"""Catálogo de capacidades (servicios y flujos) y de conectores · núcleo del PaaS.

Servicios (cualquiera con sesión ve los que su institución y su rol pueden usar):
    GET  /servicios                         el catálogo
    GET  /servicios/{id}                    un servicio (su manifiesto)
    POST /servicios/{id}/trabajos           {"entrada", "parametros"?} → {"id"}   usarlo suelto
    GET  /trabajos/{id}                     estado y resultado
    GET  /uso                               trabajos de hoy de mi institución, por servicio

Flujos (recetas que encadenan servicios y firmas):
    GET  /plantillas                        recetas de partida (flujos/*.yaml)
    POST /flujos/validar   {"receta"}       el plan, o la lista de errores
    POST /flujos           {"receta", "entrada": {"activo"} | {"documento"}}  → lanza
    GET  /flujos                            los de mi institución
    GET  /flujos/{id}                       estado, pasos y documento
    POST /flujos/{id}/firmar {"decision": aprueba|rechaza, "comentario"?}

Conectores (traen o llevan datos de los sistemas que la institución ya tiene):
    GET  /conectores                        los que puedo usar, con su última ejecución
    GET  /conectores/{id}                   manifiesto, mi configuración y mis ejecuciones
    PUT  /conectores/{id}/configuracion     los valores del formulario de su conector.yaml
    POST /conectores/{id}/ejecuciones       ejecutarlo ahora   ·   GET /ejecuciones/{id}   ·   POST /ejecuciones/{id}/parar
    GET  /registros/{tipo}                  lo que los conectores han escrito en el catastro (p. ej. RegistroCatalografico)

Por la puerta: /api/v1/servicios…, /api/v1/trabajos…, /api/v1/flujos…, /api/v1/plantillas, /api/v1/conectores…,
/api/v1/ejecuciones…, /api/v1/registros….
"""
import asyncio
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException

from sdk.identidad import Identidad, NoAutorizado, Verificador, token_de
from sdk.servicios import RAIZ, DocumentoInvalido
from services.catalogo.catalogo import Catalogo, CuotaAgotada, SinPermiso, Trabajos, descubrir
from services.catalogo.secretos import PLATAFORMA
from services.catalogo.recetas import RecetaInvalida, planificar
from sdk.conectores import ConfiguracionInvalida

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("catalogo")
PLANTILLAS = Path(os.environ.get("PLANTILLAS_DIR", RAIZ / "flujos"))


def cargar_plantillas(carpeta: Path = PLANTILLAS) -> List[Dict[str, Any]]:
    import yaml
    out = []
    for p in sorted(Path(carpeta).glob("*.yaml")):
        try:
            out.append({"id": p.stem, "receta": yaml.safe_load(p.read_text(encoding="utf-8")), "yaml": p.read_text(encoding="utf-8")})
        except (OSError, ValueError) as e:
            log.error("plantilla %s no válida: %s", p.name, e)
    return out


class Indice:
    """Qué flujos ha lanzado cada institución (Temporal guarda el resto)."""

    def __init__(self, ruta: Optional[str] = None):
        self.ruta = ruta or os.path.join(tempfile.gettempdir(), "catalogo-flujos.db")
        self._lock = threading.Lock()
        with self._con() as c:
            c.execute("create table if not exists flujos (id text primary key, tenant text, usuario text,"
                      " nombre text, creado real, plan text)")

    def _con(self):
        return sqlite3.connect(self.ruta)

    def apuntar(self, fid, tenant, usuario, nombre, plan):
        with self._lock, self._con() as c:
            c.execute("insert into flujos values (?,?,?,?,?,?)", (fid, tenant, usuario, nombre, time.time(), json.dumps(plan)))

    def de(self, tenant: str, limite: int = 100) -> List[Dict[str, Any]]:
        with self._con() as c:
            filas = c.execute("select id, usuario, nombre, creado from flujos where tenant=? order by creado desc limit ?",
                              (tenant, limite)).fetchall()
        return [{"id": f[0], "lanzadoPor": f[1], "nombre": f[2], "creado": f[3]} for f in filas]

    def tenant_de(self, fid: str) -> Optional[str]:
        with self._con() as c:
            f = c.execute("select tenant from flujos where id=?", (fid,)).fetchone()
        return f[0] if f else None


