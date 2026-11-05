"""Tests sin red de procedencia y gestoría:  python -m pytest tests"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.gestoria.app import Expedientes
from services.gestoria.app import crear_app as app_gestoria
from services.procedencia.app import Registro
from services.procedencia.app import crear_app as app_procedencia

EJ = Path(__file__).resolve().parents[1] / "contracts" / "ejemplos"
ACTIVO = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"
ingreso = json.loads((EJ / "legajo.ingestado.json").read_text(encoding="utf-8"))
htr = json.loads((EJ / "htr.completado.json").read_text(encoding="utf-8"))


def test_notario_levanta_acta_de_ingreso_y_copia(tmp_path):
    reg = Registro(str(tmp_path / "prov.ttl"))
    assert reg.anotar(ingreso) and reg.anotar(htr)
    actas = TestClient(app_procedencia(reg)).get("/actas", params={"activo": ACTIVO}).json()
    assert [a["tipo"] for a in actas] == ["ingreso", "htr"]
    assert "urn:paas:usuario:archivo-villanueva:m.ortega" in actas[0]["agentes"]
    assert "urn:paas:modelo:htr-mock@0.1" in actas[1]["agentes"]


def test_notario_no_duplica_y_recuerda_tras_reiniciar(tmp_path):
    ruta = str(tmp_path / "prov.ttl")
    reg = Registro(ruta)
    reg.anotar(ingreso)
    assert reg.anotar(ingreso) is False          # carta repetida
    assert Registro(ruta).anotar(ingreso) is False  # tras reiniciar, sigue constando
    assert len(Registro(ruta).actas(ACTIVO)) == 1


def test_gestoria_abre_un_solo_expediente(tmp_path):
    exp = Expedientes(str(tmp_path / "g.db"))
    assert exp.abrir(ingreso) is True
    assert exp.abrir(ingreso) is False           # carta repetida
    assert exp.abrir(htr) is False               # no es su carta
    r = TestClient(app_gestoria(exp)).get("/expedientes", params={"activo": ACTIVO}).json()
    assert len(r) == 1 and r[0]["estado"] == "abierto" and r[0]["id"] == f"transcripcion:{ACTIVO}"
