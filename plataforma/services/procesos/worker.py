"""Trabajador de Temporal: ejecuta los procesos TranscripcionEstandar y sus actividades."""
import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from services.procesos.actividades import registrar_validacion, transcribir
from services.procesos.flujo import TranscripcionEstandar
from sdk.trazas import configurar, interceptores_temporal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("procesos")
COLA = "transcripcion"


async def main() -> None:
    configurar("procesos")
    direccion = os.environ.get("TEMPORAL", "temporal:7233")
    while True:
        try:
            cliente = await Client.connect(direccion, interceptors=interceptores_temporal())
            break
        except Exception as e:  # Temporal aún arrancando
            log.info("esperando a Temporal en %s (%s)", direccion, e)
            await asyncio.sleep(3)
    log.info("trabajando en la cola %s", COLA)
    await Worker(cliente, task_queue=COLA, workflows=[TranscripcionEstandar],
                 activities=[transcribir, registrar_validacion]).run()


if __name__ == "__main__":
    asyncio.run(main())
