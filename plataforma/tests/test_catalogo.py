"""Catálogo de servicios y flujos: plantilla, tipos, recetas, máquina, adaptador del NER (sin red)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from sdk.identidad import Identidad, NoAutorizado
from sdk.servicios import DocumentoInvalido, ManifiestoInvalido, cargar, crear_servicio, encaja, leer_manifiesto, linaje
from services.catalogo.catalogo import Catalogo, SinPermiso, descubrir
from services.catalogo.maquina import FirmaNoValida, Maquina
from services.catalogo.recetas import RecetaInvalida, planificar
from capacidades.modernizador_demo.app import procesar as modernizar
from capacidades.ner_historico import adaptador as ner

TEXTO = "Registraron Baltasar Perez y Ernando de Sanctiago vesinos de Sevilla\nEn la villa de Villanueva a diez de março"


# ---------- tipos y plantilla ----------
def test_los_tipos_encajan_por_linaje():
    assert linaje("transcripcion-anotada") == ["transcripcion-anotada", "transcripcion", "texto"]
    assert encaja("texto-modernizado", "transcripcion") and encaja("transcripcion-anotada", "texto")
    assert not encaja("texto", "transcripcion") and not encaja("respuesta", "texto")


def test_los_servicios_del_repositorio_se_cargan():
    s = descubrir()
    assert set(s) >= {"ner-historico", "modernizador-demo"}
    assert s["ner-historico"].modo == "externo" and s["modernizador-demo"].url == "http://srv-modernizador-demo:8080"


def test_un_manifiesto_mal_escrito_dice_que_falta():
    with pytest.raises(ManifiestoInvalido) as e:
        leer_manifiesto({"id": "Mal", "tipo": "otro", "entrada": "pdf", "salida": "texto", "version": "1",
                         "modo": "externo", "acceso": ["todos"]})
    for trozo in ("id:", "falta nombre", "tipo:", "entrada:", "version", "url", "acceso"):
        assert trozo in str(e.value)


def test_servicio_interno_con_la_interfaz_estandar():
    m = cargar("capacidades/modernizador_demo")
    c = TestClient(crear_servicio(m, modernizar))
    assert c.get("/describir").json()["salida"] == "texto-modernizado"
    assert c.post("/trabajos", json={"entrada": {"sin": "texto"}}).status_code == 422
    assert c.post("/trabajos", json={"entrada": {"texto": "x"}, "parametros": {"otro": 1}}).status_code == 422
    tid = c.post("/trabajos", json={"entrada": {"texto": "a diez de março de mill"}}).json()["id"]
    import time
    for _ in range(50):
        t = c.get(f"/trabajos/{tid}").json()
        if t["estado"] == "terminado":
            break
        time.sleep(0.02)
    assert t["salida"]["texto"] == "a diez de marzo de mil" and len(t["salida"]["cambios"]) == 2


# ---------- adaptador del NER (respuesta como la documenta su API) ----------
RESP_NER = [{"Anotacion": "Registraron Baltasar Perez y Ernando de Sanctiago vesinos de Sevilla",
             "entities": [{"start": 12, "end": 26, "entity": "Persona", "fields": ["Nombre", "Hombre"]},
                          {"start": 61, "end": 68, "entity": "Localización", "fields": ["Topónimo"]}]},
            {"Anotacion": "En la villa de Villanueva a diez de março",
             "entities": [{"start": 15, "end": 25, "entity": "Localización", "fields": ["Topónimo"]}]}]


def test_el_ner_pasa_posiciones_de_linea_a_texto():
    ents = ner.normalizar(RESP_NER, TEXTO)
    assert [(e["tipo"], e["texto"]) for e in ents] == [("Persona", "Baltasar Perez"), ("Localización", "Sevilla"),
                                                       ("Localización", "Villanueva")]
    for e in ents:
        assert TEXTO[e["inicio"]:e["fin"]] == e["texto"]
    assert ents[0]["rasgos"] == ["Nombre", "Hombre"]


def _cliente_ner(capturas):
    def responder(req: httpx.Request):
        capturas.append(req)
        if req.headers.get("authorization") != "Bearer secreto":
            return httpx.Response(401, json={"detail": "token"})
        return httpx.Response(200, json=RESP_NER)
    return httpx.Client(transport=httpx.MockTransport(responder))


def test_el_catalogo_ejecuta_el_ner_externo(monkeypatch):
    monkeypatch.setenv("NER_TOKEN", "secreto")
    capturas = []
    cat = Catalogo(descubrir(), http=_cliente_ner(capturas))
    r = cat.ejecutar("ner-historico", {"texto": TEXTO, "activo": "urn:x"}, {"modelo": "toponyms", "etiquetas": ["Localización"]},
                     tenant="archivo-villanueva", roles=["archivera"])
    assert [e["texto"] for e in r["salida"]["entidades"]] == ["Sevilla", "Villanueva"]
    assert r["version"] == "1.3.0" and r["salida"]["activo"] == "urn:x"
    req = capturas[0]
    assert req.url.path == "/annotate/text" and req.url.params["model"] == "toponyms"
    assert json.loads(req.content) == {"text": TEXTO}
    with pytest.raises(DocumentoInvalido):  # parámetro fuera de los valores permitidos
        cat.ejecutar("ner-historico", {"texto": "x"}, {"modelo": "otro"}, tenant="t", roles=[])


def test_sin_token_el_ner_avisa(monkeypatch):
    monkeypatch.delenv("NER_TOKEN", raising=False)
    from services.catalogo.catalogo import FalloDelServicio
    with pytest.raises(FalloDelServicio, match="NER_TOKEN"):
        Catalogo(descubrir(), http=_cliente_ner([])).ejecutar("ner-historico", {"texto": "x"}, {}, tenant="t", roles=[])


def test_cuota_y_acceso():
    s = descubrir()
    s["ner-historico"].cuota = {"trabajos_dia": 1}
    s["modernizador-demo"].acceso = ["rol:paleografa"]
    cat = Catalogo(s)
    cat.contador.usar("t", s["ner-historico"])
    from services.catalogo.catalogo import CuotaAgotada
    with pytest.raises(CuotaAgotada):
        cat.contador.usar("t", s["ner-historico"])
    cat.contador.usar("otra", s["ner-historico"])  # la cuota es por institución
    with pytest.raises(SinPermiso):
        cat.comprobar("modernizador-demo", ["archivera"], "t")
    assert "modernizador-demo" not in [m.id for m in cat.visibles(["archivera"], "t")]
    assert "modernizador-demo" in [m.id for m in cat.visibles(["paleografa"], "t")]


# ---------- recetas ----------
RECETA = {"nombre": "Modernizar y anotar", "entrada": "transcripcion", "publicar": True,
          "pasos": [{"servicio": "modernizador-demo"}, {"firma": "paleografa"},
                    {"servicio": "ner-historico", "parametros": {"modelo": "toponyms"}}, {"firma": "paleografa"}]}


def test_una_receta_valida_fija_versiones_y_tipos():
    plan = planificar(RECETA, Catalogo(descubrir()), roles=["archivera"], tenant="t")
    assert plan["salida"] == "transcripcion-anotada"
    assert [(p["clase"], p.get("version")) for p in plan["pasos"]] == [
        ("servicio", "0.1.0"), ("firma", None), ("servicio", "1.3.0"), ("firma", None)]
    assert plan["pasos"][2]["recibe"] == "texto-modernizado" and plan["pasos"][2]["parametros"]["modelo"] == "toponyms"


def test_una_receta_mal_hecha_dice_todo_lo_que_falla():
    mala = {"nombre": "", "entrada": "texto", "publicar": True,
            "pasos": [{"servicio": "ner-historico"}, {"servicio": "no-existe"}, {"firma": ""}, {"nada": 1}]}
    with pytest.raises(RecetaInvalida) as e:
        planificar(mala, Catalogo(descubrir()), roles=[], tenant="t")
    msg = " | ".join(e.value.errores)
    for trozo in ("falta nombre", "necesita transcripcion y le llega texto", "no-existe", "firma necesita el rol",
                  "paso 4", "firmar después del último servicio"):
        assert trozo in msg


# ---------- máquina del flujo ----------
def _flujo():
    plan = planificar(RECETA, Catalogo(descubrir()), roles=["archivera"], tenant="t")
    return {"id": "abc", "tenant": "t", "usuario": "m.ortega", "roles": ["archivera"], "plan": plan, "entrada": {}}


def test_la_maquina_recorre_servicios_y_firmas():
    m = Maquina(_flujo())
    m.con_documento({"texto": "de março"})
    m.empieza("t0")
    m.servicio_hecho({"salida": {"texto": "de marzo", "original": "de março"}, "version": "0.1.0", "ms": 5}, "t1")
    assert m.e["tipo"] == "texto-modernizado"
    m.empieza("t2")
    assert m.e["estado"] == "esperando-firma"
    assert m.puede_firmar("m.ortega", ["archivera"]) == "esta firma es de una persona con rol paleografa"
    with pytest.raises(FirmaNoValida):
        m.firma("m.ortega", ["archivera"], "aprueba", "", "t3")
    m.firma("paleografa-test", ["paleografa"], "aprueba", "bien", "t3")
    assert m.e["estado"] == "en-curso" and m.actual()["servicio"] == "ner-historico"
    m.empieza("t4")
    m.servicio_hecho({"salida": {"texto": "de marzo", "entidades": []}, "version": "1.3.0"}, "t5")
    m.empieza("t6")
    m.firma("paleografa-test", ["paleografa"], "aprueba", "", "t7")
    assert m.actual() is None
    m.termina("urn:ngsi-ld:ResultadoFlujo:t:abc", "t8")
    assert m.procedencia() == {"servicios": [{"servicio": "modernizador-demo", "version": "0.1.0"},
                                             {"servicio": "ner-historico", "version": "1.3.0"}],
                               "firmas": [{"rol": "paleografa", "usuario": "paleografa-test"}] * 2}


def test_un_rechazo_para_el_flujo():
    m = Maquina(_flujo())
    m.empieza("t0")
    m.servicio_hecho({"salida": {"texto": "x", "original": "x"}}, "t1")
    m.empieza("t2")
    m.firma("p", ["paleografa"], "rechaza", "la grafía no es correcta", "t3")
    assert m.e["estado"] == "rechazado" and m.pasos[1]["comentario"] == "la grafía no es correcta"


# ---------- API del catálogo ----------
class Verif:
    P = {"tok-o": Identidad("m.ortega", "archivo-villanueva", ["archivera"]),
         "tok-p": Identidad("paleografa-test", "archivo-villanueva", ["paleografa"]),
         "tok-x": Identidad("p.otro", "otro-archivo", ["paleografa"])}

    def verificar(self, t):
        if t not in self.P:
            raise NoAutorizado(401, "no")
        return self.P[t]


class FlujosFalsos:
    def __init__(self):
        self.lanzados, self.firmas, self.estados = {}, [], {}

    def lanzar(self, flujo):
        m = Maquina(flujo)
        m.con_documento({"texto": "x"})
        m.empieza("t0")
        m.servicio_hecho({"salida": {"texto": "x", "original": "x"}}, "t1")
        m.empieza("t2")
        self.estados[flujo["id"]] = m.e
        self.lanzados[flujo["id"]] = flujo

    def estado(self, fid):
        return self.estados[fid]

    def firmar(self, fid, firma):
        self.firmas.append((fid, firma))


def _api(tmp_path):
    from services.catalogo.app import Indice, crear_app
    fl = FlujosFalsos()
    app = crear_app(verificador=Verif(), catalogo=Catalogo(descubrir()), flujos=fl,
                    indice=Indice(str(tmp_path / "f.db")))
    return TestClient(app), fl


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def test_api_catalogo_y_plantillas(tmp_path):
    c, _ = _api(tmp_path)
    assert c.get("/servicios").status_code == 401
    ids = [s["id"] for s in c.get("/servicios", headers=_h("tok-o")).json()]
    assert "ner-historico" in ids and "modernizador-demo" in ids
    plantillas = c.get("/plantillas", headers=_h("tok-o")).json()
    assert {p["id"] for p in plantillas} >= {"modernizar-y-anotar", "entidades-de-una-transcripcion"}
    for p in plantillas:  # las plantillas del repositorio son recetas válidas
        assert c.post("/flujos/validar", json={"receta": p["receta"]}, headers=_h("tok-o")).status_code == 200


def test_api_flujo_firmas_y_aislamiento(tmp_path):
    c, fl = _api(tmp_path)
    r = c.post("/flujos", json={"receta": RECETA, "entrada": {"activo": "urn:ngsi-ld:ActivoPatrimonial:otro-archivo:X"}},
               headers=_h("tok-o"))
    assert r.status_code == 403
    fid = c.post("/flujos", json={"receta": RECETA, "entrada": {"documento": {"texto": "x"}}}, headers=_h("tok-o")).json()["id"]
    assert [f["id"] for f in c.get("/flujos", headers=_h("tok-o")).json()] == [fid]
    assert c.get(f"/flujos/{fid}", headers=_h("tok-x")).status_code == 404  # otra institución
    assert c.get(f"/flujos/{fid}", headers=_h("tok-o")).json()["estado"] == "esperando-firma"
    assert c.post(f"/flujos/{fid}/firmar", json={"decision": "aprueba"}, headers=_h("tok-o")).status_code == 409
    ok = c.post(f"/flujos/{fid}/firmar", json={"decision": "aprueba", "comentario": "bien"}, headers=_h("tok-p"))
    assert ok.json()["firmadoPor"] == "paleografa-test"
    assert fl.firmas[0][1]["usuario"] == "paleografa-test" and fl.firmas[0][1]["roles"] == ["paleografa"]