class FlujosTemporal:
    """Arranca, consulta y firma flujos en Temporal desde hilos (como la gestoría)."""

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
            from sdk.trazas import interceptores_temporal
            self._cliente = await Client.connect(self.direccion, interceptors=interceptores_temporal())
        return self._cliente

    def lanzar(self, flujo: Dict[str, Any]) -> None:
        from services.catalogo.flujo import COLA, PROCESO

        async def go():
            await (await self._cli()).start_workflow(PROCESO, flujo, id=f"flujo:{flujo['id']}", task_queue=COLA)
        self._call(go())

    def estado(self, fid: str) -> Dict[str, Any]:
        async def go():
            h = (await self._cli()).get_workflow_handle(f"flujo:{fid}")
            try:
                return await h.query("estado")
            except Exception:  # noqa: BLE001  terminado: el resultado del workflow es el estado final
                return await h.result()
        return self._call(go())

    def firmar(self, fid: str, firma: Dict[str, Any]) -> None:
        async def go():
            await (await self._cli()).get_workflow_handle(f"flujo:{fid}").signal("firmar", firma)
        self._call(go())

    def arrancar_worker(self, actividades) -> None:
        """El worker de FlujoReceta vive en este mismo servicio (cola «flujos»)."""
        from concurrent.futures import ThreadPoolExecutor
        from temporalio.worker import Worker
        from services.catalogo.flujo import COLA, FlujoReceta

        async def go():
            while True:
                try:
                    w = Worker(await self._cli(), task_queue=COLA, workflows=[FlujoReceta],
                               activities=actividades.todas(), activity_executor=ThreadPoolExecutor(8))
                    log.info("worker de flujos escuchando en la cola %s", COLA)
                    await w.run()
                except Exception as e:  # noqa: BLE001  Temporal aún no está: se reintenta
                    log.warning("worker de flujos sin Temporal (%s); reintento en 5 s", e)
                    self._cliente = None
                    await asyncio.sleep(5)
        asyncio.run_coroutine_threadsafe(go(), self._loop)


