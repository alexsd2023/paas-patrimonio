"""El pasaporte público: identidad, procedencia, derechos y uso por IA, y la verificación (sin red)."""
import base64
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentimestamps.core.notary import PendingAttestation
from opentimestamps.core.timestamp import Timestamp

from capacidades.certificacion_documental import motor, proveedores
from capacidades.certificacion_documental.proveedores.blockchain_ots import BlockchainOTS
from capacidades.certificacion_documental.proveedores.nom151_simulado import Nom151Simulado
from services.panel import pasaporte as PP

A = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"
T = "urn:ngsi-ld:Transcripcion:archivo-villanueva:TEST-001-t1"
TEXTO = "En la villa de Veracruz, a 3 de mayo de 1622 años,\r\nel maestre del navío…  "
P = lambda v: {"type": "Property", "value": v}  # noqa: E731


class Cal:
    def __call__(self, url):
        return self

    def submit(self, msg, timeout=None):
        t = Timestamp(msg)
        t.attestations.add(PendingAttestation("https://cal.prueba"))
        return t


class Catastro:
    def __init__(self, ents):
        self.e = {x["id"]: x for x in ents}

    def leer(self, tenant, i):
        x = self.e.get(i)
        return x if x and i.split(":")[3] == tenant else None


ACTAS = [{"tipo": "ingreso", "tiempo": "2026-11-19T10:00:00Z", "agentes": ["urn:paas:usuario:archivo-villanueva:m.ortega"]},
         {"tipo": "htr", "tiempo": "2026-11-19T10:01:00Z", "agentes": ["urn:paas:modelo:htr-mock@0.1"], "detalle": "modelo htr-mock@0.1"},
         {"tipo": "validacion", "tiempo": "2026-11-19T11:00:00Z", "agentes": ["urn:paas:usuario:archivo-villanueva:paleografa-test"]},
         {"tipo": "certificacion", "tiempo": "2026-11-19T11:00:05Z",
          "agentes": ["https://paas-patrimonio.example/agentes/tenants/x/servicios/procesos",
                      "urn:paas:capacidad:certificacion-documental@0.1.0"], "detalle": "huella …"}]


def cliente(texto_publico=False, certificada=True, texto=TEXTO):
    proveedores.registrar("blockchain", lambda: BlockchainOTS(calendarios=["https://cal"], calendario=Cal(),
                                                              explorador=None))
    proveedores.registrar("nom151", lambda: Nom151Simulado(clave="k"))
    ev = motor.certificar(TEXTO, ["blockchain", "nom151"])
    trans = {"id": T, "type": "Transcripcion", "deActivo": {"type": "Relationship", "object": A},
             "estado": P("validada"), "modelo": P("htr-mock@0.1"), "texto": P(texto)}
    if certificada:
        trans["evidencia"] = P(json.dumps(ev))
    cat = Catastro([trans, {"id": A, "type": "ActivoPatrimonial", "signatura": P("TEST-001"), "ark": P("ark:/99999/x")}])
    app = FastAPI()
    PP.montar(app, registro=cat, actas=lambda a: ACTAS if a == A else [], verificar=motor.verificar,
              texto_publico=texto_publico)
    return TestClient(app), ev


def test_los_cuatro_pilares_y_la_verificacion():
    c, ev = cliente()
    d = c.get(f"/pasaporte/api/{T}").json()
    assert d["signatura"] == "TEST-001" and d["institucion"] == "archivo-villanueva"
    assert d["identidad"]["huella"] == ev["huella"] and d["identidad"]["certificacion"] == "pendiente"
    assert all("prueba" not in a for a in d["identidad"]["anclajes"])              # las pruebas, aparte
    assert [a["modo"] for a in d["identidad"]["anclajes"]] == ["real", "simulado"]
    assert d["derechos"]["estado"] == d["usoIA"]["estado"] == "sin-declarar"
    assert d["verificacion"]["integro"] is True
    # el libro, sin nombres de usuario
    libro = d["procedencia"]["libro"]
    assert [a["nombre"] for a in libro][-1] == "Certificación"
    plano = json.dumps(libro, ensure_ascii=False)
    assert "m.ortega" not in plano and "paleografa-test" not in plano and "una persona de la institución" in plano
    assert "certificacion-documental@0.1.0" in libro[-1]["agentes"]
    assert c.get(f"/pasaporte/{T}").status_code == 200


def test_si_cambia_el_texto_en_el_catastro_sale_alterado():
    c, _ = cliente(texto=TEXTO.replace("maestre", "maestro"))
    v = c.get(f"/pasaporte/api/{T}").json()["verificacion"]
    assert v["integro"] is False and v["resumen"].startswith("ALTERADO")


def test_verificar_un_texto_pegado():
    c, _ = cliente()
    assert c.post(f"/pasaporte/api/{T}/verificar", json={"texto": TEXTO.strip()}).json()["integro"]
    assert not c.post(f"/pasaporte/api/{T}/verificar", json={"texto": "otro texto"}).json()["integro"]
    assert c.post(f"/pasaporte/api/{T}/verificar", json={}).status_code == 422


def test_descargas_para_verificar_sin_la_plataforma():
    c, ev = cliente(texto_publico=True)
    ds = c.get(f"/pasaporte/api/{T}").json()["descargas"]
    assert set(ds) == {"evidencia", "ots", "texto"}
    ots = c.get(ds["ots"]).content
    assert ots == base64.b64decode(ev["anclajes"][0]["prueba"])
    texto = c.get(ds["texto"]).content
    assert motor.huella(texto.decode()).hex() == ev["huella"]                    # el archivo da la misma huella
    assert json.loads(c.get(ds["evidencia"]).content)["huella"] == ev["huella"]


def test_el_texto_no_se_publica_por_defecto():
    c, _ = cliente()
    assert "texto" not in c.get(f"/pasaporte/api/{T}").json()["descargas"]
    assert c.get(f"/pasaporte/{T}/texto.txt").status_code == 404


def test_sin_certificar_y_urn_ajenas():
    c, _ = cliente(certificada=False)
    d = c.get(f"/pasaporte/api/{T}").json()
    assert d["identidad"] == {"certificacion": "sin-certificar"} and d["verificacion"] is None and d["descargas"] == {}
    assert c.post(f"/pasaporte/api/{T}/verificar", json={"texto": "x"}).status_code == 409
    assert c.get(f"/pasaporte/api/{A}").status_code == 404                     # por ahora, solo transcripciones
    assert c.get("/pasaporte/api/urn:ngsi-ld:Transcripcion:otro-archivo:TEST-001-t1").status_code == 404


def test_insignias_en_la_ficha_del_legajo():
    from productos.legajo import _certificacion
    assert _certificacion({"id": T, "texto": P(TEXTO)}) is None
    _, ev = cliente()
    c = _certificacion({"id": T, "evidencia": P(json.dumps(ev))})
    assert c["estado"] == "pendiente" and c["pasaporte"] == f"/pasaporte/{T}"
    assert [a["proveedor"] for a in c["anclajes"]] == ["blockchain", "nom151"] and "prueba" not in c["anclajes"][0]
