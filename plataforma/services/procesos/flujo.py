"""El proceso TranscripcionEstandar (la gestoría, tramos 7–13 del caso).

    transcribiendo → pendiente-validacion → (espera la firma, aunque tarde días) → registrando-validacion
                   → certificando → completado

La certificación (capacidad certificacion-documental) va DESPUÉS de registrar la validación y no la
condiciona: si la capacidad no responde tras unos intentos, el proceso termina igual y la certificación
queda para la confirmación periódica. `workflow.patched` mantiene compatibles los procesos ya en marcha.

Si la certificación queda pendiente (Bitcoin tarda horas) o falla, se lanza un proceso hijo
ConfirmacionCertificacion que la comprueba cada hora hasta confirmarla (o 72 h). El hijo sigue solo:
TranscripcionEstandar termina como siempre.

El proceso no pierde su estado si el servidor se reinicia: Temporal lo guarda en cada paso.
"""
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from services.procesos.actividades import (certificar, confirmar_certificacion, registrar_validacion,
                                               transcribir)

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
                r = {}
            if self._certificacion in ("pendiente", "error") and workflow.patched("confirmacion-v1"):
                try:
                    await workflow.start_child_workflow(
                        ConfirmacionCertificacion.run,
                        {**datos, **self._copia, "cadaMinutos": r.get("cadaMinutos", 60),
                         "maxIntentos": r.get("maxIntentos", 72)},
                        id=f"confirmacion-{self._copia['transcripcion']}",
                        parent_close_policy=ParentClosePolicy.ABANDON)
                except WorkflowAlreadyStartedError:
                    pass                         # ya hay uno vigilando esa transcripción
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


@workflow.defn(name="ConfirmacionCertificacion")
class ConfirmacionCertificacion:
    """Comprueba cada `cadaMinutos` una certificación pendiente hasta confirmarla (máximo `maxIntentos`)."""

    def __init__(self) -> None:
        self._certificacion = "pendiente"
        self._intentos = 0

    @workflow.run
    async def run(self, d: dict) -> dict:
        espera = timedelta(minutes=d.get("cadaMinutos", 60))
        for _ in range(d.get("maxIntentos", 72)):
            await workflow.sleep(espera)
            self._intentos += 1
            try:
                r = await workflow.execute_activity(
                    confirmar_certificacion, d, start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=REINTENTOS_CERTIFICAR)
                self._certificacion = r.get("certificacion", self._certificacion)
            except ActivityError:
                continue                     # la capacidad o el catastro caídos: se prueba en la siguiente vuelta
            if self._certificacion == "confirmada":
                break
        return self.estado()

    @workflow.query(name="estado")
    def estado(self) -> dict:
        return {"certificacion": self._certificacion, "intentos": self._intentos}
