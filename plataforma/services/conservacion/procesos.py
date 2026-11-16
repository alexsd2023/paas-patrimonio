"""Los procesos de Temporal del gemelo patrimonial (cola «conservacion»).

    EvaluacionProgramada   lo lanza una programación de Temporal (EVALUACION_CRON, cada hora por defecto):
                           evalúa todas las zonas de todas las instituciones con gemelo.
    AlertaConservacion     uno por alerta, desde que se abre hasta que alguien la cierra. Espera las firmas de las
                           personas (reconocer, cerrar con su causa) y las registra; no pierde nada si el servidor
                           se reinicia, y en la consola de Temporal se ve quién firmó qué y cuándo.
"""
from datetime import timedelta
from typing import List, Tuple

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from services.conservacion.actividades import evaluar_todas, registrar_cierre, registrar_reconocimiento

COLA = "conservacion"
REINTENTOS = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_interval=timedelta(minutes=1),
                         non_retryable_error_types=["KeyError"])


@workflow.defn(name="EvaluacionProgramada")
class EvaluacionProgramada:
    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(evaluar_todas, start_to_close_timeout=timedelta(minutes=30),
                                               retry_policy=RetryPolicy(maximum_attempts=2))


@workflow.defn(name="AlertaConservacion")
class AlertaConservacion:
    def __init__(self) -> None:
        self._pendientes: List[Tuple[str, dict]] = []
        self._estado = "activa"
        self._firmas: List[dict] = []

    @workflow.run
    async def run(self, datos: dict) -> dict:
        while True:
            await workflow.wait_condition(lambda: bool(self._pendientes))
            tipo, firma = self._pendientes.pop(0)
            d = {**datos, **firma}
            if tipo == "reconocer":
                await workflow.execute_activity(registrar_reconocimiento, d, start_to_close_timeout=timedelta(minutes=2),
                                                retry_policy=REINTENTOS)
                self._estado = "reconocida"
            else:
                await workflow.execute_activity(registrar_cierre, d, start_to_close_timeout=timedelta(minutes=2),
                                                retry_policy=REINTENTOS)
                self._estado = "cerrada"
            self._firmas.append({"accion": tipo, **firma})
            if self._estado == "cerrada":
                return self.estado()

    @workflow.signal(name="reconocer")
    def reconocer(self, firma: dict) -> None:
        if self._estado == "activa":
            self._pendientes.append(("reconocer", firma))

    @workflow.signal(name="cerrar")
    def cerrar(self, firma: dict) -> None:
        if self._estado != "cerrada" and not any(t == "cerrar" for t, _ in self._pendientes):
            self._pendientes.append(("cerrar", firma))

    @workflow.query(name="estado")
    def estado(self) -> dict:
        return {"estado": self._estado, "firmas": self._firmas}
