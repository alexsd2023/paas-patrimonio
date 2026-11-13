"""Instituciones: alta autoservicio, personas, productos y credenciales, con un Keycloak de mentira.
(Contra un Keycloak real lo recorre scripts/institucion_check.py.)"""
import itertools

import pytest
from fastapi.testclient import TestClient

from sdk.identidad import Identidad, NoAutorizado
from services.instituciones.app import Almacen, crear_app
from services.instituciones.keycloak import ErrorKeycloak

PRODUCTOS = {"legajo": "Legajo digital", "gemelo": "Gemelo del depósito"}


class KeycloakFalso:
    def __init__(self):
        self.n = itertools.count(1)
        self.grupos_ = {"archivo-villanueva": {"id": "g0", "name": "archivo-villanueva", "attributes": {}},
                        "paas": {"id": "gp", "name": "paas", "attributes": {}}}
        self.usuarios, self.en_grupo, self.roles, self.clientes = {}, {}, {}, {}
        self.fallar_en = None

    def _id(self, p):
        return f"{p}{next(self.n)}"

    def grupo(self, nombre):
        return self.grupos_.get(nombre)

    def grupos(self):
        return list(self.grupos_.values())

    def crear_grupo(self, nombre, atributos):
        g = {"id": self._id("g"), "name": nombre, "attributes": atributos}
        self.grupos_[nombre] = g
        return g["id"]

    def borrar_grupo(self, gid):
        self.grupos_ = {k: g for k, g in self.grupos_.items() if g["id"] != gid}

    def miembros(self, gid):
        return [self.usuarios[u] for u, g in self.en_grupo.items() if gid in g]

    def usuario_por_nombre(self, nombre):
        return next((u for u in self.usuarios.values() if u["username"] == nombre), None)

    def usuario(self, uid):
        if uid not in self.usuarios:
            raise ErrorKeycloak(404, "no")
        return self.usuarios[uid]

    def grupos_de(self, uid):
        if uid not in self.usuarios:
            raise ErrorKeycloak(404, "no")
        return [g["name"] for g in self.grupos_.values() if g["id"] in self.en_grupo.get(uid, set())]

    def crear_usuario(self, nombre, clave, email=None, nombre_visible=""):
        if self.fallar_en == "usuario":
            raise ErrorKeycloak(500, "se cayó")
        uid = self._id("u")
        self.usuarios[uid] = {"id": uid, "username": nombre, "email": email, "enabled": True, "firstName": nombre_visible}
        return uid

    def borrar_usuario(self, uid):
        self.usuarios.pop(uid, None)

    def poner_en_grupo(self, uid, gid):
        self.en_grupo.setdefault(uid, set()).add(gid)

    def activar(self, uid, activo):
        self.usuarios[uid]["enabled"] = activo

    def poner_clave(self, uid, clave):
        self.usuarios[uid]["clave"] = clave

    def roles_de(self, uid):
        return sorted(self.roles.get(uid, set()))

    def dar_roles(self, uid, nombres):
        if self.fallar_en == "roles":
            raise ErrorKeycloak(500, "se cayó")
        self.roles.setdefault(uid, set()).update(nombres)

    def quitar_roles(self, uid, nombres):
        self.roles.setdefault(uid, set()).difference_update(nombres)

    def crear_cliente_app(self, client_id, nombre):
        cid = self._id("c")
        sa = self.crear_usuario(f"service-account-{client_id}", "x")
        self.clientes[cid] = {"id": cid, "clientId": client_id, "sa": sa}
        return cid

    def cliente_por_id(self, client_id):
        return next((c for c in self.clientes.values() if c["clientId"] == client_id), None)

    def secreto_de(self, cid):
        return "s3cr3t"

    def usuario_de_servicio(self, cid):
        return self.usuarios[self.clientes[cid]["sa"]]

    def borrar_cliente(self, cid):
        self.clientes.pop(cid)


class Verif:
    """El token es «usuario@tenant:rol,rol»: así cada prueba se fabrica la identidad que necesita."""
    def verificar(self, t):
        try:
            quien, roles = t.split(":", 1)
            usuario, tenant = quien.split("@")
        except ValueError:
            raise NoAutorizado(401, "token no válido")
        return Identidad(usuario, tenant, [r for r in roles.split(",") if r])


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def entorno(tmp_path):
    kc = KeycloakFalso()
    c = TestClient(crear_app(verificador=Verif(), kc=kc, almacen=Almacen(str(tmp_path / "i.db")), productos=PRODUCTOS))
    return c, kc


