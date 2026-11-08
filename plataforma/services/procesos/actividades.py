"""Actividades del proceso de transcripción: lo que el proceso encarga a otros.

Temporal las reintenta solas si fallan (el taller caído, el catastro lento…).
Por eso son idempotentes.
"""
import asyncio
import json
import os
import urllib.request
import uuid

from temporalio import activity

ESPACIO_IDS = uuid.UUID("5b0f4c1e-7a2d-4e8b-9c3f-0d1a2b3c4d5e")


def _post(url: str, cuerpo: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


@activity.defn(name="transcribir")
async def transcribir(datos: dict) -> dict:
    """Encarga la copia al taller (módulo HTR, por su API)."""
    url = os.environ.get("HTR_URL", "http://htr:8080").rstrip("/") + "/transcripciones"
    return await asyncio.to_thread(_post, url, {"activo": datos["activo"], "tenant": datos["tenant"]})


def _registrar_validacion(d: dict) -> dict:
    from sdk.eventos import Publicador, nuevo_evento
    from sdk.registro import Registro

    prop = lambda v: {"type": "Property", "value": v}  # noqa: E731
    codigo = Registro(os.environ["SCORPIO_URL"]).anadir_atributos(
        d["tenant"], d["transcripcion"], {"estado": prop("validada"), "validadoPor": prop(d["validadoPor"])})
    if codigo not in (204, 207):
        raise RuntimeError(f"el catastro respondió {codigo} al marcar la transcripción como validada")
    carta = nuevo_evento(
        "transcripcion.validada",
        id=str(uuid.uuid5(ESPACIO_IDS, f"transcripcion.validada|{d['transcripcion']}")),
        tenant=d["tenant"], subject=d["transcripcion"], source=f"/tenants/{d['tenant']}/servicios/procesos",
        data={"activo": d["activo"], "estado": "validada", "modelo": d["modelo"], "validadoPor": d["validadoPor"]},
    )
    Publicador(os.environ["KAFKA_BOOTSTRAP"], client_id="procesos").publicar(carta)
    return {"evento": carta["id"]}


@activity.defn(name="registrar_validacion")
async def registrar_validacion(d: dict) -> dict:
    """Marca la transcripción como validada en el catastro y envía transcripcion.validada."""
    return await asyncio.to_thread(_registrar_validacion, d)
