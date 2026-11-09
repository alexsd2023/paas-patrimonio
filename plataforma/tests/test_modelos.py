"""Parte 12 · datos versionados y modelos registrados: la copia sabe de qué modelo y de qué datos sale."""
import sys
from pathlib import Path

import pytest

from sdk.contratos import validar
from services.htr.app import preparar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modelos" / "htr"))
import entrenar as E  # noqa: E402

ACTIVO = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"
RUN, DATOS = "e8f472ce4e3f4d2bb4edbf4021d8d21d", "9dea83d78b0b642464dce62b56466426"
MODELO = {"nombre": "htr-paleografico", "version": 3, "etiqueta": "htr-paleografico@3", "run": RUN, "datos": DATOS,
          "cer": 0.052, "artefacto": {"muestra": "En la villa de Villanueva, a diez días, ante mí el escriuano"}}


# ---------- métricas y entrenamiento (simulado) ----------
def test_cer_y_wer():
    assert E.distancia("março", "marzo") == 1
    assert E.cer(["março"], ["marzo"]) == pytest.approx(0.2)
    assert E.wer(["ante mí el escriuano"], ["ante mi el escriuano"]) == pytest.approx(0.25)
    assert E.cer(["abc"], ["abc"]) == 0


def test_la_evaluacion_es_siempre_la_misma_y_no_se_entrena_con_ella():
    lineas = E.leer_lineas(Path("datos/gt"))
    train, ev = E.partir(lineas)
    assert len(lineas) == 35 and len(ev) == 7 and not {id(x) for x in train} & {id(x) for x in ev}
    m = E.entrenar(train)
    assert E.evaluar(m, ev, 0.06) == E.evaluar(m, ev, 0.06)          # reproducible
    assert E.evaluar(m, ev, 0.0)["cer"] == 0                          # sin errores, CER 0
    assert E.evaluar(m, ev, 0.02)["cer"] < E.evaluar(m, ev, 0.10)["cer"]


def test_la_version_de_los_datos_sale_del_dvc(tmp_path):
    d = tmp_path / "gt"
    d.mkdir()
    (d / "lineas.jsonl").write_text('{"texto": "x"}\n')
    calculada, origen = E.version_datos(d)
    assert origen == "calculado" and len(calculada) == 32
    (tmp_path / "gt.dvc").write_text(f"outs:\n- md5: {DATOS}.dir\n  path: gt\n")
    assert E.version_datos(d) == (DATOS, "dvc")


# ---------- la copia cita su modelo ----------
def test_la_copia_y_la_carta_citan_modelo_run_y_datos():
    ficha, carta = preparar(ACTIVO, "archivo-villanueva", MODELO)
    validar(carta)
    assert carta["data"]["modelo"] == "htr-paleografico@3" == ficha["modelo"]["value"]
    assert carta["data"]["modeloRun"] == RUN == ficha["modeloRun"]["value"]
    assert carta["data"]["datosVersion"] == DATOS == ficha["datosVersion"]["value"]
    assert ficha["texto"]["value"].startswith("En la villa de Villanueva")


def test_sin_registro_sigue_el_modelo_fijo():
    ficha, carta = preparar(ACTIVO, "archivo-villanueva")
    validar(carta)
    assert carta["data"]["modelo"] == "htr-mock@0.1" and "modeloRun" not in carta["data"]


def test_el_acta_del_notario_cita_modelo_datos_y_run():
    from rdflib import URIRef
    from rdflib.namespace import PROV
    from services.procedencia.app import PAAS, tripletas
    _, carta = preparar(ACTIVO, "archivo-villanueva", MODELO)
    g = tripletas(carta)
    modelo = URIRef("urn:paas:modelo:htr-paleografico@3")
    assert (modelo, PROV.wasDerivedFrom, URIRef(f"urn:paas:datos:{DATOS}")) in g
    assert (modelo, PROV.wasGeneratedBy, URIRef(f"urn:paas:mlflow:run:{RUN}")) in g
    detalle = str(next(g.objects(predicate=PAAS.detalle)))
    assert detalle == f"modelo htr-paleografico@3 · datos {DATOS[:10]} · run {RUN[:8]} · CER 0.052"


# ---------- registro de modelos (MLflow local, sin servidor) ----------
def test_registrar_y_leer_el_modelo_en_produccion(tmp_path, monkeypatch):
    pytest.importorskip("sqlalchemy")
    from sdk.modelos import RegistroModelos
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.chdir(tmp_path)  # los artefactos locales caen aquí
    train, ev = E.partir(E.leer_lineas(Path(__file__).resolve().parents[1] / "datos" / "gt"))
    m = E.entrenar(train)
    etq = {"datos.version": DATOS, "datos.origen": "dvc", "git.commit": "abc", "simulado": "true"}
    v1 = E.registrar(uri, m, E.evaluar(m, ev, 0.06), {"tasa_error": 0.06}, etq, produccion=True)
    v2 = E.registrar(uri, m, E.evaluar(m, ev, 0.02), {"tasa_error": 0.02}, etq, produccion=False)
    assert (v1["version"], v2["version"]) == (1, 2)
    actual = RegistroModelos(uri, "htr-paleografico").actual()
    assert actual["etiqueta"] == "htr-paleografico@1" and actual["datos"] == DATOS and actual["run"] == v1["run"]
    assert actual["artefacto"]["tipo"] == "simulado"
    # cambiar el alias cambia el modelo que usa el taller, sin tocar el servicio
    E.registrar(uri, m, E.evaluar(m, ev, 0.02), {"tasa_error": 0.02}, etq, produccion=True)
    assert RegistroModelos(uri, "htr-paleografico").actual()["etiqueta"] == "htr-paleografico@3"


def test_sin_registro_no_rompe():
    from sdk.modelos import RegistroModelos
    assert RegistroModelos("http://127.0.0.1:9", "htr-paleografico", ttl=0).actual() is None


def test_el_legajo_enlaza_la_version_del_modelo_en_mlflow():
    from productos.legajo import _url_modelo
    assert _url_modelo("http://srv:5000", "htr-paleografico@3", RUN) == "http://srv:5000/#/models/htr-paleografico/versions/3"
    assert _url_modelo("http://srv:5000", "htr-mock@0.1", None) is None      # modelo fijo: no está en el registro
    assert _url_modelo(None, "htr-paleografico@3", RUN) is None              # sin MLFLOW_PUBLICO no hay enlace
