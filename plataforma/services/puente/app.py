"""Puente de eventos · NGSI-LD → CloudEvents en Kafka (tramos 5–6 del caso).

Scorpio (el catastro) avisa por HTTP cada vez que se inscribe una entidad; el puente
redacta la carta estándar y la echa al bus. En el esqueleto solo traduce una cosa:

    ActivoPatrimonial nuevo         →  legajo.ingestado   (topic activos)
    Deposito con lectura nueva      →  deposito.medicion  (topic sensores)   · gemelo digital

Endpoints
    POST /ngsi-ld/notificaciones/{tenant}   destino de la suscripción de Scorpio
    GET  /salud

Respuestas
    200  {"publicados": [ids], "ignorados": n}
    400  notificación mal formada o tenant de la ruta ≠ cabecera NGSILD-Tenant
    422  la entidad no cumple el contrato del evento (no se reintenta: no se arreglará sola)
    503  Kafka no disponible (Scorpio debe reintentar)

Idempotencia: el id del evento se deriva del id de la entidad, así que si Scorpio
repite el aviso, sale la misma carta con el mismo id y los consumidores la descartan.
"""
import logging
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, Header, HTTPException

from sdk.contratos import ContratoInvalido
from sdk.eventos import Publicador, nuevo_evento
from sdk.trazas import configurar, tramo

log = logging.getLogger("puente")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

ESPACIO_IDS = uuid.UUID("5b0f4c1e-7a2d-4e8b-9c3f-0d1a2b3c4d5e")  # fijo: no cambiar
CAMPOS_LEGAJO = ["signatura", "ark", "manifiesto", "imagenes", "ingestadoPor"]


def valor(attr: Any) -> Any:
    """Acepta el formato normalizado ({"type":"Property","value":…}) y el keyValues."""
    if isinstance(attr, dict):
        if "value" in attr:
            return attr["value"]
        if "object" in attr:
            return attr["object"]
    return attr


UMBRALES = ["temperaturaMin", "temperaturaMax", "humedadMin", "humedadMax"]


def observado(attr: Any) -> Optional[str]:
    return attr.get("observedAt") if isinstance(attr, dict) else None


def medicion(entidad: Dict[str, Any], tenant: str) -> Optional[dict]:
    """Lectura de sensores de un depósito → deposito.medicion (o None si aún no hay lectura)."""
    if "temperatura" not in entidad or "humedad" not in entidad:
        return None
    cuando = observado(entidad["humedad"]) or observado(entidad["temperatura"])
    if not cuando:
        return None
    data = {"temperatura": float(valor(entidad["temperatura"])), "humedad": float(valor(entidad["humedad"])),
            "observadoEn": cuando, "umbrales": {k: float(valor(entidad[k])) for k in UMBRALES if k in entidad}}
    if "nombre" in entidad:
        data["nombre"] = valor(entidad["nombre"])
    return nuevo_evento(
        "deposito.medicion",
        id=str(uuid.uuid5(ESPACIO_IDS, f"deposito.medicion|{entidad.get('id')}|{cuando}")),
        tenant=tenant, subject=entidad.get("id", ""), source=f"/tenants/{tenant}/servicios/puente", data=data)


def a_evento(entidad: Dict[str, Any], tenant: str) -> Optional[dict]:
    """Traduce una entidad notificada a su CloudEvent, o None si no le toca carta."""
    if str(entidad.get("type", "")).endswith("Deposito"):
        return medicion(entidad, tenant)
    if not str(entidad.get("type", "")).endswith("ActivoPatrimonial"):
        return None
    data = {k: valor(entidad[k]) for k in CAMPOS_LEGAJO if k in entidad}
    return nuevo_evento(
        "legajo.ingestado",
        id=str(uuid.uuid5(ESPACIO_IDS, f"legajo.ingestado|{entidad.get('id')}")),
        tenant=tenant,
        subject=entidad.get("id", ""),
        source=f"/tenants/{tenant}/servicios/puente",
        data=data,
    )


def crear_app(publicador=None) -> FastAPI:
    app = FastAPI(title="Puente NGSI-LD → CloudEvents", version="0.1.0")
    estado = {"pub": publicador}

    def pub():
        if estado["pub"] is None:
            estado["pub"] = Publicador(os.environ["KAFKA_BOOTSTRAP"], client_id="puente")
        return estado["pub"]

    @app.get("/salud")
    def salud():
        return {"ok": True}

    @app.post("/ngsi-ld/notificaciones/{tenant}")
    def notificar(tenant: str, notificacion: Dict[str, Any] = Body(...),
                  ngsild_tenant: Optional[str] = Header(None)):
        if ngsild_tenant and ngsild_tenant != tenant:
            raise HTTPException(400, f"tenant de la ruta ({tenant}) ≠ cabecera NGSILD-Tenant ({ngsild_tenant})")
        entidades = notificacion.get("data")
        if not isinstance(entidades, list):
            raise HTTPException(400, "la notificación no trae una lista 'data' de entidades")

        publicados, ignorados = [], 0
        for entidad in entidades:
            try:
                ev = a_evento(entidad, tenant)
            except ContratoInvalido as e:
                log.warning("entidad %s rechazada: %s", entidad.get("id"), e)
                raise HTTPException(422, {"entidad": entidad.get("id"), "errores": e.errores})
            if ev is None:
                ignorados += 1
                continue
            traza = valor(entidad.get("traza"))
            try:
                with tramo(f"aviso del catastro → {ev['type']}", padre={"traceparent": traza} if traza else None,
                           paas__legajo=ev["subject"] if ev["type"] == "legajo.ingestado" else None,
                           paas__tenant=tenant):
                    pub().publicar(ev)
            except Exception as e:  # Kafka caído, timeout…
                log.error("no se pudo publicar %s: %s", ev["id"], e)
                raise HTTPException(503, f"Kafka no disponible: {e}")
            log.info("publicado %s %s tenant=%s", ev["type"], ev["subject"], tenant)
            publicados.append(ev["id"])
        return {"publicados": publicados, "ignorados": ignorados}

    return app


app = crear_app()
configurar("puente", app)
