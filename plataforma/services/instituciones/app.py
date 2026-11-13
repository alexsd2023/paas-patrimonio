"""Instituciones · que una institución entre y use la plataforma sin pasar por el equipo del PaaS (núcleo).

Alta (sin sesión; si REGISTRO=abierto):
    POST /registro {institucion, nombre, usuario, clave, email, persona?}   crea el grupo en Keycloak y su primera administradora

Con sesión (token de Keycloak). Todo se hace en la institución del token; nunca en otra:
    GET  /yo                                 mi institución, si la gestiono y qué productos tiene activados
    GET  /activaciones                       productos activados de mi institución (la consola filtra con esto)
    PUT  /activaciones/{producto} {activo}   activar o desactivar un producto            (admin-institucion)
    GET  /usuarios                           personas de mi institución                    (admin-institucion)
    POST /usuarios {usuario, clave, email, nombre?, roles}                                (admin-institucion)
    PUT  /usuarios/{id} {roles?, activo?, clave?}                                          (admin-institucion)
    GET  /credenciales                       credenciales de API de mi institución         (admin-institucion)
    POST /credenciales {nombre, roles}       crea un cliente de Keycloak; el secreto se muestra UNA vez
    DELETE /credenciales/{client_id}
    GET  /instituciones                      todas, con sus productos activados          (admin-paas)
    POST /instituciones {como /registro}     alta desde la consola, aunque el registro esté cerrado (admin-paas)

Las instituciones dadas de alta aquí empiezan sin productos: los activa su administradora. Las que ya
existían antes (grupos creados a mano en Keycloak) se consideran «no gestionadas» y lo tienen todo activado.
"""
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import Body, Depends, FastAPI, Header, HTTPException

from sdk.identidad import Identidad, NoAutorizado, Verificador, token_de
from services.instituciones.keycloak import ErrorKeycloak, KeycloakAdmin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("instituciones")

RAIZ = Path(__file__).resolve().parents[2]
ROLES_ASIGNABLES = ["archivera", "paleografa", "admin-institucion"]
GRUPO_OPERADORES = "paas"
RESERVADAS = {"paas", "admin", "master", "sistema", "plataforma"}
_ID = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
_USUARIO = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def productos_disponibles(carpeta: Path = RAIZ / "productos") -> Dict[str, Dict[str, Any]]:
    """{id: {nombre, permisos: [{id, opcional}]}} de cada productos/*/producto.yaml."""
    out = {}
    for yml in sorted(Path(carpeta).glob("*/producto.yaml")):
        try:
            d = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
            out[str(d.get("id", yml.parent.name))] = {
                "nombre": str(d.get("nombre", yml.parent.name)),
                "permisos": [{"id": str(x["id"]), "opcional": bool(x.get("opcional", False))}
                             for x in (d.get("permisos") or []) if isinstance(x, dict) and x.get("id")]}
        except (OSError, ValueError):
            pass
    return out


def _csv(v: Optional[List[str]]) -> Optional[str]:
    return None if v is None else ",".join(v)


def _lista(v: Optional[str]) -> Optional[List[str]]:
    return None if v is None else [x for x in v.split(",") if x]


