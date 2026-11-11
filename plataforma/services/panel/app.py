"""Consola del PaaS · el núcleo de la plataforma y, aparte, cada producto con sus propias vistas.

Núcleo (este servicio):
    GET  /panel                       estado de la plataforma: piezas, contrato, productos, buzones
    GET  /panel/cartas                cartas del bus de mi institución
    GET  /panel/productos                 catálogo de productos y cómo conectar uno
Capacidades:
    GET  /panel/servicios             catálogo de servicios: probarlos y usarlos por API
    GET  /panel/recetas               recetas: plantillas · /nueva componer y lanzar · /ejecuciones seguir y firmar

Conectores:
    GET  /panel/conectores            configurar y ejecutar los conectores de mi institución

Mi institución (autoservicio, services/instituciones):
    GET/POST /panel/alta              dar de alta una institución sin pasar por el equipo del PaaS (sin sesión)
    GET  /panel/institucion           personas, productos activados, credenciales de API y secretos
    /panel/api/instituciones/...      la consola habla con el servicio de instituciones en nombre de quien está
    POST /panel/entrar · /panel/salir sesión con un usuario de Keycloak (cookie con su token)
    GET  /panel/api/nucleo/estado     ·  /panel/api/nucleo/cartas  ·  /panel/api/productos

Productos (``productos/<id>/``, descubiertos al arrancar):
    /panel/productos/<id>/...             sus vistas y su API, las que monte cada producto
"""
import logging
import os
import time
import urllib.error
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from sdk.identidad import NoAutorizado, pedir_token
from services.panel import pagina as P
from services.panel import conectores_vista as CV
from services.panel import institucion_vista as IV
from services.panel import servicios_vista as SV
from services.panel.productos import Producto, descubrir
from services.panel.datos import Bus, resumen_bus, sondear
from services.panel.nucleo import COOKIE, Nucleo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("panel")
__all__ = ["COOKIE", "crear_app"]


