"""La consola y el autoservicio: alta sin sesión, «Mi institución» y productos según lo que cada una activa.
El servicio de instituciones real (con Keycloak de mentira) contesta a la consola en el mismo proceso."""
import httpx
import pytest
from fastapi.testclient import TestClient

from sdk.identidad import Identidad, NoAutorizado
from services.instituciones.app import Almacen, crear_app as crear_instituciones
from services.panel import app as panel_app
from services.panel.app import COOKIE, crear_app
from tests.test_instituciones import KeycloakFalso
from tests.test_panel import BusFalso, Exp, Reg

INST = "http://inst.test"


class Verif:
    """Token «usuario@tenant:rol,rol» (como en test_instituciones)."""
    def verificar(self, t):
        try:
            quien, roles = t.split(":", 1)
            usuario, tenant = quien.split("@")
        except ValueError:
            raise NoAutorizado(401, "no")
        return Identidad(usuario, tenant, [r for r in roles.split(",") if r])


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    kc = KeycloakFalso()
    inst = TestClient(crear_instituciones(verificador=Verif(), kc=kc, almacen=Almacen(str(tmp_path / "i.db"))))
    real_get, real_request = httpx.get, httpx.request

    def get(url, **kw):
        kw.pop("timeout", None)
        return inst.get(url, **kw) if str(url).startswith(INST) else real_get(url, **kw)

    def request(metodo, url, **kw):
        kw.pop("timeout", None)
        return inst.request(metodo, url, **kw) if str(url).startswith(INST) else real_request(metodo, url, **kw)
    monkeypatch.setattr(panel_app.httpx, "get", get)
    monkeypatch.setattr(panel_app.httpx, "request", request)
    # tras el alta la consola pide un token a Keycloak: aquí el token es la identidad
    monkeypatch.setattr(panel_app, "pedir_token", lambda _kc, u, _c: f"{u}@museo-naval:admin-institucion")
    app = crear_app(registro=Reg(), verificador=Verif(), expedientes=Exp(), keycloak_interno="http://kc",
                    procedencia="http://127.0.0.1:9", api_publico="http://srv:9080", enlaces={}, bus=BusFalso(),
                    sondas=lambda: [], servicios={"catalogo": "http://127.0.0.1:9", "instituciones": INST,
                                                  "conservacion": "http://127.0.0.1:9", "sensores": "http://127.0.0.1:9"})
    return TestClient(app), kc


ALTA = {"institucion": "museo-naval", "nombre": "Museo Naval", "usuario": "dir.naval", "clave": "una-clave-larga",
        "email": "dir@naval.es", "persona": "Ana Ruiz"}


def test_la_entrada_invita_al_alta(entorno):
    c, _ = entorno
    assert 'href="/panel/alta"' in c.get("/panel").text
    assert "Dar de alta la institución" in c.get("/panel/alta").text


def test_alta_entra_directamente_y_empieza_sin_productos(entorno):
    c, kc = entorno
    r = c.post("/panel/alta", data=ALTA, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/panel/institucion"
    assert kc.grupo("museo-naval") and r.cookies.get(COOKIE)
    c.cookies.set(COOKIE, "dir.naval@museo-naval:admin-institucion")
    pag = c.get("/panel/institucion").text
    assert "Mi institución" in pag and "Credenciales de API" in pag
    assert 'href="/panel/productos/legajo' not in c.get("/panel").text          # nada activado: no sale en la barra
    assert c.get("/panel/productos/legajo/").status_code == 403
    assert "activado" not in c.get("/panel/productos").text.split('aria-label="Productos"')[1]
    assert "Ver su ficha en el Marketplace" in c.get("/panel/productos/legajo/").text
    assert c.put("/panel/api/instituciones/activaciones/legajo", json={"activo": True}).json()["activos"] == ["legajo"]
    assert 'href="/panel/productos/legajo' in c.get("/panel").text
    assert c.get("/panel/productos/legajo/api/expedientes").status_code != 403


def test_alta_con_errores_vuelve_al_formulario(entorno):
    c, _ = entorno
    r = c.post("/panel/alta", data={**ALTA, "clave": "corta"})
    assert r.status_code == 422 and "10 caracteres" in r.text and 'value="museo-naval"' in r.text and "corta" not in r.text
    c.post("/panel/alta", data=ALTA)
    assert c.post("/panel/alta", data={**ALTA, "usuario": "otra.persona"}).status_code == 409


def test_las_instituciones_anteriores_lo_siguen_viendo_todo(entorno):
    c, _ = entorno
    c.cookies.set(COOKIE, "m.ortega@archivo-villanueva:archivera")
    pag = c.get("/panel").text
    assert 'href="/panel/productos/legajo' in pag and 'href="/panel/productos/gemelo' in pag
    assert c.get("/panel/api/instituciones/usuarios").status_code == 403      # no administra


def test_alta_desde_dentro_de_la_consola(entorno):
    c, kc = entorno
    c.cookies.set(COOKIE, "admin.paas@paas:admin-paas")
    assert 'href="/panel/instituciones"' in c.get("/panel").text
    pag = c.get("/panel/instituciones")
    assert pag.status_code == 200 and "Dar de alta una institución" in pag.text and "Todas las instituciones" in pag.text
    r = c.post("/panel/api/instituciones/instituciones", json=ALTA)
    assert r.status_code == 201 and kc.grupo("museo-naval")
    assert [i["id"] for i in c.get("/panel/api/instituciones/instituciones").json()] == ["archivo-villanueva", "museo-naval"]
    c.cookies.set(COOKIE, "m.ortega@archivo-villanueva:archivera,admin-institucion")
    assert 'href="/panel/instituciones"' not in c.get("/panel").text
    assert c.get("/panel/instituciones").status_code == 403
    assert c.post("/panel/api/instituciones/instituciones", json={**ALTA, "institucion": "otra"}).status_code == 403
