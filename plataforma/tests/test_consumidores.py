"""Tests sin red de procedencia y gestoría:  python -m pytest tests"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.gestoria.app import FueraDeTurno, NoEncontrado
from services.gestoria.app import crear_app as app_gestoria
from services.procedencia.app import Registro
from services.procedencia.app import crear_app as app_procedencia

EJ = Path(__file__).resolve().parents[1] / "contracts" / "ejemplos"
ACTIVO = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"
cargar = lambda n: json.loads((EJ / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
ingreso, htr, validada = cargar("legajo.ingestado"), cargar("htr.completado"), cargar("transcripcion.validada")


def test_notario_levanta_las_tres_actas(tmp_path):
    reg = Registro(str(tmp_path / "prov.ttl"))
    assert reg.anotar(ingreso) and reg.anotar(htr) and reg.anotar(validada)
    actas = TestClient(app_procedencia(reg)).get("/actas", params={"activo": ACTIVO}).json()
    assert [a["tipo"] for a in actas] == ["ingreso", "htr", "validacion"]
    assert "urn:paas:usuario:archivo-villanueva:m.ortega" in actas[0]["agentes"]
    assert "urn:paas:modelo:htr-mock@0.1" in actas[1]["agentes"]
    assert "urn:paas:usuario:archivo-villanueva:paleografa-test" in actas[2]["agentes"]


def test_notario_no_duplica_y_recuerda_tras_reiniciar(tmp_path):
    ruta = str(tmp_path / "prov.ttl")
    reg = Registro(ruta)
    reg.anotar(ingreso)
    assert reg.anotar(ingreso) is False
    assert Registro(ruta).anotar(ingreso) is False
    assert len(Registro(ruta).actas(ACTIVO)) == 1


class ExpedientesFalsos:
    """Sustituye a Temporal: mismo comportamiento visible."""

    def __init__(self):
        self.procesos = {}

    def abrir(self, ev):
        if ev["type"] != "legajo.ingestado" or ev["subject"] in self.procesos:
            return False
        self.procesos[ev["subject"]] = {"estado": "pendiente-validacion", "validadoPor": None}
        return True

    def listar(self, activo):
        p = self.procesos.get(activo)
        return [{"id": f"transcripcion:{activo}", "activo": activo, **p}] if p else []

    def validar(self, activo, por):
        p = self.procesos.get(activo)
        if not p:
            raise NoEncontrado(activo)
        if p["estado"] != "pendiente-validacion":
            raise FueraDeTurno(p["estado"])
        p.update(estado="completado", validadoPor=por)
        return {"activo": activo, "validadoPor": por, "estado": "validacion-recibida"}


def test_gestoria_un_proceso_por_legajo_y_validacion():
    exp = ExpedientesFalsos()
    assert exp.abrir(ingreso) is True and exp.abrir(ingreso) is False and exp.abrir(htr) is False
    c = TestClient(app_gestoria(exp))
    assert c.get("/expedientes", params={"activo": ACTIVO}).json()[0]["estado"] == "pendiente-validacion"
    assert c.post("/expedientes/validar", json={"activo": ACTIVO, "por": "paleografa-test"}).status_code == 200
    assert c.post("/expedientes/validar", json={"activo": ACTIVO, "por": "otra"}).status_code == 409
    assert c.post("/expedientes/validar", json={"activo": ACTIVO + "X", "por": "p"}).status_code == 404
