"""Tests sin red del puente (Kafka sustituido por un publicador falso):  python -m pytest tests"""
import pytest
from fastapi.testclient import TestClient

from sdk.contratos import validar
from services.puente.app import crear_app

URL = "/ngsi-ld/notificaciones/archivo-villanueva"


class PublicadorFalso:
    def __init__(self, falla=False):
        self.enviados, self.falla = [], falla

    def publicar(self, ev):
        if self.falla:
            raise RuntimeError("broker caído")
        self.enviados.append(ev)


def notificacion(**cambios):
    entidad = {
        "id": "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001",
        "type": "ActivoPatrimonial",
        "signatura": {"type": "Property", "value": "TEST-001"},
        "ark": {"type": "Property", "value": "ark:/99999/av-test-001"},
        "manifiesto": {"type": "Property", "value": "https://iiif.local/iiif/3/archivo-villanueva/TEST-001/manifest"},
        "imagenes": {"type": "Property", "value": 3},
        "ingestadoPor": {"type": "Property", "value": "m.ortega"},
    }
    entidad.update(cambios)
    return {"id": "urn:ngsi-ld:Notification:1", "type": "Notification",
            "subscriptionId": "urn:ngsi-ld:Subscription:puente", "data": [entidad]}


@pytest.fixture
def pub():
    return PublicadorFalso()


@pytest.fixture
def cliente(pub):
    return TestClient(crear_app(pub))


def test_activo_nuevo_produce_legajo_ingestado(cliente, pub):
    r = cliente.post(URL, json=notificacion())
    assert r.status_code == 200 and len(r.json()["publicados"]) == 1
    ev = validar(pub.enviados[0])
    assert ev["type"] == "legajo.ingestado" and ev["tenant"] == "archivo-villanueva"
    assert ev["data"]["imagenes"] == 3


def test_aviso_repetido_misma_carta(cliente):
    a = cliente.post(URL, json=notificacion()).json()["publicados"]
    b = cliente.post(URL, json=notificacion()).json()["publicados"]
    assert a == b


def test_formato_keyvalues(cliente, pub):
    r = cliente.post(URL, json=notificacion(signatura="TEST-001", imagenes=3))
    assert r.status_code == 200 and pub.enviados[0]["data"]["signatura"] == "TEST-001"


def test_otras_entidades_se_ignoran(cliente, pub):
    r = cliente.post(URL, json=notificacion(type="Anotacion"))
    assert r.json() == {"publicados": [], "ignorados": 1} and not pub.enviados


def test_tenant_cruzado_rechazado(cliente):
    r = cliente.post(URL, json=notificacion(), headers={"NGSILD-Tenant": "otro-archivo"})
    assert r.status_code == 400


def test_entidad_incompleta_422(cliente, pub):
    r = cliente.post(URL, json=notificacion(imagenes={"type": "Property", "value": 0}))
    assert r.status_code == 422 and not pub.enviados


def test_kafka_caido_503():
    r = TestClient(crear_app(PublicadorFalso(falla=True))).post(URL, json=notificacion())
    assert r.status_code == 503