ALTA = {"institucion": "museo-naval", "nombre": "Museo Naval", "usuario": "dir.naval", "clave": "una-clave-larga",
        "email": "dir@naval.es", "persona": "Ana Ruiz"}
ADMIN = "dir.naval@museo-naval:admin-institucion"


def test_alta_crea_institucion_y_su_administradora(entorno):
    c, kc = entorno
    r = c.post("/registro", json=ALTA)
    assert r.status_code == 201 and r.json()["roles"] == ["admin-institucion"]
    uid = kc.usuario_por_nombre("dir.naval")["id"]
    assert kc.grupos_de(uid) == ["museo-naval"] and kc.roles_de(uid) == ["admin-institucion"]
    assert kc.grupo("museo-naval")["attributes"] == {"nombre": ["Museo Naval"]}
    assert c.post("/registro", json=ALTA).status_code == 409
    yo = c.get("/yo", headers=_h(ADMIN)).json()
    assert yo["nombre"] == "Museo Naval" and yo["gestionada"] and yo["activos"] == [] and yo["admin"]


@pytest.mark.parametrize("cambio", [{"institucion": "Museo Naval"}, {"institucion": "paas"}, {"usuario": "x"},
                                    {"clave": "corta"}, {"email": "no-es-email"}, {"email": None}, {"nombre": ""}])
def test_alta_valida_los_datos(entorno, cambio):
    c, _ = entorno
    assert c.post("/registro", json={**ALTA, **cambio}).status_code == 422


def test_alta_no_deja_nada_a_medias(entorno):
    c, kc = entorno
    kc.fallar_en = "roles"
    assert c.post("/registro", json=ALTA).status_code == 502
    assert kc.grupo("museo-naval") is None and kc.usuario_por_nombre("dir.naval") is None


def test_alta_cerrada(tmp_path):
    c = TestClient(crear_app(verificador=Verif(), kc=KeycloakFalso(), almacen=Almacen(str(tmp_path / "i.db")),
                             registro_abierto=False, productos=PRODUCTOS))
    assert c.post("/registro", json=ALTA).status_code == 403


def test_productos_activables_y_las_antiguas_lo_tienen_todo(entorno):
    c, _ = entorno
    c.post("/registro", json=ALTA)
    assert c.put("/activaciones/legajo", json={"activo": True}, headers=_h("x@museo-naval:archivera")).status_code == 403
    assert c.put("/activaciones/otro", json={"activo": True}, headers=_h(ADMIN)).status_code == 404
    assert c.put("/activaciones/legajo", json={"activo": True}, headers=_h(ADMIN)).json()["activos"] == ["legajo"]
    assert c.get("/activaciones", headers=_h("x@museo-naval:archivera")).json()["activos"] == ["legajo"]
    antigua = "m.ortega@archivo-villanueva:archivera,admin-institucion"
    r = c.get("/activaciones", headers=_h(antigua)).json()
    assert (r["gestionada"], r["activos"]) == (False, ["gemelo", "legajo"])
    # al desactivar algo, pasa a gestionada conservando lo demás
    r = c.put("/activaciones/gemelo", json={"activo": False}, headers=_h(antigua)).json()
    assert (r["gestionada"], r["activos"]) == (True, ["legajo"])


def test_activar_con_permisos_y_quien_lo_usa(tmp_path):
    prods = {"scriptorium": {"nombre": "Scriptorium", "permisos": [
        {"id": "leer", "opcional": False}, {"id": "ediciones", "opcional": True}, {"id": "recetas", "opcional": True}]}}
    c = TestClient(crear_app(verificador=Verif(), kc=KeycloakFalso(), almacen=Almacen(str(tmp_path / "i.db")), productos=prods))
    c.post("/registro", json=ALTA)
    url = "/activaciones/scriptorium"
    # los imprescindibles van siempre, aunque no se pidan
    r = c.put(url, json={"activo": True, "permisos": ["recetas"], "roles": ["paleografa"]}, headers=_h(ADMIN)).json()
    assert r["detalle"]["scriptorium"]["permisos"] == ["leer", "recetas"]
    assert r["detalle"]["scriptorium"]["roles"] == ["paleografa"] and r["detalle"]["scriptorium"]["por"] == "dir.naval"
    assert c.put(url, json={"activo": True, "permisos": ["borrarlo-todo"]}, headers=_h(ADMIN)).status_code == 422
    assert c.put(url, json={"activo": True, "roles": ["admin-paas"]}, headers=_h(ADMIN)).status_code == 422
    assert c.put(url, json={"activo": True, "roles": []}, headers=_h(ADMIN)).status_code == 422
    # sin permisos ni roles: todos
    r = c.put(url, json={"activo": True}, headers=_h(ADMIN)).json()
    assert r["detalle"]["scriptorium"] == {**r["detalle"]["scriptorium"], "permisos": ["leer", "ediciones", "recetas"], "roles": None}
    # cualquiera de la institución lo ve (la consola decide qué enseña según sus roles)
    assert c.get("/activaciones", headers=_h("x@museo-naval:archivera")).json()["detalle"]["scriptorium"]["roles"] is None


