"""Tests sin red de la librería de eventos:  python -m pytest tests"""
import json
from pathlib import Path

import pytest

from sdk.contratos import ContratoInvalido
from sdk.eventos import a_kafka, de_kafka, nuevo_evento

EJ = Path(__file__).resolve().parents[1] / "contracts" / "ejemplos"


@pytest.mark.parametrize("nombre", ["legajo.ingestado", "htr.completado", "transcripcion.validada"])
def test_ida_y_vuelta_por_kafka(nombre):
    ev = json.loads((EJ / f"{nombre}.json").read_text(encoding="utf-8"))
    topic, clave, valor, cab = a_kafka(ev)
    assert clave == ev["subject"].encode()
    assert ("ce_tenant", b"archivo-villanueva") in cab
    assert de_kafka(valor, cab) == ev


def test_topic_segun_tipo():
    ev = json.loads((EJ / "htr.completado.json").read_text(encoding="utf-8"))
    assert a_kafka(ev)[0] == "htr"


def test_nuevo_evento_es_valido():
    ev = nuevo_evento("legajo.ingestado", tenant="archivo-villanueva",
                      subject="urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001",
                      source="/tenants/archivo-villanueva/servicios/puente",
                      data={"signatura": "TEST-001", "ark": "ark:/99999/av-test-001",
                            "manifiesto": "https://iiif.local/iiif/3/archivo-villanueva/TEST-001/manifest",
                            "imagenes": 3, "ingestadoPor": "m.ortega"})
    assert ev["time"].endswith("Z")


def test_no_se_envia_un_evento_invalido():
    ev = json.loads((EJ / "invalidos" / "legajo.ingestado.sin-tenant.json").read_text(encoding="utf-8"))
    with pytest.raises(ContratoInvalido):
        a_kafka(ev)


def test_se_ignora_lo_que_no_es_cloudevent():
    # como los mensajes de prueba de la parte 1
    with pytest.raises(ContratoInvalido):
        de_kafka(b'{"tipo":"prueba"}', [("ce_tenant", b"archivo-villanueva")])
