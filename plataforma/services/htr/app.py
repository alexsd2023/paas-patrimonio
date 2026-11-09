"""Taller de copistas · HTR simulado (tramos 8–10 y 14–16 del caso).

Finge la transcripción automática para probar el flujo antes de tener Kraken:
inscribe la Transcripcion en el catastro (pendiente de validar, con su modelo) y
envía la carta htr.completado. Cuando llegue Kraken/eScriptorium, este módulo se
sustituye por otro con la MISMA API y las mismas cartas, y el resto no cambia.

Qué modelo usa lo decide el registro de modelos (MLflow): la versión con alias «produccion»
de htr-paleografico. La copia y la carta dicen esa versión, el run que la produjo y la versión
(DVC) de los datos con que se entrenó. Sin MLflow, usa MODELO (htr-mock@0.1) como antes.

    POST /transcripciones  {"activo": "<urn>", "tenant": "<tenant>"}
    GET  /salud

Idempotente: transcribir dos veces el mismo legajo deja la misma ficha y la misma carta.
"""
import logging
import os
import uuid
from typing import Any, Dict, Optional, Tuple

from fastapi import Body, FastAPI, HTTPException

from sdk.eventos import Publicador, nuevo_evento
from sdk.modelos import RegistroModelos
from sdk.registro import Registro, entidad_transcripcion
from sdk.trazas import configurar, marcar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("htr")

MODELO = os.environ.get("MODELO", "htr-mock@0.1")
ESPACIO_IDS = uuid.UUID("5b0f4c1e-7a2d-4e8b-9c3f-0d1a2b3c4d5e")
TEXTO = ("En la villa de Villanueva, a diez días del mes de março de mill e quinientos e setenta años, "
         "ante mí el escriuano público e testigos de yuso escriptos paresçió presente…")


def preparar(activo: str, tenant: str, modelo: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], dict]:
    """La ficha que se inscribe y la carta que se envía (sin red: se puede probar).

    `modelo` es lo que devuelve RegistroModelos.actual(); sin él, el modelo fijo MODELO."""
    if activo.split(":")[3:4] != [tenant]:
        raise ValueError(f"el legajo {activo} no es del tenant {tenant}")
    etiqueta = modelo["etiqueta"] if modelo else MODELO
    texto = (modelo or {}).get("artefacto", {}).get("muestra") or TEXTO
    linaje = {k: v for k, v in {"modeloRun": (modelo or {}).get("run"), "datosVersion": (modelo or {}).get("datos"),
                                "cerModelo": (modelo or {}).get("cer")}.items() if v is not None}
    lineas = max(1, texto.count(",") + 1) if modelo else 42
    ficha = entidad_transcripcion(activo, modelo=etiqueta, lineas=lineas, texto=texto, confianza=0.87,
                                  modelo_run=linaje.get("modeloRun"), datos_version=linaje.get("datosVersion"),
                                  cer=linaje.get("cerModelo"))
    carta = nuevo_evento(
        "htr.completado",
        id=str(uuid.uuid5(ESPACIO_IDS, f"htr.completado|{ficha['id']}")),
        tenant=tenant, subject=ficha["id"], source=f"/tenants/{tenant}/modulos/htr-mock",
        data={"activo": activo, "estado": "pendiente-validacion", "modelo": etiqueta, "lineas": lineas,
              "confianza": 0.87, **linaje},
    )
    return ficha, carta


def crear_app(registro=None, publicador=None, modelos: Optional[RegistroModelos] = None) -> FastAPI:
    app = FastAPI(title="HTR simulado", version="0.2.0")
    estado = {"reg": registro, "pub": publicador}
    if modelos is None and os.environ.get("MLFLOW_TRACKING_URI"):
        modelos = RegistroModelos(os.environ["MLFLOW_TRACKING_URI"], os.environ.get("HTR_MODELO", "htr-paleografico"))

    def modelo_actual() -> Optional[Dict[str, Any]]:
        return modelos.actual() if modelos else None

    def reg():
        if estado["reg"] is None:
            estado["reg"] = Registro(os.environ["SCORPIO_URL"])
        return estado["reg"]

    def pub():
        if estado["pub"] is None:
            estado["pub"] = Publicador(os.environ["KAFKA_BOOTSTRAP"], client_id="htr")
        return estado["pub"]

    @app.get("/salud")
    def salud():
        m = modelo_actual()
        return {"ok": True, "modelo": m["etiqueta"] if m else MODELO, "datos": (m or {}).get("datos"),
                "registro": "mlflow" if m else "fijo"}

    @app.post("/transcripciones")
    def transcribir(peticion: Dict[str, Any] = Body(...)):
        try:
            m = modelo_actual()
            ficha, carta = preparar(peticion["activo"], peticion["tenant"], m)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))
        etiqueta = carta["data"]["modelo"]
        marcar(paas__legajo=peticion["activo"], paas__modelo=etiqueta, paas__datos=(m or {}).get("datos") or "")
        codigo = reg().crear(peticion["tenant"], ficha)
        if codigo not in (201, 409):  # 409 = ya estaba inscrita (reintento)
            raise HTTPException(502, f"el catastro respondió {codigo} al inscribir la transcripción")
        pub().publicar(carta)
        log.info("transcripción %s (%s) y carta htr.completado", ficha["id"], etiqueta)
        return {"transcripcion": ficha["id"], "modelo": etiqueta, "lineas": carta["data"]["lineas"],
                "estado": "pendiente-validacion"}

    return app


app = crear_app()
configurar("htr", app)