def crear_app(*, verificador, catalogo: Catalogo, flujos, indice: Indice, plantillas=None, conectores=None) -> FastAPI:
    trabajos = Trabajos(catalogo)
    plantillas = cargar_plantillas() if plantillas is None else plantillas
    app = FastAPI(title="Catálogo de servicios y flujos", version="0.1.0")

    def yo(authorization: Optional[str] = Header(None), x_access_token: Optional[str] = Header(None)) -> Identidad:
        try:
            return verificador.verificar(token_de(authorization, x_access_token))
        except NoAutorizado as e:
            raise HTTPException(e.codigo, e.motivo)

    @app.get("/salud")
    def salud():
        return {"ok": True, "servicios": len(catalogo.servicios), "plantillas": len(plantillas)}

    # ---------- servicios ----------
    @app.get("/servicios")
    def servicios(quien: Identidad = Depends(yo)):
        return [m.publico() for m in catalogo.visibles(quien.roles, quien.tenant)]

    @app.get("/servicios/{sid}")
    def servicio(sid: str, quien: Identidad = Depends(yo)):
        try:
            return catalogo.comprobar(sid, quien.roles, quien.tenant).publico()
        except KeyError:
            raise HTTPException(404, f"no hay ningún servicio {sid}")
        except SinPermiso as e:
            raise HTTPException(403, str(e))

    @app.post("/servicios/{sid}/trabajos", status_code=202)
    def trabajo(sid: str, peticion: Dict[str, Any] = Body(...), quien: Identidad = Depends(yo)):
        try:
            return trabajos.lanzar(sid, peticion.get("entrada"), peticion.get("parametros"), tenant=quien.tenant,
                                   usuario=quien.usuario, roles=quien.roles)
        except KeyError:
            raise HTTPException(404, f"no hay ningún servicio {sid}")
        except SinPermiso as e:
            raise HTTPException(403, str(e))
        except DocumentoInvalido as e:
            raise HTTPException(422, str(e))

    @app.get("/trabajos/{tid}")
    def ver_trabajo(tid: str, quien: Identidad = Depends(yo)):
        t = trabajos.ver(tid, quien.tenant)
        if not t:
            raise HTTPException(404, "no existe ese trabajo en tu institución")
        return t

    @app.get("/uso")
    def uso(quien: Identidad = Depends(yo)):
        return catalogo.contador.uso(quien.tenant)

    # ---------- flujos ----------
    @app.get("/plantillas")
    def ver_plantillas(quien: Identidad = Depends(yo)):
        return plantillas

    def plan_de(receta, quien):
        try:
            return planificar(receta, catalogo, roles=quien.roles, tenant=quien.tenant)
        except RecetaInvalida as e:
            raise HTTPException(422, {"errores": e.errores})

    @app.post("/flujos/validar")
    def validar(peticion: Dict[str, Any] = Body(...), quien: Identidad = Depends(yo)):
        return plan_de(peticion.get("receta"), quien)

    @app.post("/flujos", status_code=202)
    def lanzar(peticion: Dict[str, Any] = Body(...), quien: Identidad = Depends(yo)):
        plan = plan_de(peticion.get("receta"), quien)
        entrada = peticion.get("entrada") or {}
        if not ({"activo"} == set(entrada) or {"documento"} == set(entrada)):
            raise HTTPException(422, "entrada: {\"activo\": <urn de un legajo>} o {\"documento\": {...}}")
        if "activo" in entrada and str(entrada["activo"]).split(":")[3:4] != [quien.tenant]:
            raise HTTPException(403, "el legajo no es de tu institución")
        fid = uuid.uuid4().hex[:12]
        flujo = {"id": fid, "tenant": quien.tenant, "usuario": quien.usuario, "roles": list(quien.roles),
                 "plan": plan, "entrada": entrada}
        try:
            flujos.lanzar(flujo)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"Procesos (Temporal) no responde: {e}")
        indice.apuntar(fid, quien.tenant, quien.usuario, plan["nombre"], plan)
        return {"id": fid, "estado": "en-curso", "plan": plan}

    @app.get("/flujos")
    def mis_flujos(quien: Identidad = Depends(yo)):
        return indice.de(quien.tenant)

    def del_tenant(fid, quien):
        if indice.tenant_de(fid) != quien.tenant:
            raise HTTPException(404, "no existe ese flujo en tu institución")

    @app.get("/flujos/{fid}")
    def ver_flujo(fid: str, quien: Identidad = Depends(yo)):
        del_tenant(fid, quien)
        try:
            return flujos.estado(fid)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"Procesos (Temporal) no responde: {e}")

    @app.post("/flujos/{fid}/firmar")
    def firmar(fid: str, peticion: Dict[str, Any] = Body(...), quien: Identidad = Depends(yo)):
        """Quién firma lo dice el token. Se comprueba el rol antes de mandar la señal."""
        del_tenant(fid, quien)
        decision = peticion.get("decision")
        if decision not in ("aprueba", "rechaza"):
            raise HTTPException(422, "decision: aprueba | rechaza")
        e = flujos.estado(fid)
        from services.catalogo.maquina import Maquina
        m = Maquina.__new__(Maquina)
        m.e = e
        motivo = m.puede_firmar(quien.usuario, list(quien.roles))
        if motivo:
            raise HTTPException(409, motivo)
        flujos.firmar(fid, {"usuario": quien.usuario, "roles": list(quien.roles), "decision": decision,
                            "comentario": str(peticion.get("comentario") or "")[:2000]})
        return {"ok": True, "decision": decision, "firmadoPor": quien.usuario}

    # ---------- conectores ----------
    def conector_de(cid, quien):
        if conectores is None:
            raise HTTPException(404, "no hay conectores")
        try:
            return conectores.comprobar(cid, list(quien.roles), quien.tenant)
        except KeyError:
            raise HTTPException(404, f"no hay ningún conector {cid}")
        except PermissionError as e:
            raise HTTPException(403, str(e))

    @app.get("/conectores")
    def ver_conectores(quien: Identidad = Depends(yo)):
        if conectores is None:
            return []
        out = []
        for c in conectores.visibles(list(quien.roles), quien.tenant):
            ult = conectores.ejecuciones(c.id, quien.tenant, 1)
            out.append({**c.publico(), "configurado": conectores.configuracion(c.id, quien.tenant) is not None,
                        "ultima": ult[0] if ult else None})
        return out

    @app.get("/conectores/{cid}")
    def ver_conector(cid: str, quien: Identidad = Depends(yo)):
        c = conector_de(cid, quien)
        return {**c.publico(), "configuracion_actual": conectores.configuracion(cid, quien.tenant),
                "ejecuciones": conectores.ejecuciones(cid, quien.tenant)}

    @app.put("/conectores/{cid}/configuracion")
    def configurar(cid: str, valores: Dict[str, Any] = Body(...), quien: Identidad = Depends(yo)):
        conector_de(cid, quien)
        try:
            return {"valores": conectores.configurar(cid, quien.tenant, quien.usuario, valores)}
        except ConfiguracionInvalida as e:
            raise HTTPException(422, str(e))

    @app.post("/conectores/{cid}/ejecuciones", status_code=202)
    def ejecutar_conector(cid: str, quien: Identidad = Depends(yo)):
        conector_de(cid, quien)
        try:
            return conectores.lanzar(cid, quien.tenant, quien.usuario)
        except ConfiguracionInvalida as e:
            raise HTTPException(409, str(e))

    @app.get("/ejecuciones/{eid}")
    def ver_ejecucion(eid: str, quien: Identidad = Depends(yo)):
        e = conectores.ejecucion(eid, quien.tenant) if conectores else None
        if not e:
            raise HTTPException(404, "no existe esa ejecución en tu institución")
        return e

    @app.post("/ejecuciones/{eid}/parar")
    def parar(eid: str, quien: Identidad = Depends(yo)):
        if not (conectores and conectores.ejecucion(eid, quien.tenant)):
            raise HTTPException(404, "no existe esa ejecución en tu institución")
        conectores.parar(eid)
        return {"ok": True}

    @app.get("/registros/{tipo}")
    def registros(tipo: str, quien: Identidad = Depends(yo), limite: int = 50):
        """Lo que han escrito los conectores en el catastro de mi institución (solo tipos declarados en «escribe»)."""
        if conectores is None or not any(tipo in c.escribe for c in conectores.visibles(list(quien.roles), quien.tenant)):
            raise HTTPException(404, f"ningún conector tuyo escribe {tipo}")
        filas = conectores.registro.listar(quien.tenant, tipo, limite=min(max(limite, 1), 200))
        v = lambda e, k: (e.get(k) or {}).get("value") if isinstance(e.get(k), dict) else e.get(k)  # noqa: E731
        return [{"id": e["id"], **{k: v(e, k) for k in ("titulo", "creadores", "fechas", "tipos", "origen",
                                                         "identificadorOai", "cosechadoEn")}} for e in filas]

    # ---------- secretos de las capacidades ----------
    def secretos_de(sid: str, quien: Identidad):
        if catalogo.secretos is None:
            raise HTTPException(503, "este catálogo no guarda secretos")
        try:
            return catalogo.comprobar(sid, quien.roles, quien.tenant)
        except KeyError:
            raise HTTPException(404, f"no hay ningún servicio {sid}")
        except SinPermiso as e:
            raise HTTPException(403, str(e))

    @app.get("/secretos")
    def ver_secretos(quien: Identidad = Depends(yo)):
        """Qué secretos piden las capacidades que veo y cuáles están puestos. Nunca devuelve valores."""
        if catalogo.secretos is None:
            return []
        return [{"servicio": m.id, "nombre": m.nombre, "secretos": catalogo.secretos.estado(m, quien.tenant)}
                for m in catalogo.visibles(quien.roles, quien.tenant) if m.secretos]

    def ambito_y_dueno(m, nombre: str, ambito: str, quien: Identidad) -> str:
        d = next((x for x in m.secretos if x["nombre"] == nombre), None)
        if not d:
            raise HTTPException(404, f"{m.id} no declara ningún secreto {nombre}")
        if ambito not in ("institucion", "plataforma") or d["ambito"] not in (ambito, "ambos"):
            raise HTTPException(422, f"{nombre} es de ámbito {d['ambito']}")
        if ambito == "plataforma":
            if not quien.tiene("admin-paas"):
                raise HTTPException(403, "los secretos de la plataforma los pone el equipo del PaaS (admin-paas)")
            return PLATAFORMA
        if not quien.tiene("admin-institucion"):
            raise HTTPException(403, "hace falta el rol admin-institucion")
        return quien.tenant

    @app.put("/secretos/{sid}/{nombre}")
    def poner_secreto(sid: str, nombre: str, peticion: Dict[str, Any] = Body(...), quien: Identidad = Depends(yo)):
        m = secretos_de(sid, quien)
        dueno = ambito_y_dueno(m, nombre, str(peticion.get("ambito", "institucion")), quien)
        valor = str(peticion.get("valor") or "")
        if not valor.strip() or len(valor) > 4096:
            raise HTTPException(422, "el valor no puede estar vacío (ni pasar de 4096 caracteres)")
        catalogo.secretos.poner(m.id, dueno, nombre, valor.strip(), quien.usuario)
        log.info("%s pone el secreto %s de %s (%s)", quien.usuario, nombre, m.id, dueno or "plataforma")
        return {"servicio": m.id, "secretos": catalogo.secretos.estado(m, quien.tenant)}

    @app.delete("/secretos/{sid}/{nombre}")
    def quitar_secreto(sid: str, nombre: str, ambito: str = "institucion", quien: Identidad = Depends(yo)):
        m = secretos_de(sid, quien)
        catalogo.secretos.quitar(m.id, ambito_y_dueno(m, nombre, ambito, quien), nombre)
        return {"servicio": m.id, "secretos": catalogo.secretos.estado(m, quien.tenant)}

    @app.exception_handler(CuotaAgotada)
    async def cuota(_req, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=429)

    return app


