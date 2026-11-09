"""Gestoría · abre y sigue los expedientes de transcripción (tramos 7 y 13 del caso).

Cuando llega «ha llegado un legajo», arranca el proceso TranscripcionEstandar en Temporal.
El id del proceso es transcripcion:<urn del legajo>: si la carta llega dos veces, Temporal
rechaza el segundo arranque y no se duplica nada.

    GET  /expedientes?activo=<urn>      estado del expediente      (token de su institución)
    POST /expedientes/validar {"activo"}  la paleógrafa firma la copia (token con rol paleografa)
    GET  /yo                              quién soy según el token
    GET  /salud

Quién firma lo dice el token, no el cuerpo de la petición: la firma queda a nombre de
la persona que inició sesión en Keycloak, y solo si es paleógrafa de esa institución.
"""
import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query

from sdk.identidad import Identidad, NoAutorizado, Verificador, token_de

from sdk.servicio import lanzar_consumidor
from sdk.trazas import con_contexto, configurar, contexto_actual, interceptores_temporal

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
        # el bucle de Temporal vive en otro hilo: le pasamos el contexto de la traza actual
        return asyncio.run_coroutine_threadsafe(con_contexto(contexto_actual(), coro), self._loop).result(timeout)

    async def _cli(self):
        if self._cliente is None:
            from temporalio.client import Client
            self._cliente = await Client.connect(self.direccion, interceptors=interceptores_temporal())
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


def crear_app(expedientes, bootstrap: Optional[str] = None, verificador=None) -> FastAPI:
    estado: dict = {}

    @asynccontextmanager
    async def ciclo(app):
        if bootstrap:
            lanzar_consumidor(bootstrap=bootstrap, grupo="gestoria", topics=["activos"],
                              tipos=["legajo.ingestado"], manejar=expedientes.abrir, estado=estado)
        yield

    app = FastAPI(title="Gestoría (expedientes)", version="0.3.0", lifespan=ciclo)

    def quien(authorization: Optional[str] = Header(None),
              x_access_token: Optional[str] = Header(None)) -> Identidad:
        if verificador is None:
            raise HTTPException(503, "identidad no configurada (KEYCLOAK_JWKS / KEYCLOAK_ISSUER)")
        try:
            return verificador.verificar(token_de(authorization, x_access_token))
        except NoAutorizado as e:
            raise HTTPException(e.codigo, e.motivo)

    def de_su_institucion(activo: str, yo: Identidad) -> None:
        partes = activo.split(":")
        if len(partes) < 5 or partes[3] != yo.tenant:
            raise HTTPException(403, f"el legajo no es de tu institución ({yo.tenant})")

    @app.get("/salud")
    def salud():
        return {"ok": True, "consumidor": estado}

    @app.get("/yo")
    def yo(yo: Identidad = Depends(quien)):
        return yo._asdict()

    @app.get("/expedientes")
    def listar(activo: str = Query(...), yo: Identidad = Depends(quien)):
        de_su_institucion(activo, yo)
        return expedientes.listar(activo)

    @app.post("/expedientes/validar")
    def validar(peticion: Dict[str, Any] = Body(...), yo: Identidad = Depends(quien)):
        activo = peticion.get("activo") or ""
        de_su_institucion(activo, yo)
        if not yo.tiene("paleografa"):
            raise HTTPException(403, "solo una paleógrafa puede validar la copia")
        try:
            return expedientes.validar(activo, yo.usuario)
        except NoEncontrado:
            raise HTTPException(404, "no hay expediente para ese legajo")
        except FueraDeTurno as e:
            raise HTTPException(409, f"el expediente no espera validación (estado: {e})")

    return app


def _verificador() -> Optional[Verificador]:
    jwks, emisor = os.environ.get("KEYCLOAK_JWKS"), os.environ.get("KEYCLOAK_ISSUER")
    return Verificador(jwks, emisor) if jwks and emisor else None


app = crear_app(ExpedientesTemporal(os.environ.get("TEMPORAL", "temporal:7233")),
                os.environ.get("KAFKA_BOOTSTRAP"), _verificador())
configurar("gestoria", app)
