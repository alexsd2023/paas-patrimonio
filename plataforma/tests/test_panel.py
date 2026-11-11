"""La consola: núcleo y productos separados, cada producto con sus vistas (sin red)."""
import pytest
from fastapi.testclient import TestClient

from productos.legajo.datos import pasos
from sdk.identidad import Identidad, NoAutorizado
from services.panel.app import COOKIE, crear_app
from services.panel.productos import ProductoInvalido, descubrir, leer_manifiesto

A = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"
T = "urn:ngsi-ld:Transcripcion:archivo-villanueva:TEST-001-t1"
P = lambda x: {"type": "Property", "value": x}  # noqa: E731
R = lambda x: {"type": "Relationship", "object": x}  # noqa: E731
DEP = {"id": "urn:ngsi-ld:Deposito:archivo-villanueva:D1", "type": "Deposito", "nombre": P("Depósito 1 · sótano"),
       "temperatura": P(17.6), "humedad": P(48.0), "estadoAmbiental": P("ok")}
CAJA = {"id": "urn:ngsi-ld:Caja:archivo-villanueva:C-002", "type": "Caja", "nombre": P("C-002"), "enDeposito": R(DEP["id"])}
ACTIVO = {"id": A, "type": "ActivoPatrimonial", "signatura": P("TEST-001"), "ark": P("ark:/99999/x"),
          "manifiesto": P("http://srv:9080/iiif/3/archivo-villanueva/TEST-001/manifest"), "imagenes": P(3),
          "ingestadoPor": P("m.ortega"), "createdAt": "2026-11-08T10:00:00Z", "enCaja": R(CAJA["id"])}
COPIA = {"id": T, "type": "Transcripcion", "deActivo": R(A), "estado": P("pendiente-validacion"),
         "modelo": P("htr-mock@0.1"), "lineas": P(42), "texto": P("En la villa…")}
TODO = {"ActivoPatrimonial": [ACTIVO], "Transcripcion": [COPIA], "Deposito": [DEP], "Caja": [CAJA]}


def test_recorrido_esperando_la_firma():
    ps = pasos(ACTIVO, COPIA, {"estado": "pendiente-validacion"},
               [{"tipo": "ingreso", "tiempo": "t1"}, {"tipo": "htr", "tiempo": "t2"}])
    assert [p["estado"] for p in ps] == ["hecho"] * 6 + ["esperando", "pendiente"]


class Reg:
    def listar(self, tenant, tipo):
        return TODO.get(tipo, []) if tenant == "archivo-villanueva" else []

    def leer(self, tenant, i):
        if tenant != "archivo-villanueva":
            return None
        return {x["id"]: x for xs in TODO.values() for x in xs}.get(i)


class Verif:
    P = {"tok-o": Identidad("m.ortega", "archivo-villanueva", ["archivera"]),
         "tok-p": Identidad("paleografa-test", "archivo-villanueva", ["paleografa"]),
         "tok-x": Identidad("p.otro", "otro-archivo", ["paleografa"])}

    def verificar(self, t):
        if t not in self.P:
            raise NoAutorizado(401, "no")
        return self.P[t]


class Exp:
    def listar(self, a):
        return [{"id": f"transcripcion:{a}", "estado": "pendiente-validacion"}]


class BusFalso:
    def buzones(self):
        return [{"buzon": "activos", "cartas": 7, "particiones": 1}, {"buzon": "sensores", "cartas": 900, "particiones": 1}]

    def ultimas(self, tenant):
        cartas = [{"buzon": "activos", "tipo": "legajo.ingestado", "sujeto": A, "tenant": "archivo-villanueva",
                   "tiempo": "2026-11-08T10:00:01Z", "traza": "ab" * 16},
                  {"buzon": "activos", "tipo": "legajo.ingestado", "sujeto": "x", "tenant": "otro-archivo",
                   "tiempo": "2026-11-08T10:00:02Z", "traza": None}]
        return [c for c in cartas if c["tenant"] == tenant]


def cliente(token=None, **kw):
    app = crear_app(registro=Reg(), verificador=Verif(), expedientes=Exp(), keycloak_interno="http://kc",
                    procedencia="http://127.0.0.1:9", api_publico="http://srv:9080",
                    enlaces={"temporal": "http://srv:8233", "jaeger": "http://srv:16686"}, bus=BusFalso(),
                    sondas=lambda: [{"pieza": "correos", "nombre": "Correos · Kafka", "destino": "kafka:29092",
                                     "ok": True, "ms": 2, "detalle": None}],
                    servicios={"conservacion": "http://127.0.0.1:9", "sensores": "http://127.0.0.1:9",
                              "catalogo": "http://127.0.0.1:9", "instituciones": "http://127.0.0.1:9"}, **kw)
    c = TestClient(app)
    if token:
        c.cookies.set(COOKIE, token)
    return c


