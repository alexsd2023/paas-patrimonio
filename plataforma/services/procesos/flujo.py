"""El proceso TranscripcionEstandar (la gestoría, tramos 7–13 del caso).

    transcribiendo → pendiente-validacion → (espera la firma, aunque tarde días) → registrando-validacion
                   → certificando → completado

La certificación (capacidad certificacion-documental) va DESPUÉS de registrar la validación y no la
condiciona: si la capacidad no responde tras unos intentos, el proceso termina igual y la certificación
queda para la confirmación periódica. `workflow.patched` mantiene compatibles los procesos ya en marcha.

El proceso no pierde su estado si el servidor se reinicia: Temporal lo guarda en cada paso.
"""
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from services.procesos.actividades import certificar, registrar_validacion, transcribir

REINTENTOS = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_interval=timedelta(minutes=1))
REINTENTOS_CERTIFICAR = RetryPolicy(initial_interval=timedelta(seconds=5), maximum_interval=timedelta(minutes=1),
                                    maximum_attempts=5)


@workflow.defn(name="TranscripcionEstandar")
class TranscripcionEstandar:
    def __init__(self) -> None:
        self._estado = "iniciado"
        self._copia: Optional[dict] = None
        self._validadoPor: Optional[str] = None
        self._certificacion: Optional[str] = None

    @workflow.run
    async def run(self, datos: dict) -> dict:
        self._estado = "transcribiendo"
        self._copia = await workflow.execute_activity(
            transcribir, datos, start_to_close_timeout=timedelta(minutes=5), retry_policy=REINTENTOS)

        self._estado = "pendiente-validacion"
        await workflow.wait_condition(lambda: self._validadoPor is not None)

        self._estado = "registrando-validacion"
        await workflow.execute_activity(
            registrar_validacion,
            {**datos, **self._copia, "validadoPor": self._validadoPor},
            start_to_close_timeout=timedelta(minutes=2), retry_policy=REINTENTOS)

        if workflow.patched("certificacion-v1"):
            self._estado = "certificando"
            try:
                r = await workflow.execute_activity(
                    certificar, {**datos, **self._copia},
                    start_to_close_timeout=timedelta(minutes=4), retry_policy=REINTENTOS_CERTIFICAR)
                self._certificacion = r.get("certificacion")
            except ActivityError:
                self._certificacion = "error"   # la reintenta la confirmación periódica
        self._estado = "completado"
        return self.estado()

    @workflow.signal(name="validar")
    def validar(self, por: str) -> None:
        if self._validadoPor is None and self._estado == "pendiente-validacion":
            self._validadoPor = por

    @workflow.query(name="estado")
    def estado(self) -> dict:
        return {"estado": self._estado,
                "transcripcion": (self._copia or {}).get("transcripcion"),
                "modelo": (self._copia or {}).get("modelo"),
                "validadoPor": self._validadoPor,
                "certificacion": self._certificacion}
