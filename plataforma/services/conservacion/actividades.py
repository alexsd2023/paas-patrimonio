"""Actividades de los procesos del gemelo patrimonial: lo que el proceso encarga al servicio de conservación.
Son idempotentes (Temporal las reintenta)."""
import asyncio

from temporalio import activity

GEMELO = None   # services.conservacion.patrimonial.GemeloPatrimonial; lo pone el servicio al arrancar


@activity.defn(name="evaluar_todas")
async def evaluar_todas() -> dict:
    return await asyncio.to_thread(GEMELO.evaluar_todo)


@activity.defn(name="registrar_reconocimiento")
async def registrar_reconocimiento(d: dict) -> None:
    await asyncio.to_thread(GEMELO.registrar_reconocimiento, d["tenant"], d["alerta"], d["por"])


@activity.defn(name="registrar_cierre")
async def registrar_cierre(d: dict) -> None:
    await asyncio.to_thread(GEMELO.registrar_cierre, d["tenant"], d["alerta"], d["por"], d["causa"])