def test_almacen_antiguo_se_migra(tmp_path):
    import sqlite3
    db = str(tmp_path / "viejo.db")
    with sqlite3.connect(db) as con:
        con.execute("create table activaciones (tenant text, producto text, por text, cuando real, primary key (tenant, producto))")
        con.execute("insert into activaciones values ('museo', 'legajo', 'ana', 1)")
    a = Almacen(db)
    assert a.detalle("museo") == {"legajo": {"por": "ana", "cuando": 1.0, "permisos": None, "roles": None}}


def test_personas_solo_de_mi_institucion_y_sin_escalar(entorno):
    c, kc = entorno
    c.post("/registro", json=ALTA)
    nueva = {"usuario": "ana.p", "clave": "otra-clave-larga", "email": "ana@naval.es", "roles": ["paleografa"]}
    assert c.post("/usuarios", json=nueva, headers=_h("x@museo-naval:archivera")).status_code == 403
    assert c.post("/usuarios", json={**nueva, "roles": ["admin-paas"]}, headers=_h(ADMIN)).status_code == 422
    r = c.post("/usuarios", json=nueva, headers=_h(ADMIN))
    assert r.status_code == 201 and r.json()["roles"] == ["paleografa"]
    ana = r.json()["id"]
    assert sorted(u["usuario"] for u in c.get("/usuarios", headers=_h(ADMIN)).json()) == ["ana.p", "dir.naval"]
    assert c.put(f"/usuarios/{ana}", json={"roles": ["archivera"], "activo": False}, headers=_h(ADMIN)).json()["activo"] is False
    assert kc.roles_de(ana) == ["archivera"]
    # otra institución no la ve ni la toca
    assert c.put(f"/usuarios/{ana}", json={"activo": True}, headers=_h("dir@otro:admin-institucion")).status_code == 404
    yo = kc.usuario_por_nombre("dir.naval")["id"]
    assert c.put(f"/usuarios/{yo}", json={"roles": ["archivera"]}, headers=_h(ADMIN)).status_code == 409
    assert c.put(f"/usuarios/{yo}", json={"activo": False}, headers=_h(ADMIN)).status_code == 409


def test_credenciales_de_api(entorno):
    c, kc = entorno
    c.post("/registro", json=ALTA)
    r = c.post("/credenciales", json={"nombre": "Catálogo web", "roles": ["archivera"]}, headers=_h(ADMIN))
    assert r.status_code == 201 and r.json()["client_id"] == "app-museo-naval-catalogo-web" and r.json()["secreto"]
    sa = kc.usuario_por_nombre("service-account-app-museo-naval-catalogo-web")["id"]
    assert kc.grupos_de(sa) == ["museo-naval"] and kc.roles_de(sa) == ["archivera"]
    assert "secreto" not in c.get("/credenciales", headers=_h(ADMIN)).json()[0]
    assert c.post("/credenciales", json={"nombre": "x", "roles": ["admin-institucion"]}, headers=_h(ADMIN)).status_code == 422
    assert c.delete("/credenciales/app-museo-naval-catalogo-web", headers=_h("d@otro:admin-institucion")).status_code == 404
    assert c.delete("/credenciales/app-museo-naval-catalogo-web", headers=_h(ADMIN)).json() == {"ok": True}
    assert kc.cliente_por_id("app-museo-naval-catalogo-web") is None and c.get("/credenciales", headers=_h(ADMIN)).json() == []


