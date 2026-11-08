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


class VerificadorFalso:
    """Tokens de juguete: el texto del token dice quién eres."""
    from sdk.identidad import Identidad
    PERSONAS = {
        "tok-ortega": Identidad("m.ortega", "archivo-villanueva", ["archivera"]),
        "tok-paleo": Identidad("paleografa-test", "archivo-villanueva", ["paleografa"]),
        "tok-otro": Identidad("p.otro", "otro-archivo", ["paleografa"]),
    }

    def verificar(self, token):
        from sdk.identidad import NoAutorizado
        if token not in self.PERSONAS:
            raise NoAutorizado(401, "token no válido")
        return self.PERSONAS[token]


def _cab(t):
    return {"Authorization": f"Bearer {t}"}


def test_gestoria_un_proceso_por_legajo_y_firma_con_identidad():
    exp = ExpedientesFalsos()
    assert exp.abrir(ingreso) is True and exp.abrir(ingreso) is False and exp.abrir(htr) is False
    c = TestClient(app_gestoria(exp, verificador=VerificadorFalso()))
    assert c.get("/expedientes", params={"activo": ACTIVO}).status_code == 401           # sin token
    assert c.get("/expedientes", params={"activo": ACTIVO}, headers=_cab("tok-otro")).status_code == 403
    r = c.get("/expedientes", params={"activo": ACTIVO}, headers=_cab("tok-ortega"))
    assert r.json()[0]["estado"] == "pendiente-validacion"
    v = lambda t, a=ACTIVO: c.post("/expedientes/validar", json={"activo": a, "por": "quien-sea"}, headers=_cab(t))  # noqa: E731
    assert v("tok-ortega").status_code == 403      # no es paleógrafa
    assert v("tok-otro").status_code == 403        # otra institución
    assert v("tok-falso").status_code == 401
    r = v("tok-paleo")
    assert r.status_code == 200 and r.json()["validadoPor"] == "paleografa-test"  # firma el token, no el cuerpo
    assert v("tok-paleo").status_code == 409       # segunda firma
    assert v("tok-paleo", ACTIVO + "X").status_code == 404
    assert c.get("/yo", headers=_cab("tok-paleo")).json()["tenant"] == "archivo-villanueva"


def test_gestoria_sin_identidad_configurada_no_atiende():
    c = TestClient(app_gestoria(ExpedientesFalsos()))
    assert c.get("/yo", headers=_cab("tok-ortega")).status_code == 503
