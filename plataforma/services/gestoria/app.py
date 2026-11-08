"""Gestoría · abre y sigue los expedientes de transcripción (tramos 7 y 13 del caso).

Cuando llega «ha llegado un legajo», arranca el proceso TranscripcionEstandar en Temporal.
El id del proceso es transcripcion:<urn del legajo>: si la carta llega dos veces, Temporal
rechaza el segundo arranque y no se duplica nada.

    GET  /expedientes?activo=<urn>                 estado del expediente
    POST /expedientes/validar {"activo", "por"}     la paleógrafa firma la copia
    GET  /salud

Hasta que llegue la puerta (Keycloak + APISIX), la validación no comprueba quién firma.
"""
import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query

from sdk.servicio import lanzar_consumidor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("gestoria")

PROCESO, COLA = "TranscripcionEstandar", "transcripcion"


class NoEncontrado(LookupError):
    pass


class FueraDeTurno(ValueError):
    pass


class ExpedientesTemporal:
    """Expedientes = procesos en Temporal. El cliente es asíncrono; lo usamos desde hilos
    (el consumidor del bus y las peticiones HTTP) a través de un bucle propio."""

    def __init__(self, direccion: str):
        self.direccion = direccion
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="temporal").start()
        self._cliente = None

    def _call(self, coro, timeout: float = 30):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _cli(self):
        if self._cliente is None:
            from temporalio.client import Client
            self._cliente = await Client.connect(self.direccion)
        return self._cliente

    # --- abrir (desde el bus) ---
    def abrir(self, ev: dict) -> bool:
        if ev["type"] != "legajo.ingestado":
            return False
        return self._call(self._abrir(ev))

    async def _abrir(self, ev: dict) -> bool:
        from temporalio.exceptions import WorkflowAlreadyStartedError
        cli = await self._cli()
        try:
            await cli.start_workflow(PROCESO, {"activo": ev["subject"], "tenant": ev["tenant"],
                                               "signatura": ev["data"]["signatura"]},
                                     id=f"transcripcion:{ev['subject']}", task_queue=COLA)
            log.info("proceso %s arrancado para %s", PROCESO, ev["subject"])
            return True
        except WorkflowAlreadyStartedError:
            return False

    # --- consultar ---
    def listar(self, activo: str) -> List[Dict[str, Any]]:
        return self._call(self._listar(activo))

    async def _listar(self, activo: str) -> List[Dict[str, Any]]:
        from temporalio.service import RPCError, RPCStatusCode
        h = (await self._cli()).get_workflow_handle(f"transcripcion:{activo}")
        try:
            d = await h.describe()
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                return []
            raise
        try:
            q = await h.query("estado")
        except Exception:  # sin trabajador disponible
            q = {"estado": d.status.name.lower() if d.status else "desconocido"}
        return [{"id": h.id, "activo": activo, "tenant": activo.split(":")[3], "proceso": PROCESO,
                 "temporal": d.status.name if d.status else None, **q}]

    # --- validar (la paleógrafa) ---
    def validar(self, activo: str, por: str) -> Dict[str, Any]:
        return self._call(self._validar(activo, por))

    async def _validar(self, activo: str, por: str) -> Dict[str, Any]:
        exps = await self._listar(activo)
        if not exps:
            raise NoEncontrado(activo)
        if exps[0]["estado"] != "pendiente-validacion":
            raise FueraDeTurno(exps[0]["estado"])
        await (await self._cli()).get_workflow_handle(exps[0]["id"]).signal("validar", por)
        log.info("validación de %s firmada por %s", activo, por)
        return {"activo": activo, "validadoPor": por, "estado": "validacion-recibida"}


def crear_app(expedientes, bootstrap: Optional[str] = None) -> FastAPI:
    estado: dict = {}

    @asynccontextmanager
    async def ciclo(app):
        if bootstrap:
            lanzar_consumidor(bootstrap=bootstrap, grupo="gestoria", topics=["activos"],
                              tipos=["legajo.ingestado"], manejar=expedientes.abrir, estado=estado)
        yield

    app = FastAPI(title="Gestoría (expedientes)", version="0.2.0", lifespan=ciclo)

    @app.get("/salud")
    def salud():
        return {"ok": True, "consumidor": estado}

    @app.get("/expedientes")
    def listar(activo: str = Query(...)):
        return expedientes.listar(activo)

    @app.post("/expedientes/validar")
    def validar(peticion: Dict[str, Any] = Body(...)):
        try:
            return expedientes.validar(peticion["activo"], peticion["por"])
        except KeyError as e:
            raise HTTPException(400, f"falta {e}")
        except NoEncontrado:
            raise HTTPException(404, "no hay expediente para ese legajo")
        except FueraDeTurno as e:
            raise HTTPException(409, f"el expediente no espera validación (estado: {e})")

    return app


app = crear_app(ExpedientesTemporal(os.environ.get("TEMPORAL", "temporal:7233")), os.environ.get("KAFKA_BOOTSTRAP"))
