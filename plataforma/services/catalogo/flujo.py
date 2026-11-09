"""FlujoReceta · el único workflow que ejecuta cualquier flujo que defina un ciudadano.

Recorre el plan: cada servicio es una actividad (con reintentos), cada firma espera la señal
``firmar`` de una persona con el rol pedido. Al final, si la receta lo pide, publica el resultado.
La consulta ``estado`` devuelve dónde va y el documento de cada momento.
"""
from datetime import timedelta
from typing import Any, Dict, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from services.catalogo.maquina import FirmaNoValida, Maquina

PROCESO, COLA = "FlujoReceta", "flujos"
REINTENTOS = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2),
                         non_retryable_error_types=["NoReintentable"])


def _causa(e: BaseException) -> str:
    while getattr(e, "cause", None) is not None:
        e = e.cause
    return getattr(e, "message", None) or str(e)


@workflow.defn(name=PROCESO)
class FlujoReceta:
    def __init__(self) -> None:
        self.m: Optional[Maquina] = None
        self._firma: Optional[Dict[str, Any]] = None

    @workflow.run
    async def run(self, flujo: Dict[str, Any]) -> Dict[str, Any]:
        self.m = m = Maquina(flujo)
        ahora = lambda: workflow.now().isoformat(timespec="seconds")  # noqa: E731
        try:
            doc = await workflow.execute_activity(
                "leer_entrada", {"tenant": flujo["tenant"], "entrada": flujo["entrada"], "tipo": flujo["plan"]["entrada"]},
                start_to_close_timeout=timedelta(seconds=30), retry_policy=REINTENTOS)
            m.con_documento(doc)
            while m.actual() is not None:
                p = m.empieza(ahora())
                if p["clase"] == "servicio":
                    r = await workflow.execute_activity(
                        "ejecutar_servicio",
                        {"servicio": p["servicio"], "parametros": p["parametros"], "documento": m.e["documento"],
                         "tenant": flujo["tenant"], "roles": flujo["roles"]},
                        start_to_close_timeout=timedelta(minutes=15), retry_policy=REINTENTOS)
                    m.servicio_hecho(r, ahora())
                    continue
                self._firma = None
                while True:
                    await workflow.wait_condition(lambda: self._firma is not None)
                    f, self._firma = self._firma, None
                    try:
                        m.firma(f["usuario"], f["roles"], f["decision"], f.get("comentario", ""), ahora())
                        break
                    except FirmaNoValida:
                        continue  # la API ya lo comprueba; una firma inválida se ignora
                if m.e["estado"] == "rechazado":
                    return m.e
            resultado = None
            if m.e["publicar"]:
                resultado = await workflow.execute_activity(
                    "publicar_resultado",
                    {"id": flujo["id"], "tenant": flujo["tenant"], "usuario": flujo["usuario"], "nombre": m.e["nombre"],
                     "tipo": m.e["tipo"], "documento": m.e["documento"], "procedencia": m.procedencia()},
                    start_to_close_timeout=timedelta(seconds=60), retry_policy=REINTENTOS)
            m.termina(resultado, ahora())
        except ActivityError as e:
            m.falla(_causa(e), ahora())
        return m.e

    @workflow.signal
    def firmar(self, firma: Dict[str, Any]) -> None:
        self._firma = firma

    @workflow.query
    def estado(self) -> Dict[str, Any]:
        return self.m.e if self.m else {"estado": "arrancando"}
