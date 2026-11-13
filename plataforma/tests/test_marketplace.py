"""Marketplace: escaparate, ficha, activar con permisos y quién lo usa, Mis productos y la barra según el rol.
El servicio de instituciones real (con Keycloak de mentira) contesta a la consola en el mismo proceso."""
from services.panel.app import COOKIE
from tests.test_panel_institucion import ALTA, entorno  # noqa: F401  (fixture)

ADMIN = "dir.naval@museo-naval:admin-institucion"
ARCH = "ana@museo-naval:archivera"
PALEO = "pepa@museo-naval:paleografa"


def _como(c, quien):
    c.cookies.set(COOKIE, quien)
    return c


def test_escaparate_con_los_tres_modelos(entorno):  # noqa: F811
    c, _ = entorno
    c.post("/panel/alta", data=ALTA)
    html = _como(c, ADMIN).get("/panel/productos").text
    for nombre in ("Legajo de la archivera", "Gemelo del archivo", "Scriptorium"):
        assert nombre in html
    assert html.count('class="modelo integrado"') == 2 and html.count('class="modelo externo"') == 1
    assert 'data-fuera="true"' in html and 'id="solo-dentro"' in html and 'data-oficio="Investigación"' in html
    assert 'aria-current="page"><span class="izq">Marketplace' in html


def test_ficha_dice_permisos_y_donde_van_los_datos(entorno):  # noqa: F811
    c, _ = entorno
    c.post("/panel/alta", data=ALTA)
    html = _como(c, ADMIN).get("/panel/marketplace/scriptorium").text
    assert "Tus datos salen de la plataforma" in html and "scriptorium-nsf.appincubator.dev" in html
    assert "Leer expedientes y transcripciones" in html and "Guardar ediciones anotadas" in html and "opcional" in html
    assert "Capacidad · corrector-htr" in html and "Receta · Edición anotada" in html
    assert 'href="/panel/marketplace/scriptorium/activar"' in html
    assert "Tus datos no salen de la plataforma" in c.get("/panel/marketplace/legajo").text
    # quien no administra la institución no puede activar
    assert "Pide a quien administra" in _como(c, ARCH).get("/panel/marketplace/scriptorium").text
    assert c.get("/panel/marketplace/scriptorium/activar").status_code == 403
    assert c.get("/panel/marketplace/no-existe").status_code == 404


def test_activar_con_permisos_y_roles_y_la_barra_lo_respeta(entorno):  # noqa: F811
    c, _ = entorno
    c.post("/panel/alta", data=ALTA)
    _como(c, ADMIN)
    form = c.get("/panel/marketplace/scriptorium/activar").text
    assert 'value="expedientes-lectura" checked disabled' in form and 'value="ediciones" checked>' in form
    assert 'value="paleografa" checked' in form and 'value="admin-institucion">' in form
    r = c.put("/panel/api/instituciones/activaciones/scriptorium",
              json={"activo": True, "permisos": ["recetas"], "roles": ["paleografa"]}).json()
    assert r["detalle"]["scriptorium"]["permisos"] == ["expedientes-lectura", "recetas"]
    mis = c.get("/panel/mis-productos").text
    assert "Scriptorium" in mis and "Lanzar recetas en tu nombre" in mis and "Guardar ediciones anotadas" not in mis
    assert "Paleógrafas" in mis and 'data-desactivar="scriptorium"' in mis
    # la administradora no lo tiene para su rol: no le sale en la barra
    assert 'href="https://scriptorium-nsf.appincubator.dev"' not in c.get("/panel").text
    # la paleógrafa sí, como enlace externo a su web
    barra = _como(c, PALEO).get("/panel").text
    assert 'href="https://scriptorium-nsf.appincubator.dev" target="_blank" rel="noopener"' in barra
    assert "Abrir ↗" in c.get("/panel/mis-productos").text and "data-desactivar=\"" not in c.get("/panel/mis-productos").text


def test_un_producto_integrado_solo_para_algunos_roles(entorno):  # noqa: F811
    c, _ = entorno
    c.post("/panel/alta", data=ALTA)
    _como(c, ADMIN).put("/panel/api/instituciones/activaciones/legajo", json={"activo": True, "roles": ["archivera"]})
    assert _como(c, ARCH).get("/panel/productos/legajo/").status_code == 200
    r = _como(c, PALEO).get("/panel/productos/legajo/")
    assert r.status_code == 403 and "no para tu rol" in r.text
    assert _como(c, ADMIN).put("/panel/api/instituciones/activaciones/legajo", json={"activo": False}).status_code == 200
    assert "Tu institución no tiene productos activados" in c.get("/panel/mis-productos").text


def test_las_instituciones_anteriores_lo_tienen_todo(entorno):  # noqa: F811
    c, _ = entorno
    mis = _como(c, "m.ortega@archivo-villanueva:archivera,admin-institucion").get("/panel/mis-productos").text
    assert "anterior al Marketplace" in mis and mis.count('class="tarjeta mk-mis"') == 3