# ---------- productos: manifiesto y descubrimiento ----------
def test_descubre_los_productos_de_la_carpeta():
    productos = descubrir()
    assert [c.id for c in productos] == ["legajo", "gemelo"]
    leg = productos[0]
    assert leg.color == "#3FA594" and "catastro" in leg.usa and leg.url("validar") == "/panel/productos/legajo/validar"
    assert len(leg.tramos) == 16 and callable(leg.montar)


def test_un_manifiesto_mal_escrito_dice_que_falta():
    with pytest.raises(ProductoInvalido) as e:
        leer_manifiesto({"id": "tei", "nombre": "TEI", "color": "morado", "usa": ["blockchain"], "vistas": []}, "tei")
    msg = str(e.value)
    assert "falta resumen" in msg and "color" in msg and "blockchain" in msg and "vistas" in msg


def test_un_producto_roto_no_tumba_la_consola(tmp_path):
    (tmp_path / "roto").mkdir()
    (tmp_path / "roto" / "producto.yaml").write_text("id: roto\nnombre: Roto\n")
    assert descubrir(tmp_path) == []


# ---------- núcleo ----------
def test_sin_sesion_pide_entrar():
    c = cliente()
    assert 'action="/panel/entrar"' in c.get("/panel").text
    assert 'action="/panel/entrar"' in c.get("/panel/productos/legajo").text
    assert c.get("/panel/api/nucleo/estado").status_code == 401
    assert c.get("/panel/productos/legajo/api/legajos").status_code == 401


def test_la_barra_separa_nucleo_y_productos():
    html = cliente("tok-o").get("/panel").text
    nucleo, productos = html.split("Núcleo del PaaS</span>", 1)[1].split("Productos</span>", 1)
    assert "Estado de la plataforma" in nucleo and "Cartas · bus" in nucleo and "Temporal" in nucleo
    assert "Legajo de la archivera" in productos and "Gemelo del archivo" in productos
    assert "Legajo de la archivera" not in nucleo


def test_estado_del_nucleo_no_sabe_de_legajos():
    d = cliente("tok-o").get("/panel/api/nucleo/estado").json()
    assert d["sondas"][0]["ok"] and [c["id"] for c in d["productos"]] == ["legajo", "gemelo"]
    assert d["buzonesPorProducto"]["activos"] == ["Legajo de la archivera"]
    assert d["buzonesPorProducto"]["sensores"] == ["Gemelo del archivo"]


def test_cartas_solo_de_mi_institucion():
    assert [x["sujeto"] for x in cliente("tok-o").get("/panel/api/nucleo/cartas").json()["ultimas"]] == [A]
    assert [x["sujeto"] for x in cliente("tok-x").get("/panel/api/nucleo/cartas").json()["ultimas"]] == ["x"]


def test_catalogo_lista_los_productos_y_como_conectar_uno():
    html = cliente("tok-o").get("/panel/productos").text
    assert "Legajo de la archivera" in html and "Gemelo del archivo" in html and 'id="conectar"' in html


# ---------- producto: legajo ----------
def test_vistas_del_legajo_con_su_cabecera():
    c = cliente("tok-o")
    for ruta, vista in [("", "Legajos"), ("/entregar", "Entregar"), ("/validar", "Validar"), ("/tramos", "Tramos")]:
        html = c.get("/panel/productos/legajo" + ruta).text
        assert "--producto:#3FA594" in html and "Del núcleo usa" in html
        assert f'aria-current="page">{vista}<' in html
    assert "16 de 16" in c.get("/panel/productos/legajo/tramos").text


def test_cada_uno_ve_su_institucion():
    c = cliente("tok-o")
    assert [f["signatura"] for f in c.get("/panel/productos/legajo/api/legajos").json()] == ["TEST-001"]
    d = c.get("/panel/productos/legajo/api/legajo", params={"activo": A}).json()
    assert d["resumen"]["estado"] == "pendiente" and len(d["miniaturas"]) == 3
    assert d["ubicacion"]["caja"] == "C-002"
    assert d["temporal"].startswith("http://srv:8233/namespaces/default/workflows/")
    assert d["avisos"]  # el notario de prueba no responde: se avisa, no se rompe
    x = cliente("tok-x")
    assert x.get("/panel/productos/legajo/api/legajos").json() == []
    assert x.get("/panel/productos/legajo/api/legajo", params={"activo": A}).status_code == 403


def test_pendientes_y_cajas_del_legajo():
    c = cliente("tok-p")
    assert [p["signatura"] for p in c.get("/panel/productos/legajo/api/pendientes").json()] == ["TEST-001"]
    assert c.get("/panel/productos/legajo/api/cajas").json() == [{"deposito": "Depósito 1 · sótano", "cajas": ["C-002"]}]


