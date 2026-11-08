"""El proceso TranscripcionEstandar en un Temporal de pruebas, con actividades simuladas.

Necesita descargar el servidor de pruebas de Temporal la primera vez; si no hay red, se omite.
"""
import asyncio
import uuid

import pytest

temporalio = pytest.importorskip("temporalio")
from temporalio import activity  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from services.procesos.flujo import TranscripcionEstandar  # noqa: E402

registro = []


@activity.defn(name="transcribir")
async def transcribir_falso(datos: dict) -> dict:
    registro.append(("transcribir", datos["activo"]))
    return {"transcripcion": datos["activo"].replace("ActivoPatrimonial", "Transcripcion") + "-t1",
            "modelo": "htr-mock@0.1", "lineas": 42, "estado": "pendiente-validacion"}


@activity.defn(name="registrar_validacion")
async def validacion_falsa(d: dict) -> dict:
    registro.append(("validacion", d["validadoPor"]))
    return {"evento": "x"}


def test_proceso_espera_la_firma_y_termina():
    async def caso():
        try:
            env = await WorkflowEnvironment.start_time_skipping()
        except Exception as e:  # sin red para descargar el servidor de pruebas
            pytest.skip(f"servidor de pruebas de Temporal no disponible: {e}")
        async with env:
            async with Worker(env.client, task_queue="t", workflows=[TranscripcionEstandar],
                              activities=[transcribir_falso, validacion_falsa]):
                h = await env.client.start_workflow(
                    TranscripcionEstandar.run,
                    {"activo": "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001",
                     "tenant": "archivo-villanueva", "signatura": "TEST-001"},
                    id=f"t-{uuid.uuid4()}", task_queue="t")
                for _ in range(50):
                    if (await h.query(TranscripcionEstandar.estado))["estado"] == "pendiente-validacion":
                        break
                    await asyncio.sleep(0.1)
                assert (await h.query(TranscripcionEstandar.estado))["estado"] == "pendiente-validacion"
                await h.signal(TranscripcionEstandar.validar, "paleografa-test")
                fin = await h.result()
                assert fin["estado"] == "completado" and fin["validadoPor"] == "paleografa-test"
                assert ("validacion", "paleografa-test") in registro

    asyncio.run(caso())
