"""Gemelo patrimonial (sin red): simulador, series, evaluación EN 15757, alertas con firma, notario y API."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from capacidades.evaluacion_en15757.motor import evaluar
from productos.gemelo import modelo as M
from sdk.contratos import validar
from sdk.registro import entidad_activo, entidad_caja, entidad_deposito, urn_deposito
from services.conservacion.app import Vigilante, crear_app
from services.conservacion.patrimonial import Conflicto, FirmasDirectas, GemeloPatrimonial, decidir
from services.conservacion.series import SeriesLocal, SeriesScorpio
from services.procedencia.app import Registro as Libro
from services.sensores.app import UMBRALES, SimuladorPatrimonial

T = "archivo-villanueva"
AHORA = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)


class Catastro:
    """Scorpio en memoria: lo justo para el gemelo."""

    def __init__(self):
        self.e = {}

    def disponible(self):
        return True

    def crear(self, t, x):
        if (t, x["id"]) in self.e:
            return 409
        self.e[(t, x["id"])] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in x.items()}
        return 201

    def leer(self, t, i):
        return self.e.get((t, i))

    def listar(self, t, tipo, limite=200):
        return [x for (tt, _), x in self.e.items() if tt == t and x["type"] == tipo]

    def anadir_atributos(self, t, i, a):
        if (t, i) not in self.e:
            return 404
        self.e[(t, i)].update(a)
        return 204

    def borrar(self, t, i):
        return 204 if self.e.pop((t, i), None) else 404


class Pub:
    def __init__(self):
        self.ev = []

    def publicar(self, e):
        self.ev.append(validar(e))      # todo lo que sale cumple su contrato

    def de(self, tipo):
        return [e for e in self.ev if e["type"] == tipo]


@pytest.fixture
def mundo():
    reg, pub = Catastro(), Pub()
    reg.crear(T, entidad_deposito(T, "D1", nombre="Depósito 1 · sótano", umbrales=UMBRALES))
    reg.crear(T, entidad_caja(T, "C-001", "D1"))
    legajo = entidad_activo(T, signatura="AV-1", ark="ark:/1/x", manifiesto="m", imagenes=1, ingestado_por="m.ortega",
                            caja="C-001")
    reg.crear(T, legajo)
    sim = SimuladorPatrimonial(reg)
    sim.sembrar(T)
    reloj = {"ahora": AHORA}
    g = GemeloPatrimonial(registro=reg, series=SeriesLocal(), publicador=pub, capacidad=lambda t, s, p: evaluar(s, p),
                          legajos_de=Vigilante(reg, pub).legajos_en, reloj=lambda: reloj["ahora"])
    g.firmas = FirmasDirectas(g)
    return {"reg": reg, "pub": pub, "sim": sim, "g": g, "legajo": legajo["id"], "reloj": reloj}


# ---------- el inmueble y el simulador ----------
def test_el_inmueble_de_ejemplo_se_inscribe_una_vez_y_enlaza_los_depositos(mundo):
    reg, sim = mundo["reg"], mundo["sim"]
    cuenta = {tipo: len(reg.listar(T, tipo)) for tipo in M.TIPOS[:5]}
    assert cuenta == {"HeritageBuilding": 1, "HeritageZone": 4, "HeritageElement": 3, "EnvironmentalSensor": 6,
                      "IndoorEnvironmentObserved": 6}
    z2 = reg.leer(T, M.urn("HeritageZone", T, "Z02"))
    assert M.v(z2, "refDeposito") == urn_deposito(T, "D1") and M.v(z2, "zoneType") == "depósito"
    assert M.v(reg.leer(T, M.urn("HeritageZone", T, "Z03")), "refDeposito") is None   # D2 no existe aquí
    assert sim.sembrar(T) == 0 and len(sim.sensores) == 6


def test_el_simulador_escribe_lecturas_y_cambia_de_perfil_en_caliente(mundo):
    reg, sim = mundo["reg"], mundo["sim"]
    assert sim.leer_y_escribir() == 6
    obs = reg.leer(T, M.urn("IndoorEnvironmentObserved", T, "S02"))
    assert 30 < M.v(obs, "relativeHumidity") < 90 and M.observado(obs, "relativeHumidity")
    assert M.v(reg.leer(T, M.urn("EnvironmentalSensor", T, "S02")), "operStatus") == "OK"
    assert sim.perfil(T, "Z02", "desviacion")["perfil"] == "desviacion"
    assert {p["zona"]: p["perfil"] for p in sim.perfiles_de(T)}["Z02"] == "desviacion"
    with pytest.raises(ValueError):
        sim.perfil(T, "Z02", "terremoto")
    with pytest.raises(KeyError):
        sim.perfil(T, "Z99", "estable")


# ---------- series ----------
def test_las_lecturas_del_bus_se_guardan_y_se_compactan(mundo):
    g = mundo["g"]
    z = M.urn("HeritageZone", T, "Z01")
    s = M.urn("EnvironmentalSensor", T, "S01")
    for minuto, h in ((0, 50.0), (30, 52.0)):
        g.manejar({"type": "zona.medicion", "tenant": T, "subject": z,
                   "data": {"sensor": s, "temperatura": 20.0, "humedad": h, "observadoEn": f"2026-11-10T08:{minuto:02d}:00Z"}})
    assert g.ahora(T, z)[0]["humedad"] == 52.0 and T in g.series.tenants()
    hora = g.series.horaria(T, z, AHORA - timedelta(days=10), AHORA)
    assert hora == [{"t": "2026-11-10T08:00:00Z", "temperatura": 20.0, "humedad": 51.0, "origen": "real"}]
    assert g.series.compactar(AHORA) == 2
    assert g.series.horaria(T, z, AHORA - timedelta(days=10), AHORA)[0]["humedad"] == 51.0


def test_la_api_temporal_de_scorpio_se_lee_por_instancias():
    class Reg:
        def _req(self, metodo, ruta, tenant):
            assert "temporal/entities" in ruta and "refZone" in ruta and tenant == T
            return 200, [{"id": "o1", "temperature": [{"value": 18, "observedAt": "2026-11-16T09:10:00Z"},
                                                      {"value": 19, "observedAt": "2026-11-16T09:40:00Z"}],
                          "relativeHumidity": [{"value": 50, "observedAt": "2026-11-16T09:10:00Z"},
                                               {"value": 54, "observedAt": "2026-11-16T09:40:00Z"}]}]
    s = SeriesScorpio(Reg())
    s.guardar_muchas(T, "z", [{"t": "2026-11-16T08:00:00Z", "temperatura": 17, "humedad": 49}])
    h = s.horaria(T, "z", AHORA - timedelta(days=1), AHORA)
    assert [(p["t"][11:13], p["humedad"], p["origen"]) for p in h] == [("08", 49, "sintetico"), ("09", 52, "real")]


# ---------- evaluación y alertas ----------
def test_decidir_que_hacer_con_la_alerta():
    assert decidir(None, "medio", AHORA, 7) == [("abrir", "medio")]
    assert decidir(None, "bajo", AHORA, 7) == []
    assert decidir({"nivel": "medio"}, "alto", AHORA, 7) == [("agravar", "alto")]
    assert decidir({"nivel": "alto"}, "medio", AHORA, 7) == []
    assert decidir({"nivel": "medio"}, "bajo", AHORA, 7)[0][0] == "bajo-desde"
    hace = (AHORA - timedelta(days=8)).isoformat()
    assert decidir({"nivel": "medio", "bajoDesde": hace}, "bajo", AHORA, 7) == [("proponer-cierre", None)]
    assert decidir({"nivel": "medio", "bajoDesde": hace, "propuesta": True}, "bajo", AHORA, 7) == []
    assert decidir({"nivel": "medio", "bajoDesde": hace}, "medio", AHORA, 7) == [("sigue-en-riesgo", None)]


def test_preparar_genera_el_historico_y_evaluar_escribe_en_el_catastro(mundo):
    g, reg, pub = mundo["g"], mundo["reg"], mundo["pub"]
    assert len(g.preparar(T)) == 4 and g.preparar(T) == []
    r = g.evaluar_zona(T, g.zona(T, "Z01"))
    assert r["evaluacion"]["nivel"] == "bajo" and r["acciones"] == []
    ca = reg.leer(T, M.urn("ClimateAssessment", T, "Z01"))
    assert M.v(ca, "riskLevel") == "bajo" and M.v(ca, "method") == "en15757" and M.v(ca, "dataOrigin") == "sintetico"
    assert len(M.v(ca, "targetHumidity")) == 2
    ev = pub.de("conservacion.evaluada")[0]
    assert ev["subject"] == M.urn("HeritageZone", T, "Z01") and ev["data"]["evaluacion"] == ca["id"]
    assert g.estado_zona(T, "Z01")["evaluacion"]["banda"]


def test_una_desviacion_abre_la_alerta_con_sus_legajos_y_se_cierra_con_firma(mundo, tmp_path):
    g, reg, pub = mundo["g"], mundo["reg"], mundo["pub"]
    g.preparar(T)
    r = g.simular(T, "Z02", "desviacion", 8)
    assert r["evaluacion"]["nivel"] == "alto" and r["acciones"] == ["abierta Z02-1"]
    aid = M.urn("ConservationAlert", T, "Z02-1")
    a = reg.leer(T, aid)
    assert M.v(a, "alertStatus") == "activa" and M.v(a, "severity") == "critical"
    assert M.v(a, "refAssessment") == M.urn("ClimateAssessment", T, "Z02")
    abierta = pub.de("conservacion.riesgo")[0]
    assert abierta["data"]["estado"] == "abierta" and abierta["data"]["legajos"] == [mundo["legajo"]]

    # otra evaluación con el mismo nivel no abre otra
    assert g.evaluar_zona(T, g.zona(T, "Z02"))["acciones"] == []
    # firmas: reconocer y cerrar (la causa es obligatoria en la API; aquí, directo)
    g.firmas.reconocer(T, aid, "conservador-test")
    with pytest.raises(Conflicto):
        g.firmas.reconocer(T, aid, "otra")
    g.firmas.cerrar(T, aid, "conservador-test", "Fuga localizada y reparada")
    a = reg.leer(T, aid)
    assert M.v(a, "alertStatus") == "cerrada" and M.v(a, "closedBy") == "conservador-test"
    with pytest.raises(Conflicto):
        g.firmas.cerrar(T, aid, "x", "otra vez")
    assert [e["data"]["estado"] for e in pub.de("conservacion.riesgo")] == ["abierta", "reconocida", "cerrada"]

    # el notario lleva el libro de la zona, de la alerta y del legajo afectado
    libro = Libro(str(tmp_path / "prov.ttl"))
    for e in pub.ev:
        libro.anotar(e)
    tipos = [x["tipo"] for x in libro.actas(aid)]
    assert tipos == ["alerta-zona-abierta", "alerta-zona-reconocida", "alerta-zona-cerrada"]
    assert "Fuga localizada" in libro.actas(aid)[-1]["detalle"]
    assert "alerta-zona-cerrada" in [x["tipo"] for x in libro.actas(mundo["legajo"])]

    # una nueva desviación abre otra alerta (la 2)
    assert g.simular(T, "Z02", "desviacion", 8)["acciones"] == ["abierta Z02-2"]


def test_agravar_y_proponer_el_cierre(mundo):
    g, reg, reloj = mundo["g"], mundo["reg"], mundo["reloj"]
    g.preparar(T)
    assert g.simular(T, "Z04", "desviacion", 3)["evaluacion"]["nivel"] == "medio"
    assert g.simular(T, "Z04", "fluctuacion", 1)["acciones"] == ["agravada Z04-1"]
    aid = M.urn("ConservationAlert", T, "Z04-1")
    assert M.v(reg.leer(T, aid), "riskLevel") == "alto"
    g.simular(T, "Z04", "estable", 30)                    # vuelve a su clima
    assert M.v(reg.leer(T, aid), "lowSince")
    reloj["ahora"] = AHORA + timedelta(days=8)
    g.series.guardar_muchas(T, M.urn("HeritageZone", T, "Z04"), [])
    acciones = g.simular(T, "Z04", "estable", 30)["acciones"]
    assert acciones == ["propuesto cerrar Z04-1"] and M.v(reg.leer(T, aid), "closureProposed") is True
    assert M.v(reg.leer(T, aid), "alertStatus") == "activa"     # proponer no cierra: cierra una persona


def test_evaluar_todo_recorre_las_instituciones_con_gemelo(mundo):
    g = mundo["g"]
    g.series.anadir_tenant(T)
    r = g.evaluar_todo()
    assert r["zonas"] == 4 and r["errores"] == []


# ---------- API del servicio (la usa el producto en la consola) ----------
def test_api_del_gemelo(mundo):
    g = mundo["g"]
    c = TestClient(crear_app(Vigilante(mundo["reg"], mundo["pub"]), gemelo=g, firmas=g.firmas))
    assert c.post("/gemelo/preparar", json={"tenant": T}).json()["evaluadas"]
    resumen = {z["codigo"]: z for z in c.get("/gemelo/resumen", params={"tenant": T}).json()}
    assert set(resumen) == {"Z01", "Z02", "Z03", "Z04"} and resumen["Z01"]["nivel"] == "bajo"
    zona = c.get("/gemelo/zonas/Z01", params={"tenant": T}).json()
    assert len(zona["serie"]) >= 7 * 24 and zona["evaluacion"]["humedad"]["objetivo"]
    assert c.get("/gemelo/zonas/Z99", params={"tenant": T}).status_code == 404
    assert c.post("/gemelo/zonas/Z02/simular", json={"tenant": T, "perfil": "magia"}).status_code == 422
    r = c.post("/gemelo/zonas/Z02/simular", json={"tenant": T, "perfil": "desviacion", "dias": 8}).json()
    aid = M.urn("ConservationAlert", T, "Z02-1")
    assert r["acciones"] == ["abierta Z02-1"]
    assert c.get("/gemelo/resumen", params={"tenant": T}).json()[1]["alerta"]["codigo"] == "Z02-1"
    otra = M.urn("ConservationAlert", "otro-archivo", "Z02-1")
    assert c.post("/gemelo/alertas/cerrar", json={"tenant": T, "alerta": otra, "por": "x", "causa": "abc"}).status_code == 422
    assert c.post("/gemelo/alertas/cerrar", json={"tenant": T, "alerta": aid, "por": "x"}).status_code == 422
    assert c.post("/gemelo/alertas/cerrar", json={"tenant": T, "alerta": aid, "por": "x", "causa": "Reparada"}).status_code == 200
    assert c.post("/gemelo/alertas/cerrar", json={"tenant": T, "alerta": aid, "por": "x", "causa": "Reparada"}).status_code == 409
    assert c.post("/gemelo/alertas/reconocer",
                  json={"tenant": T, "alerta": M.urn("ConservationAlert", T, "Z01-9"), "por": "x"}).status_code == 404
    assert c.get("/salud").json()["gemelo"]["series"] == "local"


# ---------- el producto en la consola, con conservación y sensores de verdad (en memoria) ----------
def test_el_producto_en_la_consola_con_sus_roles(monkeypatch):
    import productos.gemelo as producto
    from sdk.identidad import Identidad, NoAutorizado
    from services.panel.app import COOKIE, crear_app as consola
    from services.sensores.app import Simulador, crear_app as app_sensores

    reg, pub = Catastro(), Pub()
    g = GemeloPatrimonial(registro=reg, series=SeriesLocal(), publicador=pub, capacidad=lambda t, s, p: evaluar(s, p))
    g.firmas = FirmasDirectas(g)
    apps = {"conservacion": TestClient(crear_app(Vigilante(reg, pub), gemelo=g, firmas=g.firmas)),
            "sensores": TestClient(app_sensores(Simulador(reg, {}), patrimonial=SimuladorPatrimonial(reg)))}

    def peticion(metodo, url, json=None, params=None, timeout=None):
        host, ruta = url.split("//", 1)[1].split("/", 1)
        return apps[host].request(metodo, "/" + ruta, json=json, params=params)
    monkeypatch.setattr(producto.httpx, "request", peticion)

    class Verif:
        P = {"tok-a": Identidad("m.ortega", T, ["archivera", "admin-institucion"]),
             "tok-c": Identidad("conservador-test", T, ["conservador"]),
             "tok-t": Identidad("tecnico-test", T, ["tecnico"]),
             "tok-p": Identidad("paleografa-test", T, ["paleografa"])}

        def verificar(self, t):
            if t not in self.P:
                raise NoAutorizado(401, "no")
            return self.P[t]

    app = consola(registro=reg, verificador=Verif(), expedientes=None, keycloak_interno="http://kc",
                  procedencia="http://127.0.0.1:9", api_publico="http://srv:9080", enlaces={},
                  servicios={"conservacion": "http://conservacion", "sensores": "http://sensores",
                             "catalogo": "http://127.0.0.1:9", "instituciones": "http://127.0.0.1:9"})

    def como(tok):
        c = TestClient(app)
        c.cookies.set(COOKIE, tok)
        return c
    a, c, t, p = como("tok-a"), como("tok-c"), como("tok-t"), como("tok-p")
    B = "/panel/productos/gemelo"

    assert c.get(f"{B}/api/inmueble").json()["edificio"] is None          # aún sin inmueble
    assert t.post(f"{B}/api/semilla").status_code == 403
    r = a.post(f"{B}/api/semilla").json()
    assert r["creadas"] == 20 and r["sensores"] == 6 and len(r["evaluadas"]) == 4
    for vista in ("", "/zona?z=Z01", "/mapa", "/alertas", "/configuracion", "/depositos", "/cajas"):
        assert c.get(B + vista).status_code == 200, vista
    d = c.get(f"{B}/api/inmueble").json()
    assert d["kpis"]["zonas"] == 4 and d["kpis"]["enRiesgo"] == 0 and d["zonas"][0]["nivel"] == "bajo"
    assert p.get(f"{B}/api/inmueble").status_code == 403                  # la paleógrafa no tiene el gemelo

    # demo: una fuga en el sótano (8 días) → alerta alta con su evaluación
    assert t.post(f"{B}/api/simular", json={"zona": "Z02", "perfil": "desviacion"}).status_code == 403
    r = a.post(f"{B}/api/simular", json={"zona": "Z02", "perfil": "desviacion", "dias": 8}).json()
    assert r["evaluacion"]["nivel"] == "alto" and r["acciones"] == ["abierta Z02-1"]
    assert {x["zona"]: x["perfil"] for x in c.get(f"{B}/api/perfiles").json()}["Z02"] == "desviacion"
    d = c.get(f"{B}/api/inmueble").json()
    assert d["zonas"][0]["codigo"] == "Z02" and d["kpis"]["alertas"] == 1 and d["kpis"]["criticas"] == 1
    z = c.get(f"{B}/api/zonas/Z02").json()
    assert z["evaluacion"]["nivel"] == "alto" and len(z["serie"]) >= 160 and z["alertas"][0]["codigo"] == "Z02-1"
    assert len(c.get(f"{B}/api/sensores").json()) == 6
    assert c.get(f"{B}/api/zonas/Z99").status_code == 404

    # firmas: el técnico no; conservación sí, y con causa
    assert t.post(f"{B}/api/alertas/Z02-1/reconocer").status_code == 403
    assert c.post(f"{B}/api/alertas/Z02-1/reconocer").json()["por"] == "conservador-test"
    assert c.post(f"{B}/api/alertas/Z02-1/cerrar", json={"causa": ""}).status_code == 422
    assert c.post(f"{B}/api/alertas/Z02-1/cerrar", json={"causa": "Fuga reparada"}).status_code == 200
    assert c.get(f"{B}/api/alertas").json() == []
    cerrada = c.get(f"{B}/api/alertas?estado=todas").json()[0]
    assert (cerrada["estado"], cerrada["cerradaPor"], cerrada["causaCierre"]) == ("cerrada", "conservador-test", "Fuga reparada")
    assert [e["data"]["estado"] for e in pub.de("conservacion.riesgo")] == ["abierta", "reconocida", "cerrada"]

    # configuración: una zona y un sensor nuevos
    assert a.post(f"{B}/api/zonas", json={"codigo": "Z05", "nombre": "Sacristía", "tipo": "sala", "humedad": 60}).status_code == 200
    assert a.post(f"{B}/api/zonas", json={"codigo": "Z05", "nombre": "x"}).status_code == 409
    assert a.post(f"{B}/api/sensores", json={"codigo": "S07", "zona": "Z05", "nombre": "Sacristía"}).status_code == 200
    assert len(c.get(f"{B}/api/sensores").json()) == 7

    # la API pública (/api/v1/gemelo/… por la puerta) entra con el token, sin cookie
    api = TestClient(app)
    assert api.get(f"{B}/api/inmueble", headers={"Authorization": "Bearer tok-t"}).json()["kpis"]["zonas"] == 5
    assert api.post(f"{B}/api/ingesta/observacion", headers={"Authorization": "Bearer tok-a"},
                    json={"sensor": "S07", "temperatura": 19.5, "humedad": 61, "observadoEn": "2026-11-16T10:00:00Z"}).status_code == 200
    assert M.v(reg.leer(T, M.urn("IndoorEnvironmentObserved", T, "S07")), "relativeHumidity") == 61
    assert api.post(f"{B}/api/ingesta/observacion", headers={"Authorization": "Bearer tok-c"},
                    json={"sensor": "S07", "temperatura": 19.5, "humedad": 61, "observadoEn": "x"}).status_code == 403

    # el vocabulario, público
    ctx = TestClient(app).get("/contexts/v1/gdp.jsonld")
    assert ctx.status_code == 200 and "HeritageZone" in ctx.json()["@context"]
    assert TestClient(app).get("/contexts/v1/nada.jsonld").status_code == 404