class Almacen:
    def __init__(self, ruta: Optional[str] = None):
        self.ruta = ruta or os.path.join(tempfile.gettempdir(), "instituciones.db")
        self._lock = threading.Lock()
        with self._con() as c:
            c.execute("create table if not exists instituciones (id text primary key, nombre text, creada real, por text)")
            c.execute("create table if not exists activaciones (tenant text, producto text, por text, cuando real,"
                      " primary key (tenant, producto))")
            c.execute("create table if not exists credenciales (client_id text primary key, tenant text, nombre text,"
                      " roles text, por text, cuando real)")
            # Marketplace: permisos concedidos y roles que pueden usar cada producto (None = todos)
            cols = {f[1] for f in c.execute("pragma table_info(activaciones)")}
            for col in ("permisos", "roles"):
                if col not in cols:
                    c.execute(f"alter table activaciones add column {col} text")

    def _con(self):
        return sqlite3.connect(self.ruta)

    def gestionada(self, tenant: str) -> Optional[Dict[str, Any]]:
        with self._con() as c:
            f = c.execute("select id, nombre, creada, por from instituciones where id=?", (tenant,)).fetchone()
        return {"id": f[0], "nombre": f[1], "creada": f[2], "por": f[3]} if f else None

    def alta(self, tenant: str, nombre: str, por: str):
        with self._lock, self._con() as c:
            c.execute("insert into instituciones values (?,?,?,?)", (tenant, nombre, time.time(), por))

    def todas(self) -> List[Dict[str, Any]]:
        with self._con() as c:
            return [{"id": f[0], "nombre": f[1], "creada": f[2], "por": f[3]}
                    for f in c.execute("select id, nombre, creada, por from instituciones order by creada")]

    def activos(self, tenant: str) -> List[str]:
        with self._con() as c:
            return [f[0] for f in c.execute("select producto from activaciones where tenant=? order by producto", (tenant,))]

    def detalle(self, tenant: str) -> Dict[str, Dict[str, Any]]:
        with self._con() as c:
            return {f[0]: {"por": f[1], "cuando": f[2], "permisos": _lista(f[3]), "roles": _lista(f[4])}
                    for f in c.execute("select producto, por, cuando, permisos, roles from activaciones where tenant=?",
                                       (tenant,))}

    def activar(self, tenant: str, producto: str, activo: bool, por: str,
                permisos: Optional[List[str]] = None, roles: Optional[List[str]] = None):
        with self._lock, self._con() as c:
            if activo:
                c.execute("insert or replace into activaciones (tenant, producto, por, cuando, permisos, roles)"
                          " values (?,?,?,?,?,?)", (tenant, producto, por, time.time(), _csv(permisos), _csv(roles)))
            else:
                c.execute("delete from activaciones where tenant=? and producto=?", (tenant, producto))

    def credenciales(self, tenant: str) -> List[Dict[str, Any]]:
        with self._con() as c:
            return [{"client_id": f[0], "nombre": f[1], "roles": f[2].split(",") if f[2] else [], "por": f[3], "cuando": f[4]}
                    for f in c.execute("select client_id, nombre, roles, por, cuando from credenciales where tenant=?"
                                       " order by cuando desc", (tenant,))]

    def apuntar_credencial(self, client_id, tenant, nombre, roles, por):
        with self._lock, self._con() as c:
            c.execute("insert into credenciales values (?,?,?,?,?,?)", (client_id, tenant, nombre, ",".join(roles), por, time.time()))

    def credencial(self, client_id: str) -> Optional[str]:
        with self._con() as c:
            f = c.execute("select tenant from credenciales where client_id=?", (client_id,)).fetchone()
        return f[0] if f else None

    def borrar_credencial(self, client_id: str):
        with self._lock, self._con() as c:
            c.execute("delete from credenciales where client_id=?", (client_id,))


def _validar_clave(clave: str) -> None:
    if len(clave or "") < 10:
        raise HTTPException(422, "la contraseña necesita al menos 10 caracteres")


def _roles(roles: List[str]) -> List[str]:
    raros = sorted(set(roles or []) - set(ROLES_ASIGNABLES))
    if raros:
        raise HTTPException(422, f"roles no asignables: {raros} (posibles: {ROLES_ASIGNABLES})")
    return sorted(set(roles or []))


