"""Taller de copistas · HTR simulado (tramos 8–10 del caso).

Finge la transcripción automática para probar el flujo antes de tener Kraken:
inscribe la Transcripcion en el catastro (pendiente de validar, con su modelo) y
envía la carta htr.completado. Cuando llegue Kraken/eScriptorium, este módulo se
sustituye por otro con la MISMA API y las mismas cartas, y el resto no cambia.

    POST /transcripciones  {"activo": "<urn>", "tenant": "<tenant>"}
    GET  /salud

Idempotente: transcribir dos veces el mismo legajo deja la misma ficha y la misma carta.
"""
import logging
import os
import uuid
from typing import Any, Dict, Tuple

from fastapi import Body, FastAPI, HTTPException

from sdk.eventos import Publicador, nuevo_evento
from sdk.registro import Registro, entidad_transcripcion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("htr")

MODELO = os.environ.get("MODELO", "htr-mock@0.1")
ESPACIO_IDS = uuid.UUID("5b0f4c1e-7a2d-4e8b-9c3f-0d1a2b3c4d5e")
TEXTO = ("En la villa de Villanueva, a diez días del mes de março de mill e quinientos e setenta años, "
         "ante mí el escriuano público e testigos de yuso escriptos paresçió presente…")


def preparar(activo: str, tenant: str) -> Tuple[Dict[str, Any], dict]:
    """La ficha que se inscribe y la carta que se envía (sin red: se puede probar)."""
    if activo.split(":")[3:4] != [tenant]:
        raise ValueError(f"el legajo {activo} no es del tenant {tenant}")
    ficha = entidad_transcripcion(activo, modelo=MODELO, lineas=42, texto=TEXTO, confianza=0.87)
    carta = nuevo_evento(
        "htr.completado",
        id=str(uuid.uuid5(ESPACIO_IDS, f"htr.completado|{ficha['id']}")),
        tenant=tenant, subject=ficha["id"], source=f"/tenants/{tenant}/modulos/htr-mock",
        data={"activo": activo, "estado": "pendiente-validacion", "modelo": MODELO, "lineas": 42, "confianza": 0.87},
    )
    return ficha, carta


def crear_app(registro=None, publicador=None) -> FastAPI:
    app = FastAPI(title="HTR simulado", version="0.1.0")
    estado = {"reg": registro, "pub": publicador}

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
        return {"ok": True, "modelo": MODELO}

    @app.post("/transcripciones")
    def transcribir(peticion: Dict[str, Any] = Body(...)):
        try:
            ficha, carta = preparar(peticion["activo"], peticion["tenant"])
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))
        codigo = reg().crear(peticion["tenant"], ficha)
        if codigo not in (201, 409):  # 409 = ya estaba inscrita (reintento)
            raise HTTPException(502, f"el catastro respondió {codigo} al inscribir la transcripción")
        pub().publicar(carta)
        log.info("transcripción %s (%s) y carta htr.completado", ficha["id"], MODELO)
        return {"transcripcion": ficha["id"], "modelo": MODELO, "lineas": 42, "estado": "pendiente-validacion"}

    return app


app = crear_app()