def test_solo_operadores_ven_todas(entorno):
    c, _ = entorno
    c.post("/registro", json=ALTA)
    assert c.get("/instituciones", headers=_h(ADMIN)).status_code == 403
    todas = c.get("/instituciones", headers=_h("admin.paas@paas:admin-paas")).json()
    assert [(i["id"], i["gestionada"]) for i in todas] == [("archivo-villanueva", False), ("museo-naval", True)]


def test_el_equipo_del_paas_da_altas_aunque_el_registro_este_cerrado(tmp_path):
    kc = KeycloakFalso()
    c = TestClient(crear_app(verificador=Verif(), kc=kc, almacen=Almacen(str(tmp_path / "i.db")),
                             registro_abierto=False, productos=PRODUCTOS))
    assert c.post("/instituciones", json=ALTA, headers=_h(ADMIN)).status_code == 403
    r = c.post("/instituciones", json=ALTA, headers=_h("admin.paas@paas:admin-paas"))
    assert r.status_code == 201 and kc.roles_de(kc.usuario_por_nombre("dir.naval")["id"]) == ["admin-institucion"]
    i = next(x for x in c.get("/instituciones", headers=_h("admin.paas@paas:admin-paas")).json() if x["id"] == "museo-naval")
    assert i["gestionada"] and i["por"] == "admin.paas" and i["activos"] == []
    assert c.post("/instituciones", json={**ALTA, "clave": "corta"}, headers=_h("admin.paas@paas:admin-paas")).status_code == 422


def test_el_alta_conecta_el_catastro_al_bus(tmp_path):
    conectados = []
    c = TestClient(crear_app(verificador=Verif(), kc=KeycloakFalso(), almacen=Almacen(str(tmp_path / "i.db")),
                             productos=PRODUCTOS, preparar_catastro=conectados.append))
    assert c.post("/registro", json=ALTA).json()["catastro"] == "conectado" and conectados == ["museo-naval"]


def test_si_scorpio_falla_el_alta_vale_y_queda_pendiente(tmp_path):
    def caido(_t):
        raise OSError("scorpio no responde")
    c = TestClient(crear_app(verificador=Verif(), kc=KeycloakFalso(), almacen=Almacen(str(tmp_path / "i.db")),
                             productos=PRODUCTOS, preparar_catastro=caido))
    r = c.post("/registro", json=ALTA)
    assert r.status_code == 201 and r.json()["catastro"] == "pendiente"
    assert c.post("/instituciones/museo-naval/catastro", headers=_h("admin.paas@paas:admin-paas")).status_code == 502


def test_al_arrancar_se_reparan_las_instituciones_ya_dadas_de_alta(tmp_path):
    import time
    almacen = Almacen(str(tmp_path / "i.db"))
    almacen.alta("museo-viejo", "Museo viejo", "ana")
    almacen.alta("archivo-viejo", "Archivo viejo", "luis")
    conectados, listo = [], {"n": 0}

    def disponible():                      # Scorpio tarda en arrancar: responde a la segunda
        listo["n"] += 1
        return listo["n"] > 1
    app = crear_app(verificador=Verif(), kc=KeycloakFalso(), almacen=almacen, productos=PRODUCTOS,
                    preparar_catastro=conectados.append, catastro_disponible=disponible)
    import services.instituciones.app as modulo
    original = modulo.time.sleep
    modulo.time.sleep = lambda s: None
    try:
        with TestClient(app):
            fin = time.monotonic() + 5
            while len(conectados) < 2 and time.monotonic() < fin:
                original(0.02)
    finally:
        modulo.time.sleep = original
    assert sorted(conectados) == ["archivo-viejo", "museo-viejo"]


def test_el_equipo_del_paas_reconecta_un_catastro(tmp_path):
    conectados = []
    c = TestClient(crear_app(verificador=Verif(), kc=KeycloakFalso(), almacen=Almacen(str(tmp_path / "i.db")),
                             productos=PRODUCTOS, preparar_catastro=conectados.append))
    assert c.post("/instituciones/archivo-villanueva/catastro", headers=_h(ADMIN)).status_code == 403
    assert c.post("/instituciones/no-existe/catastro", headers=_h("admin.paas@paas:admin-paas")).status_code == 404
    r = c.post("/instituciones/archivo-villanueva/catastro", headers=_h("admin.paas@paas:admin-paas"))
    assert r.json() == {"institucion": "archivo-villanueva", "catastro": "conectado"} and conectados == ["archivo-villanueva"]