def crear_app(*, registro, verificador, expedientes, keycloak_interno: str, procedencia: str, api_publico: str,
              enlaces: Dict[str, str], productos: Optional[List[Producto]] = None, bus: Optional[Bus] = None,
              sondas=None, servicios: Optional[Dict[str, str]] = None) -> FastAPI:
    app = FastAPI(title="Consola del PaaS", version="0.2.0", docs_url=None, redoc_url=None)
    productos = descubrir() if productos is None else productos
    por_id = {c.id: c for c in productos}

    # ---------- productos activados por cada institución (servicio de instituciones, con caché corta) ----------
    cache_activos: Dict[str, Any] = {}

    def activos_de(token: str, tenant: str) -> Optional[List[str]]:
        """None = no se sabe (servicio caído): se muestra todo, como antes del autoservicio.
        Activar no es una barrera de seguridad (los datos ya están aislados por institución): es la oferta."""
        hit = cache_activos.get(tenant)
        if hit and time.monotonic() - hit[0] < 30:
            return hit[1]
        try:
            r = httpx.get(f"{nucleo.servicio('instituciones')}/activaciones", timeout=5,
                          headers={"Authorization": f"Bearer {token}"})
            act = r.json()["activos"] if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError, KeyError):
            act = None
        if act is not None:
            cache_activos[tenant] = (time.monotonic(), act)
        return act

    def activos_req(req: Request, quien) -> Optional[List[str]]:
        return activos_de(nucleo.token(req), quien.tenant)

    def pintar(req: Request, *, producto: str, vista: str, cuerpo: str, script: str, estilo: str, datos: Dict[str, Any]):
        quien = nucleo.yo(req)
        c = por_id[producto]
        cfg = {"usuario": quien.usuario, "tenant": quien.tenant, "roles": list(quien.roles), "enlaces": enlaces,
               "producto": c.id, "base": c.base, **datos}
        return P.documento(f"{c.nombre} · {next((v.nombre for v in c.vistas if v.id == vista), '')}",
                           P.barra(productos, f"producto:{c.id}", quien, enlaces, activos_req(req, quien)),
                           P.cabecera_producto(c, vista),
                           cuerpo, cfg, script, estilo, c.color)

    nucleo = Nucleo(registro=registro, verificador=verificador, expedientes=expedientes, procedencia=procedencia,
                    api_publico=api_publico, enlaces=enlaces, servicios=servicios, pintar=pintar)
    app.state.nucleo, app.state.productos = nucleo, productos

    def cfg_de(quien) -> Dict[str, Any]:
        return {"usuario": quien.usuario, "tenant": quien.tenant, "roles": list(quien.roles), "enlaces": enlaces,
                "api": api_publico}

    def buzones_por_producto() -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for c in productos:
            if c.estado == "conectado":
                for b in c.buzones:
                    out.setdefault(b, []).append(c.nombre)
        return out

    def vista_nucleo(req: Request, activo: str, titulo: str, cabecera: str, cuerpo: str, script: str = "",
                     estilo: str = ""):
        try:
            quien = nucleo.yo(req)
        except HTTPException:
            return HTMLResponse(P.entrar_html())
        return HTMLResponse(P.documento(titulo, P.barra(productos, activo, quien, enlaces, activos_req(req, quien)),
                                        cabecera, cuerpo, cfg_de(quien), script, estilo))

    # ---------- sesión ----------
    @app.post("/panel/entrar")
    def entrar(usuario: str = Form(...), clave: str = Form(...)):
        try:
            token = pedir_token(keycloak_interno, usuario, clave)
            verificador.verificar(token)
        except (urllib.error.HTTPError, NoAutorizado):
            return HTMLResponse(P.entrar_html("Usuario o contraseña incorrectos."), status_code=401)
        except OSError:
            return HTMLResponse(P.entrar_html("No se puede contactar con Keycloak. Prueba en un momento."), status_code=503)
        r = RedirectResponse("/panel", status_code=303)
        r.set_cookie(COOKIE, token, httponly=True, samesite="lax", path="/panel", max_age=900)
        return r

    @app.get("/panel/api/autorizar")
    def autorizar(req: Request):
        """La puerta (forward-auth) pregunta aquí antes de dejar pasar a una consola técnica (/panel/jaeger…).
        Vale la sesión de la consola (cookie) o un token de Keycloak. Sin ninguno, al navegador se le manda a entrar."""
        token = req.cookies.get(COOKIE) or req.headers.get("authorization", "")[7:].strip()
        try:
            quien = verificador.verificar(token) if token else None
        except NoAutorizado:
            quien = None
        if quien is None:
            return RedirectResponse("/panel", status_code=302)
        return JSONResponse({"ok": True}, headers={"X-Usuario": quien.usuario, "X-Tenant": quien.tenant})

    @app.get("/panel/nucleo/{clave}", response_class=HTMLResponse)
    def consola_incrustada(clave: str, req: Request):
        if clave not in P.INCRUSTADAS:
            raise HTTPException(404, "no hay ninguna consola con ese nombre")
        pieza, nombre, ruta = P.INCRUSTADAS[clave]
        derecha = f'<a class="btn sec" href="{P.e(ruta)}" target="_blank" rel="noopener">Abrir en pestaña nueva</a>'
        cab = P.cabecera_nucleo(pieza, nombre, derecha=derecha)
        return vista_nucleo(req, f"nucleo:{clave}", nombre, cab, P.cuerpo_marco(clave, ruta, nombre), "", P.MARCO_ESTILO)

    @app.post("/panel/salir")
    def salir():
        r = RedirectResponse("/panel", status_code=303)
        r.delete_cookie(COOKIE, path="/panel")
        return r

    # ---------- vistas del núcleo ----------
    @app.get("/panel", response_class=HTMLResponse)
    def estado(req: Request):
        cab = P.cabecera_nucleo("Estado", "Estado de la plataforma",
                                "Lo que comparten todos los productos: identidad, puerta, correos, catastro, procesos, notario y trazas.")
        return vista_nucleo(req, "nucleo:estado", "Estado de la plataforma", cab, P.ESTADO_CUERPO, P.ESTADO_SCRIPT)

    @app.get("/panel/cartas", response_class=HTMLResponse)
    def cartas(req: Request):
        derecha = f'<a class="btn sec" href="{P.e(enlaces["kafka"])}" target="_blank" rel="noopener">Abrir en Kafka UI</a>' \
            if enlaces.get("kafka") else ""
        cab = P.cabecera_nucleo("Correos · Kafka", "Cartas del bus",
                                "Todos los productos publican y leen aquí con el mismo contrato CloudEvents.", derecha)
        return vista_nucleo(req, "nucleo:cartas", "Cartas del bus", cab, P.CARTAS_CUERPO, P.CARTAS_SCRIPT)

    @app.get("/panel/productos", response_class=HTMLResponse)
    def catalogo(req: Request):
        cab = P.cabecera_nucleo("Catálogo", "Catálogo de productos", capa="Productos", sub=
                                "Cada producto es una carpeta en productos/ con su manifiesto y sus vistas. El núcleo no cambia.")
        try:
            quien = nucleo.yo(req)
        except HTTPException:
            return HTMLResponse(P.entrar_html())
        return vista_nucleo(req, "productos", "Productos", cab, P.catalogo_cuerpo(productos, activos_req(req, quien)))

    # ---------- mi institución ----------
    def a_instituciones(metodo: str, ruta: str, *, token: str = "", cuerpo: Any = None, params=None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx.request(metodo, f"{nucleo.servicio('instituciones')}/{ruta}", json=cuerpo, params=params,
                             headers=headers, timeout=30)

    @app.get("/panel/alta", response_class=HTMLResponse)
    def alta_form():
        try:
            cerrado = a_instituciones("GET", "salud").json().get("registro") != "abierto"
        except (httpx.HTTPError, ValueError):
            cerrado = False
        return HTMLResponse(IV.alta_html(cerrado=cerrado))

    @app.post("/panel/alta")
    def alta(institucion: str = Form(...), nombre: str = Form(...), usuario: str = Form(...), clave: str = Form(...),
             email: str = Form(...), persona: str = Form("")):
        datos = {"institucion": institucion.strip().lower(), "nombre": nombre.strip(), "usuario": usuario.strip().lower(),
                 "clave": clave, "email": email.strip(), "persona": persona.strip()}
        try:
            r = a_instituciones("POST", "registro", cuerpo=datos)
        except httpx.HTTPError:
            return HTMLResponse(IV.alta_html("El servicio de instituciones no responde. Prueba en un momento.", datos), 503)
        if r.status_code == 403:
            return HTMLResponse(IV.alta_html(cerrado=True), 403)
        if r.status_code != 201:
            try:
                motivo = r.json().get("detail") or r.text
            except ValueError:
                motivo = r.text
            return HTMLResponse(IV.alta_html(str(motivo), datos), r.status_code if r.status_code < 500 else 502)
        log.info("alta de la institución %s por %s", datos["institucion"], datos["usuario"])
        try:  # entra directamente con su nueva cuenta
            token = pedir_token(keycloak_interno, datos["usuario"], clave)
        except (urllib.error.HTTPError, OSError):
            return HTMLResponse(P.entrar_html("Institución creada. Entra con tu usuario y contraseña."))
        resp = RedirectResponse("/panel/institucion", status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", path="/panel", max_age=900)
        return resp

    @app.get("/panel/institucion", response_class=HTMLResponse)
    def institucion(req: Request):
        try:
            quien = nucleo.yo(req)
        except HTTPException:
            return HTMLResponse(P.entrar_html())
        sub = ("Activa productos, invita a tu equipo, crea credenciales de API y pon los secretos de las capacidades."
               if quien.tiene("admin-institucion") else "Lo que tu institución tiene activado. Lo gestiona quien la administra.")
        cab = P.cabecera_nucleo(quien.tenant, "Mi institución", sub, capa="Mi institución")
        return vista_nucleo(req, "institucion", "Mi institución", cab, IV.CUERPO_INST, IV.SCRIPT_INST, IV.ESTILO_INST)

    @app.get("/panel/instituciones", response_class=HTMLResponse)
    def instituciones(req: Request):
        try:
            quien = nucleo.yo(req)
        except HTTPException:
            return HTMLResponse(P.entrar_html())
        cab = P.cabecera_nucleo("Equipo del PaaS", "Instituciones",
                                "Da de alta instituciones y mira qué tiene activado cada una.", capa="Mi institución")
        if not quien.tiene("admin-paas"):
            cuerpo = ('<section class="tarjeta"><p style="margin:0">Esta página es del equipo del PaaS (rol admin-paas). '
                      'Para dar de alta otra institución, sal y usa «Dadla de alta» en la entrada.</p></section>')
            r = vista_nucleo(req, "instituciones", "Instituciones", cab, cuerpo)
            r.status_code = 403
            return r
        return vista_nucleo(req, "instituciones", "Instituciones", cab, IV.CUERPO_TODAS, IV.SCRIPT_TODAS, IV.ESTILO_INST)

    def al_servicio_inst(req: Request, metodo: str, ruta: str, cuerpo: Any = None):
        quien = nucleo.yo(req)
        try:
            r = a_instituciones(metodo, ruta, token=nucleo.token(req), cuerpo=cuerpo, params=dict(req.query_params))
        except httpx.HTTPError as ex:
            raise HTTPException(503, f"El servicio de instituciones no responde: {ex}")
        if metodo != "GET" and ruta.startswith("activaciones"):
            cache_activos.pop(quien.tenant, None)
        try:
            datos = r.json()
        except ValueError:
            datos = {"detail": r.text}
        return JSONResponse(datos, status_code=r.status_code)

    @app.get("/panel/api/instituciones/{ruta:path}")
    def inst_get(ruta: str, req: Request):
        return al_servicio_inst(req, "GET", ruta)

    @app.post("/panel/api/instituciones/{ruta:path}")
    def inst_post(ruta: str, req: Request, cuerpo: Dict[str, Any] = Body(...)):
        return al_servicio_inst(req, "POST", ruta, cuerpo)

    @app.put("/panel/api/instituciones/{ruta:path}")
    def inst_put(ruta: str, req: Request, cuerpo: Dict[str, Any] = Body(...)):
        return al_servicio_inst(req, "PUT", ruta, cuerpo)

    @app.delete("/panel/api/instituciones/{ruta:path}")
    def inst_delete(ruta: str, req: Request):
        return al_servicio_inst(req, "DELETE", ruta)

    @app.get("/panel/servicios", response_class=HTMLResponse)
    def servicios(req: Request):
        cab = P.cabecera_nucleo("Catálogo de servicios", "Servicios",
                                "Servicios reutilizables que cualquier institución usa sueltos, por API o dentro de un flujo.",
                                capa="Capacidades")
        return vista_nucleo(req, "capacidades:servicios", "Servicios", cab, SV.SERVICIOS_CUERPO,
                            SV.SCRIPT_DOC + SV.SERVICIOS_SCRIPT, SV.ESTILO)

    def recetas_vista(req: Request, activo: str, titulo: str, sub: str, cuerpo: str, script: str):
        cab = P.cabecera_nucleo("Recetas", titulo, sub, capa="Capacidades")
        return vista_nucleo(req, f"capacidades:{activo}", f"Recetas · {titulo}", cab, cuerpo,
                            SV.SCRIPT_DOC + SV.RECETAS_COMUN + script, SV.ESTILO)

    @app.get("/panel/recetas", response_class=HTMLResponse)
    def recetas(req: Request):
        return recetas_vista(req, "recetas", "Plantillas",
                             "Recetas listas para usar: encadenan capacidades y firmas de personas. Úsalas tal cual o adáptalas.",
                             SV.RECETAS_CUERPO, SV.RECETAS_SCRIPT)

    @app.get("/panel/recetas/nueva", response_class=HTMLResponse)
    def receta_nueva(req: Request):
        return recetas_vista(req, "nueva-receta", "Nueva receta",
                             "Parte de una plantilla, cámbiala y lánzala. La plataforma comprueba que cada paso encaja con el siguiente.",
                             SV.NUEVA_CUERPO, SV.NUEVA_SCRIPT)

    @app.get("/panel/recetas/ejecuciones", response_class=HTMLResponse)
    def receta_ejecuciones(req: Request):
        return recetas_vista(req, "ejecuciones", "Ejecuciones",
                             "Las recetas lanzadas en tu institución, paso a paso, y las firmas que esperan a alguien.",
                             SV.EJECUCIONES_CUERPO, SV.EJECUCIONES_SCRIPT)

    @app.get("/panel/flujos")
    def flujos_antes():
        return RedirectResponse("/panel/recetas/ejecuciones", status_code=301)

    @app.get("/panel/conectores", response_class=HTMLResponse)
    def conectores(req: Request):
        cab = P.cabecera_nucleo("Sistemas de la institución", "Conectores",
                                "Traen a la plataforma lo que tu institución ya tiene en otros sistemas, o lo llevan allí.",
                                capa="Conectores")
        return vista_nucleo(req, "conectores", "Conectores", cab, CV.CUERPO, CV.SCRIPT, CV.ESTILO)

    # ---------- catálogo: la consola habla con él en nombre de quien está dentro ----------
    def al_catalogo(req: Request, metodo: str, ruta: str, cuerpo: Any = None):
        nucleo.yo(req)
        try:
            r = httpx.request(metodo, f"{nucleo.servicio('catalogo')}/{ruta}", json=cuerpo, timeout=30,
                              params=dict(req.query_params), headers={"Authorization": f"Bearer {nucleo.token(req)}"})
        except httpx.HTTPError as e:
            raise HTTPException(503, f"El catálogo no responde: {e}")
        try:
            datos = r.json()
        except ValueError:
            datos = {"detail": r.text}
        return JSONResponse(datos, status_code=r.status_code)

    @app.get("/panel/api/catalogo/{ruta:path}")
    def catalogo_get(ruta: str, req: Request):
        return al_catalogo(req, "GET", ruta)

    @app.put("/panel/api/catalogo/{ruta:path}")
    def catalogo_put(ruta: str, req: Request, cuerpo: Dict[str, Any] = Body(...)):
        return al_catalogo(req, "PUT", ruta, cuerpo)

    @app.post("/panel/api/catalogo/{ruta:path}")
    def catalogo_post(ruta: str, req: Request, cuerpo: Dict[str, Any] = Body(...)):
        return al_catalogo(req, "POST", ruta, cuerpo)

    @app.delete("/panel/api/catalogo/{ruta:path}")
    def catalogo_delete(ruta: str, req: Request):
        return al_catalogo(req, "DELETE", ruta)

    def receta_de(texto: str) -> Any:
        import yaml
        try:
            return yaml.safe_load(texto or "")
        except yaml.YAMLError as e:
            raise HTTPException(422, {"errores": [f"el YAML no se puede leer: {e}"]})

    @app.post("/panel/api/flujos/validar")
    def flujo_validar(req: Request, cuerpo: Dict[str, Any] = Body(...)):
        return al_catalogo(req, "POST", "flujos/validar", {"receta": receta_de(cuerpo.get("yaml"))})

    @app.post("/panel/api/flujos/lanzar")
    def flujo_lanzar(req: Request, cuerpo: Dict[str, Any] = Body(...)):
        return al_catalogo(req, "POST", "flujos", {"receta": receta_de(cuerpo.get("yaml")), "entrada": cuerpo.get("entrada")})

    # ---------- API del núcleo ----------
    @app.get("/panel/api/nucleo/estado")
    def api_estado(req: Request):
        nucleo.yo(req)
        buz, error = resumen_bus(bus)
        capas = {"productos": sum(1 for c in productos if c.estado == "conectado"), "capacidades": None, "conectores": None}
        for clave, ruta in (("capacidades", "servicios"), ("conectores", "conectores")):
            try:
                r = httpx.get(f"{nucleo.servicio('catalogo')}/{ruta}", timeout=5,
                              headers={"Authorization": f"Bearer {nucleo.token(req)}"})
                if r.status_code == 200:
                    capas[clave] = len(r.json())
            except (httpx.HTTPError, ValueError):
                pass
        return {"capas": capas, "sondas": sondear() if sondas is None else sondas(), "buzones": buz, "errorBus": error,
                "buzonesPorProducto": buzones_por_producto(), "productos": [c.ficha() for c in productos]}

    @app.get("/panel/api/nucleo/cartas")
    def api_cartas(req: Request):
        quien = nucleo.yo(req)
        buz, error = resumen_bus(bus)
        ultimas: List[Dict[str, Any]] = []
        if not error and bus is not None:
            try:
                ultimas = bus.ultimas(quien.tenant)[:40]
            except Exception as ex:  # noqa: BLE001
                error = f"Kafka no responde: {ex}"
        return {"buzones": buz, "ultimas": ultimas, "error": error, "buzonesPorProducto": buzones_por_producto()}

    @app.get("/panel/api/productos")
    def api_productos(req: Request):
        nucleo.yo(req)
        return [c.ficha() for c in productos]

    # ---------- montar cada producto ----------
    for c in productos:
        if c.estado != "conectado" or c.montar is None:
            continue
        try:
            app.include_router(c.montar(nucleo, c), prefix=c.base)
            log.info("Producto conectado: %s en %s", c.id, c.base)
        except Exception as ex:  # un producto roto no tumba la consola
            log.error("No se pudo montar el producto %s: %s", c.id, ex)
            c.estado = f"error al montar: {ex}"

    @app.middleware("http")
    async def solo_productos_activados(req: Request, siguiente):
        partes = req.url.path.split("/")
        if len(partes) > 3 and partes[1:3] == ["panel", "productos"] and partes[3] in por_id and req.cookies.get(COOKIE):
            try:
                quien = verificador.verificar(req.cookies[COOKIE])
            except NoAutorizado:
                quien = None
            if quien is not None:
                act = await run_in_threadpool(activos_de, req.cookies[COOKIE], quien.tenant)
                if act is not None and partes[3] not in act:
                    c = por_id[partes[3]]
                    msg = f"Tu institución no tiene activado el producto {c.nombre}."
                    if "/api/" in req.url.path:
                        return JSONResponse({"detail": msg}, status_code=403)
                    cab = P.cabecera_nucleo("Productos", c.nombre, capa="Productos")
                    cuerpo = (f'<section class="tarjeta"><p style="margin:0 0 12px">{P.e(msg)}</p>'
                              f'<a class="btn" href="/panel/institucion">Ir a Mi institución</a></section>')
                    return HTMLResponse(P.documento(c.nombre, P.barra(productos, "productos", quien, enlaces, act), cab,
                                                    cuerpo, cfg_de(quien)), status_code=403)
        return await siguiente(req)

    @app.exception_handler(401)
    async def sin_sesion(req: Request, exc):
        # una vista HTML sin sesión lleva a entrar; la API responde 401
        if "/api/" not in req.url.path and req.method == "GET":
            return HTMLResponse(P.entrar_html(), status_code=200)
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": getattr(exc, "detail", "inicia sesión")}, status_code=401)

    return app


def _crear() -> FastAPI:
    from services.gestoria.app import ExpedientesTemporal
    from sdk.identidad import Verificador
    from sdk.registro import Registro
    jwks, emisor = os.environ.get("KEYCLOAK_JWKS"), os.environ.get("KEYCLOAK_ISSUER")
    publico = {"scorpio": "SCORPIO_PUBLICO", "keycloak": "KEYCLOAK_PUBLICO"}
    # las consolas incrustadas viven en la misma dirección que la consola (detrás de la puerta)
    incrustadas = {k: f"/panel/{k}" for k in P.INCRUSTADAS}
    return crear_app(
        registro=Registro(os.environ.get("SCORPIO_URL", "http://scorpio:9090")),
        verificador=Verificador(jwks, emisor) if jwks and emisor else None,
        expedientes=ExpedientesTemporal(os.environ.get("TEMPORAL", "temporal:7233")),
        keycloak_interno=os.environ.get("KEYCLOAK_INTERNO", "http://keycloak:8080"),
        procedencia=os.environ.get("PROCEDENCIA_INTERNO", "http://procedencia:8080"),
        api_publico=os.environ.get("API_PUBLICO", "http://localhost:9080").rstrip("/"),
        enlaces={**incrustadas, **{k: u.rstrip("/") for k, var in publico.items() if (u := os.environ.get(var, ""))}},
        bus=Bus(os.environ.get("KAFKA_BOOTSTRAP", "kafka:29092")),
    )


app = _crear()
from sdk.trazas import configurar  # noqa: E402
configurar("panel", app)
