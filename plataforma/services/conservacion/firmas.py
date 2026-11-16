"""Conservación ↔ Temporal: el worker de la cola «conservacion», la programación de la evaluación y las firmas.

Todo corre en un bucle asyncio propio, en un hilo (como el catálogo y la gestoría). Si Temporal aún no está,
se reintenta solo; mientras tanto las firmas se registran directamente (FirmasDirectas) para no bloquear a nadie.
"""
import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from services.conservacion.patrimonial import FirmasDirectas

log = logging.getLogger("conservacion.temporal")
PROGRAMACION = "evaluacion-en15757"


class FirmasTemporal:
    def __init__(self, gemelo, direccion: str, cron: str = "0 * * * *"):
        self.g, self.direccion, self.cron = gemelo, direccion, cron
        self.directas = FirmasDirectas(gemelo)
        self._loop = asyncio.new_event_loop()
        self._cliente = None
        self.listo = False
        threading.Thread(target=self._loop.run_forever, daemon=True, name="temporal-conservacion").start()

    def _call(self, coro, timeout: float = 20):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _cli(self):
        if self._cliente is None:
            from temporalio.client import Client
            from sdk.trazas import interceptores_temporal
            self._cliente = await Client.connect(self.direccion, interceptors=interceptores_temporal())
        return self._cliente

    # ---------- worker y programación ----------
    def arrancar(self) -> None:
        from temporalio.worker import Worker
        from services.conservacion import actividades
        from services.conservacion.procesos import COLA, AlertaConservacion, EvaluacionProgramada
        actividades.GEMELO = self.g

        async def go():
            while True:
                try:
                    cli = await self._cli()
                    await self._programar(cli)
                    w = Worker(cli, task_queue=COLA, workflows=[EvaluacionProgramada, AlertaConservacion],
                               activities=[actividades.evaluar_todas, actividades.registrar_reconocimiento,
                                           actividades.registrar_cierre],
                               activity_executor=ThreadPoolExecutor(4))
                    self.listo = True
                    log.info("worker de conservación en la cola %s; evaluación programada «%s»", COLA, self.cron)
                    await w.run()
                except Exception as e:  # noqa: BLE001  Temporal aún no está
                    self.listo, self._cliente = False, None
                    log.warning("conservación sin Temporal (%s); reintento en 5 s", e)
                    await asyncio.sleep(5)
        asyncio.run_coroutine_threadsafe(go(), self._loop)

    async def _programar(self, cli) -> None:
        from temporalio.client import (Schedule, ScheduleActionStartWorkflow, ScheduleAlreadyRunningError,
                                       ScheduleSpec, ScheduleUpdate)
        from services.conservacion.procesos import COLA
        programa = Schedule(action=ScheduleActionStartWorkflow("EvaluacionProgramada", id="evaluacion-programada",
                                                               task_queue=COLA),
                            spec=ScheduleSpec(cron_expressions=[self.cron]))
        try:
            await cli.create_schedule(PROGRAMACION, programa)
        except ScheduleAlreadyRunningError:
            async def actualizar(_entrada):
                return ScheduleUpdate(schedule=programa)
            await cli.get_schedule_handle(PROGRAMACION).update(actualizar)   # por si cambió EVALUACION_CRON

    # ---------- firmas ----------
    def _firmar(self, tenant: str, aid: str, senal: str, firma: dict) -> None:
        from services.conservacion.procesos import COLA

        async def go():
            await (await self._cli()).start_workflow("AlertaConservacion", {"tenant": tenant, "alerta": aid},
                                                     id=f"alerta:{aid}", task_queue=COLA,
                                                     start_signal=senal, start_signal_args=[firma])
        self._call(go())

    def abrir(self, tenant: str, aid: str) -> None:
        if not self.listo:
            return
        from services.conservacion.procesos import COLA

        async def go():
            from temporalio.exceptions import WorkflowAlreadyStartedError
            try:
                await (await self._cli()).start_workflow("AlertaConservacion", {"tenant": tenant, "alerta": aid},
                                                         id=f"alerta:{aid}", task_queue=COLA)
            except WorkflowAlreadyStartedError:
                pass
        try:
            self._call(go())
        except Exception as e:  # noqa: BLE001  la alerta ya está en el catastro; el proceso se crea al firmar
            log.warning("no se pudo crear el proceso de %s: %s", aid, e)

    def reconocer(self, tenant: str, aid: str, por: str) -> None:
        self.g.comprobar(tenant, aid, "reconocer")
        if not self.listo:
            return self.directas.reconocer(tenant, aid, por)
        self._firmar(tenant, aid, "reconocer", {"por": por})

    def cerrar(self, tenant: str, aid: str, por: str, causa: str) -> None:
        self.g.comprobar(tenant, aid, "cerrar")
        if not self.listo:
            return self.directas.cerrar(tenant, aid, por, causa)
        self._firmar(tenant, aid, "cerrar", {"por": por, "causa": causa})

    def evaluar_ahora(self) -> None:
        """Lanza la evaluación programada en este momento (además de la de cada hora)."""
        async def go():
            await (await self._cli()).get_schedule_handle(PROGRAMACION).trigger()
        self._call(go())