def _crear() -> FastAPI:
    from sdk.registro import Registro
    from services.catalogo.actividades import Actividades
    jwks, emisor = os.environ.get("KEYCLOAK_JWKS"), os.environ.get("KEYCLOAK_ISSUER")
    from services.catalogo.secretos import Secretos
    catalogo = Catalogo(descubrir(), secretos=Secretos(os.environ.get("SECRETOS_DB")))
    flujos = FlujosTemporal(os.environ.get("TEMPORAL", "temporal:7233"))
    publicador = None
    if os.environ.get("KAFKA_BOOTSTRAP"):
        from sdk.eventos import Publicador
        publicador = Publicador(os.environ["KAFKA_BOOTSTRAP"], client_id="catalogo")
    registro = Registro(os.environ.get("SCORPIO_URL", "http://scorpio:9090"))
    if os.environ.get("SERVICIO") == "catalogo":
        flujos.arrancar_worker(Actividades(catalogo, registro, publicador))
    from services.catalogo.conectores import Conectores, descubrir as descubrir_conectores
    conectores = Conectores(descubrir_conectores(), registro, os.environ.get("CONECTORES_DB"), publicador=publicador)
    log.info("catálogo con %d servicios (%s) y %d conectores (%s)", len(catalogo.servicios), ", ".join(catalogo.servicios),
             len(conectores.conectores), ", ".join(conectores.conectores))
    return crear_app(verificador=Verificador(jwks, emisor) if jwks and emisor else None, catalogo=catalogo,
                     flujos=flujos, indice=Indice(os.environ.get("CATALOGO_DB")), conectores=conectores)


app = _crear()
from sdk.trazas import configurar  # noqa: E402
configurar("catalogo", app)