def test_solo_la_archivera_entrega():
    c = cliente("tok-p")
    assert "Solo una archivera" in c.get("/panel/productos/legajo/entregar").text
    r = c.post("/panel/productos/legajo/api/ingesta", data={"signatura": "X-1"}, files={"imagenes": ("a.jpg", b"x", "image/jpeg")})
    assert r.status_code == 403


# ---------- producto: gemelo ----------
def test_gemelo_con_sus_vistas_y_datos():
    c = cliente("tok-o")
    assert "--producto:#D9A23B" in c.get("/panel/productos/gemelo").text
    deps = c.get("/panel/productos/gemelo/api/depositos").json()  # sensores y conservación no responden: se sigue
    assert deps[0]["codigo"] == "D1" and deps[0]["cajas"] == ["C-002"] and deps[0]["legajos"] == 1
    assert c.get("/panel/productos/gemelo/api/cajas").json()[0]["legajos"] == ["TEST-001"]
    assert cliente("tok-p").post("/panel/productos/gemelo/api/escenario", json={"deposito": "D1", "escenario": "fuga"}).status_code == 403


# ---------- servicios y flujos en la consola ----------
def test_servicios_y_flujos_en_el_nucleo():
    c = cliente("tok-o")
    nucleo = c.get("/panel/servicios").text.split("Núcleo del PaaS</span>", 1)[1].split("Productos</span>", 1)[0]
    assert 'aria-current="page"><span class="izq">Servicios' in nucleo and "/panel/recetas/ejecuciones" in nucleo
    assert "Receta (YAML)" in c.get("/panel/recetas/nueva").text
    assert 'id="plantillas"' in c.get("/panel/recetas").text and 'id="flujos"' in c.get("/panel/recetas/ejecuciones").text
    r = c.get("/panel/flujos", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/panel/recetas/ejecuciones"
    r = c.post("/panel/api/flujos/validar", json={"yaml": "nombre: [sin cerrar"})
    assert r.status_code == 422 and "YAML" in r.json()["detail"]["errores"][0]
    assert c.get("/panel/api/catalogo/servicios").status_code == 503  # sin catálogo: se avisa


def test_la_barra_tiene_las_cuatro_capas_en_orden():
    html = cliente("tok-o").get("/panel/conectores").text
    i = [html.index(f'<span class="eyebrow">{c}</span>') for c in ("Núcleo del PaaS", "Capacidades", "Productos", "Conectores")]
    assert i == sorted(i)
    capacidades = html[i[1]:i[2]]
    assert "/panel/servicios" in capacidades and "/panel/recetas" in capacidades
    assert 'aria-current="page"><span class="izq">Sistemas de la institución' in html[i[3]:]
    assert "Conectores · Sistemas de la institución" in html


def test_el_estado_resume_las_capas():
    d = cliente("tok-o").get("/panel/api/nucleo/estado").json()
    assert d["capas"]["productos"] == 2 and d["capas"]["capacidades"] is None  # sin catálogo: no se inventa


# ---------- consolas técnicas dentro de la consola ----------
def test_las_consolas_tecnicas_se_abren_dentro_de_la_consola():
    c = cliente("tok-x")   # cualquier usuario con sesión, de cualquier institución
    html = c.get("/panel").text
    nucleo = html.split('Núcleo del PaaS</span>', 1)[1].split('Capacidades</span>', 1)[0]
    for clave in ("jaeger", "temporal", "kafka", "mlflow", "fuseki"):
        assert f'href="/panel/nucleo/{clave}"' in nucleo
    marco = c.get("/panel/nucleo/jaeger").text
    assert 'class="consola-externa" src="/panel/jaeger/search"' in marco and "Abrir en pestaña nueva" in marco
    assert 'aria-current="page"><span class="izq">Trazas' in marco
    assert c.get("/panel/nucleo/otra").status_code == 404


def test_la_puerta_pregunta_a_la_consola_antes_de_dejar_pasar():
    r = cliente().get("/panel/api/autorizar", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/panel"         # sin sesión: a entrar
    r = cliente("tok-o").get("/panel/api/autorizar")
    assert r.status_code == 200 and r.headers["x-tenant"] == "archivo-villanueva"
    r = cliente().get("/panel/api/autorizar", headers={"Authorization": "Bearer tok-p"})
    assert r.status_code == 200 and r.headers["x-usuario"] == "paleografa-test"   # scripts con token
    assert cliente().get("/panel/api/autorizar", headers={"Authorization": "Bearer malo"},
                         follow_redirects=False).status_code == 302