def crear_app(*, verificador, kc: KeycloakAdmin, almacen: Almacen, registro_abierto: bool = True,
              productos: Optional[Dict[str, str]] = None, preparar_catastro=None, catastro_disponible=None) -> FastAPI:
    """preparar_catastro(tenant): conecta el catastro de una institución al bus (sus suscripciones de Scorpio),
    para que sus productos reaccionen a lo que inscriba. catastro_disponible(): si Scorpio ya responde."""
    app = FastAPI(title="Instituciones", version="0.1.0")
    productos = productos_disponibles() if productos is None else productos
    # admite {id: "Nombre"} (pruebas) además de {id: {nombre, permisos}}
    productos = {k: (v if isinstance(v, dict) else {"nombre": v, "permisos": []}) for k, v in productos.items()}

    def todos_los_permisos(pid: str) -> List[str]:
        return [x["id"] for x in productos[pid]["permisos"]]
    alta_lock = threading.Lock()

    def yo(authorization: Optional[str] = Header(None)) -> Identidad:
        try:
            return verificador.verificar(token_de(authorization))
        except NoAutorizado as e:
            raise HTTPException(e.codigo, e.motivo)

    def admin(quien: Identidad = Depends(yo)) -> Identidad:
        if not quien.tiene("admin-institucion"):
            raise HTTPException(403, "hace falta el rol admin-institucion")
        return quien

    def grupo_de(tenant: str) -> Dict[str, Any]:
        g = kc.grupo(tenant)
        if not g:
            raise HTTPException(404, f"no existe la institución {tenant} en Keycloak")
        return g

    def mio(uid: str, quien: Identidad) -> Dict[str, Any]:
        """El usuario uid, solo si es de la institución de quien pregunta."""
        try:
            if quien.tenant not in kc.grupos_de(uid):
                raise HTTPException(404, "esa persona no es de tu institución")
            return kc.usuario(uid)
        except ErrorKeycloak as e:
            raise HTTPException(404 if e.codigo == 404 else 502, str(e))

    @app.get("/salud")
    def salud():
        return {"ok": True, "registro": "abierto" if registro_abierto else "cerrado", "productos": sorted(productos)}

    # ---------- alta autoservicio ----------
    @app.post("/registro", status_code=201)
    def registro(p: Dict[str, Any] = Body(...)):
        if not registro_abierto:
            raise HTTPException(403, "el alta de instituciones está cerrada en esta plataforma")
        return dar_de_alta(p, None)

    def dar_de_alta(p: Dict[str, Any], por: Optional[str]) -> Dict[str, Any]:
        """Crea la institución y su primera administradora. por: quien la da de alta (None = ella misma)."""
        tenant, nombre = str(p.get("institucion", "")).strip().lower(), str(p.get("nombre", "")).strip()
        usuario, clave, email = str(p.get("usuario", "")).strip().lower(), str(p.get("clave", "")), p.get("email") or None
        if not _ID.match(tenant) or tenant in RESERVADAS:
            raise HTTPException(422, "identificador: 3–40 minúsculas, cifras y guiones, empezando por letra")
        if not nombre:
            raise HTTPException(422, "falta el nombre de la institución")
        if not _USUARIO.match(usuario):
            raise HTTPException(422, "usuario: 3–40 minúsculas, cifras, puntos, guiones o guiones bajos")
        if not email or not _EMAIL.match(str(email)):
            raise HTTPException(422, "hace falta un email válido")
        _validar_clave(clave)
        with alta_lock:
            if kc.grupo(tenant):
                raise HTTPException(409, f"ya existe una institución {tenant}")
            if kc.usuario_por_nombre(usuario):
                raise HTTPException(409, f"ya existe el usuario {usuario}")
            gid = kc.crear_grupo(tenant, {"nombre": [nombre]})
            uid = None
            try:
                uid = kc.crear_usuario(usuario, clave, email, str(p.get("persona") or ""))
                kc.poner_en_grupo(uid, gid)
                kc.dar_roles(uid, ["admin-institucion"])
                almacen.alta(tenant, nombre, por or usuario)
            except Exception:
                # sin alta a medias: si algo falla, no queda ni el grupo ni la persona
                for deshacer, x in ((kc.borrar_usuario, uid), (kc.borrar_grupo, gid)):
                    if x:
                        try:
                            deshacer(x)
                        except Exception:  # noqa: BLE001
                            log.exception("no pude deshacer el alta de %s", tenant)
                raise
        log.info("institución %s dada de alta por %s (administra %s)", tenant, por or usuario, usuario)
        return {"institucion": tenant, "nombre": nombre, "usuario": usuario, "roles": ["admin-institucion"],
                "productos": [], "catastro": conectar_catastro(tenant)}

    def conectar_catastro(tenant: str) -> str:
        """Si falla, el alta sigue valiendo: se repara sola al volver a arrancar este servicio,
        o a mano con POST /instituciones/{id}/catastro."""
        if not preparar_catastro:
            return "sin catastro"
        try:
            preparar_catastro(tenant)
            return "conectado"
        except Exception:  # noqa: BLE001
            log.exception("el catastro de %s no quedó conectado al bus", tenant)
            return "pendiente"

    @app.on_event("startup")
    def reparar_catastros():
        """Las instituciones dadas de alta antes de este arreglo (o con Scorpio caído) se conectan al arrancar."""
        if not preparar_catastro:
            return

        def reparar():
            fin = time.time() + 300
            while catastro_disponible and not catastro_disponible():
                if time.time() > fin:
                    log.warning("el catastro no responde: no reparo las suscripciones de las instituciones")
                    return
                time.sleep(5)
            for i in almacen.todas():
                log.info("catastro de %s: %s", i["id"], conectar_catastro(i["id"]))
        threading.Thread(target=reparar, daemon=True, name="reparar-catastros").start()

    # ---------- mi institución ----------
    def activos_de(tenant: str) -> Dict[str, Any]:
        """Productos activados, con los permisos concedidos y quién puede usarlos (roles; None = todos).
        Una institución anterior al autoservicio («no gestionada») lo tiene todo, con todos los permisos."""
        gestion = almacen.gestionada(tenant)
        if gestion:
            det = {k: v for k, v in almacen.detalle(tenant).items() if k in productos}
        else:
            det = {k: {"por": None, "cuando": None, "permisos": None, "roles": None} for k in productos}
        for k, v in det.items():
            if v["permisos"] is None:
                v["permisos"] = todos_los_permisos(k)
        return {"gestionada": gestion is not None, "activos": sorted(det), "detalle": det}

    @app.get("/yo")
    def mi_institucion(quien: Identidad = Depends(yo)):
        g = kc.grupo(quien.tenant) or {}
        nombre = ((g.get("attributes") or {}).get("nombre") or [quien.tenant])[0]
        return {"institucion": quien.tenant, "nombre": nombre, "usuario": quien.usuario,
                "admin": quien.tiene("admin-institucion"), "operador": quien.tiene("admin-paas"),
                "productos": [{"id": k, "nombre": v["nombre"]} for k, v in productos.items()], **activos_de(quien.tenant)}

    @app.get("/activaciones")
    def activaciones(quien: Identidad = Depends(yo)):
        return activos_de(quien.tenant)

    @app.put("/activaciones/{producto}")
    def activar(producto: str, p: Dict[str, Any] = Body(...), quien: Identidad = Depends(admin)):
        """{activo, permisos?, roles?}: los permisos imprescindibles van siempre; sin «permisos», todos.
        «roles»: quién de la institución puede usarlo (sin «roles», todos)."""
        if producto not in productos:
            raise HTTPException(404, f"no hay ningún producto {producto}")
        declarados = productos[producto]["permisos"]
        permisos = None
        if p.get("permisos") is not None:
            pedidos = set(p.get("permisos") or [])
            raros = sorted(pedidos - {x["id"] for x in declarados})
            if raros:
                raise HTTPException(422, f"{producto} no pide esos permisos: {raros}")
            permisos = [x["id"] for x in declarados if x["id"] in pedidos or not x["opcional"]]
        roles = None
        if p.get("roles") is not None:
            roles = sorted(set(p.get("roles") or []))
            raros = sorted(set(roles) - set(ROLES_ASIGNABLES))
            if raros:
                raise HTTPException(422, f"roles no válidos: {raros} (posibles: {ROLES_ASIGNABLES})")
            if not roles and p.get("activo"):
                raise HTTPException(422, "elige al menos quién de tu equipo podrá usarlo")
        if not almacen.gestionada(quien.tenant):
            # una institución anterior al alta autoservicio pasa a gestionada conservando lo que tenía activo
            g = kc.grupo(quien.tenant) or {}
            almacen.alta(quien.tenant, ((g.get("attributes") or {}).get("nombre") or [quien.tenant])[0], quien.usuario)
            for otro in productos:
                almacen.activar(quien.tenant, otro, True, quien.usuario)
        almacen.activar(quien.tenant, producto, bool(p.get("activo")), quien.usuario, permisos, roles)
        return activos_de(quien.tenant)

    # ---------- personas ----------
    def ficha(u: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": u["id"], "usuario": u["username"], "email": u.get("email"), "activo": u.get("enabled", True),
                "nombre": " ".join(dict.fromkeys(x for x in (u.get("firstName"), u.get("lastName")) if x and x != u["username"])),
                "roles": sorted(r for r in kc.roles_de(u["id"]) if r in ROLES_ASIGNABLES + ["admin-paas"])}

    @app.get("/usuarios")
    def usuarios(quien: Identidad = Depends(admin)):
        miembros = kc.miembros(grupo_de(quien.tenant)["id"])
        return [ficha(u) for u in miembros if not u["username"].startswith("service-account-")]

    @app.post("/usuarios", status_code=201)
    def nuevo_usuario(p: Dict[str, Any] = Body(...), quien: Identidad = Depends(admin)):
        usuario, clave, email = str(p.get("usuario", "")).strip().lower(), str(p.get("clave", "")), p.get("email") or None
        if not _USUARIO.match(usuario):
            raise HTTPException(422, "usuario: 3–40 minúsculas, cifras, puntos, guiones o guiones bajos")
        if not email or not _EMAIL.match(str(email)):
            raise HTTPException(422, "hace falta un email válido")
        _validar_clave(clave)
        roles = _roles(p.get("roles") or [])
        if kc.usuario_por_nombre(usuario):
            raise HTTPException(409, f"ya existe el usuario {usuario}")
        uid = kc.crear_usuario(usuario, clave, email, str(p.get("nombre") or ""))
        kc.poner_en_grupo(uid, grupo_de(quien.tenant)["id"])
        kc.dar_roles(uid, roles)
        log.info("%s añade a %s en %s con %s", quien.usuario, usuario, quien.tenant, roles)
        return ficha(kc.usuario(uid))

    @app.put("/usuarios/{uid}")
    def cambiar_usuario(uid: str, p: Dict[str, Any] = Body(...), quien: Identidad = Depends(admin)):
        u = mio(uid, quien)
        propio = u["username"] == quien.usuario
        if "roles" in p:
            nuevos = set(_roles(p["roles"]))
            if propio and "admin-institucion" not in nuevos:
                raise HTTPException(409, "no puedes quitarte a ti misma el rol admin-institucion")
            actuales = set(r for r in kc.roles_de(uid) if r in ROLES_ASIGNABLES)
            kc.dar_roles(uid, sorted(nuevos - actuales))
            kc.quitar_roles(uid, sorted(actuales - nuevos))
        if "activo" in p:
            if propio and not p["activo"]:
                raise HTTPException(409, "no puedes desactivar tu propia cuenta")
            kc.activar(uid, bool(p["activo"]))
        if p.get("clave"):
            _validar_clave(p["clave"])
            kc.poner_clave(uid, p["clave"])
        return ficha(kc.usuario(uid))

    # ---------- credenciales de API ----------
    @app.get("/credenciales")
    def credenciales(quien: Identidad = Depends(admin)):
        return almacen.credenciales(quien.tenant)

    @app.post("/credenciales", status_code=201)
    def nueva_credencial(p: Dict[str, Any] = Body(...), quien: Identidad = Depends(admin)):
        nombre = str(p.get("nombre", "")).strip()
        llano = unicodedata.normalize("NFKD", nombre.lower()).encode("ascii", "ignore").decode()
        corto = re.sub(r"[^a-z0-9]+", "-", llano).strip("-")[:30]
        if not corto:
            raise HTTPException(422, "pon un nombre a la credencial (p. ej. «catálogo web»)")
        roles = _roles(p.get("roles") or [])
        if "admin-institucion" in roles:
            raise HTTPException(422, "una aplicación no puede administrar la institución")
        client_id = f"app-{quien.tenant}-{corto}"
        if kc.cliente_por_id(client_id):
            raise HTTPException(409, f"ya existe la credencial {client_id}")
        cid = kc.crear_cliente_app(client_id, f"{nombre} ({quien.tenant})")
        sa = kc.usuario_de_servicio(cid)
        kc.poner_en_grupo(sa["id"], grupo_de(quien.tenant)["id"])
        kc.dar_roles(sa["id"], roles)
        almacen.apuntar_credencial(client_id, quien.tenant, nombre, roles, quien.usuario)
        return {"client_id": client_id, "secreto": kc.secreto_de(cid), "roles": roles,
                "aviso": "Guarda el secreto ahora: no se vuelve a mostrar."}

    @app.delete("/credenciales/{client_id}")
    def borrar_credencial(client_id: str, quien: Identidad = Depends(admin)):
        if almacen.credencial(client_id) != quien.tenant:
            raise HTTPException(404, "esa credencial no es de tu institución")
        c = kc.cliente_por_id(client_id)
        if c:
            kc.borrar_cliente(c["id"])
        almacen.borrar_credencial(client_id)
        return {"ok": True}

    # ---------- operadores de la plataforma ----------
    @app.post("/instituciones/{tid}/catastro")
    def reconectar_catastro(tid: str, quien: Identidad = Depends(yo)):
        """Vuelve a conectar al bus el catastro de una institución (idempotente)."""
        if not quien.tiene("admin-paas"):
            raise HTTPException(403, "hace falta el rol admin-paas")
        if not kc.grupo(tid):
            raise HTTPException(404, f"no existe la institución {tid}")
        estado = conectar_catastro(tid)
        if estado == "pendiente":
            raise HTTPException(502, f"no se pudo conectar el catastro de {tid}: mira los logs de instituciones y scorpio")
        return {"institucion": tid, "catastro": estado}

    @app.post("/instituciones", status_code=201)
    def alta_por_operador(p: Dict[str, Any] = Body(...), quien: Identidad = Depends(yo)):
        """El equipo del PaaS da de alta una institución desde la consola (también con REGISTRO=cerrado)."""
        if not quien.tiene("admin-paas"):
            raise HTTPException(403, "hace falta el rol admin-paas")
        return dar_de_alta(p, quien.usuario)

    @app.get("/instituciones")
    def instituciones(quien: Identidad = Depends(yo)):
        if not quien.tiene("admin-paas"):
            raise HTTPException(403, "hace falta el rol admin-paas")
        gestionadas = {i["id"]: i for i in almacen.todas()}
        out = []
        for g in kc.grupos():
            if g["name"] == GRUPO_OPERADORES:
                continue
            nombre = ((g.get("attributes") or {}).get("nombre") or [g["name"]])[0]
            i = gestionadas.get(g["name"])
            out.append({"id": g["name"], "nombre": nombre, "gestionada": bool(i), "creada": (i or {}).get("creada"),
                        "por": (i or {}).get("por"), **activos_de(g["name"])})
        return out

    @app.exception_handler(ErrorKeycloak)
    async def keycloak_caido(_req, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=502)

    return app


def _crear() -> FastAPI:
    jwks, emisor = os.environ.get("KEYCLOAK_JWKS"), os.environ.get("KEYCLOAK_ISSUER")
    return crear_app(
        verificador=Verificador(jwks, emisor) if jwks and emisor else None,
        kc=KeycloakAdmin(os.environ.get("KEYCLOAK_INTERNO", "http://keycloak:8080"), os.environ.get("GESTION_SECRET", "")),
        almacen=Almacen(os.environ.get("INSTITUCIONES_DB")),
        registro_abierto=os.environ.get("REGISTRO", "abierto") == "abierto",
        **_catastro(),
    )


def _catastro() -> Dict[str, Any]:
    """Con SCORPIO_URL, cada alta conecta el catastro de la institución al bus (services/suscripciones)."""
    if not os.environ.get("SCORPIO_URL"):
        return {}
    from sdk.registro import Registro
    from services.suscripciones.crear import preparar
    reg = Registro(os.environ["SCORPIO_URL"])
    return {"preparar_catastro": lambda tenant: preparar(reg, tenant), "catastro_disponible": reg.disponible}


app = _crear()
from sdk.trazas import configurar  # noqa: E402
configurar("instituciones", app)
