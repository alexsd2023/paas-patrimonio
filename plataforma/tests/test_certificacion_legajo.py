"""Parte 2 de la certificación: el proceso de transcripción certifica la copia validada.

Sin red ni servicios: la capacidad, el catastro y el bus son dobles. Se prueba la actividad `_certificar`
(el flujo de Temporal, con sus reintentos, está en test_flujo.py).
"""
import pytest

from capacidades.certificacion_documental import motor, proveedores
from capacidades.certificacion_documental.proveedores.nom151_simulado import Nom151Simulado
from sdk.contratos import validar
from services.procesos import actividades as act

ACTIVO = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"
TRANS = "urn:ngsi-ld:Transcripcion:archivo-villanueva:TEST-001-t1"
D = {"tenant": "archivo-villanueva", "activo": ACTIVO, "transcripcion": TRANS}


class Catastro:
    def __init__(self, texto="En la villa de Veracruz, a 3 de mayo de 1622…"):
        self.ent = {"id": TRANS, "texto": {"type": "Property", "value": texto}}

    def leer(self, tenant, eid):
        return self.ent if eid == TRANS else None

    def anadir_atributos(self, tenant, eid, attrs):
        self.ent.update(attrs)
        return 204


class Bus:
    def __init__(self):
        self.cartas = []

    def publicar(self, ev):
        self.cartas.append(validar(ev))


class Capacidad:
    """Llama al motor de la capacidad de verdad (sin catálogo), como haría el catálogo."""
    def __init__(self):
        self.llamadas = 0
        proveedores.registrar("nom151", lambda: Nom151Simulado(clave="k"))

    def __call__(self, tenant, entrada, parametros):
        self.llamadas += 1
        return motor.certificar(entrada["texto"], parametros["anclajes"])


@pytest.fixture(autouse=True)
def activada(monkeypatch):
    monkeypatch.setenv("CERTIFICAR", "si")
    monkeypatch.setenv("CERTIFICAR_ANCLAJES", "nom151")


def test_certifica_guarda_la_evidencia_y_publica():
    cat, bus, cap = Catastro(), Bus(), Capacidad()
    r = act._certificar(D, ejecutar=cap, registro=cat, publicador=bus)
    assert r["certificacion"] == "confirmada" and cap.llamadas == 1
    ev = act.leer_evidencia(cat.ent)
    assert isinstance(cat.ent["evidencia"]["value"], str)
    assert cat.ent["huella"]["value"] == ev["huella"] == motor.huella(cat.ent["texto"]["value"]).hex()
    assert cat.ent["certificacion"]["value"] == "confirmada"
    (carta,) = bus.cartas
    assert carta["type"] == "evidencia.anclada" and carta["subject"] == TRANS
    assert carta["data"]["anclajes"] == [{"proveedor": "nom151", "modo": "simulado", "estado": "confirmado"}]
    # la evidencia guardada sigue verificando el texto del catastro
    assert motor.verificar(cat.ent["texto"]["value"], ev)["integro"]


def test_es_idempotente_si_temporal_repite_la_actividad():
    cat, bus, cap = Catastro(), Bus(), Capacidad()
    act._certificar(D, ejecutar=cap, registro=cat, publicador=bus)
    act._certificar(D, ejecutar=cap, registro=cat, publicador=bus)
    assert cap.llamadas == 1                                   # no certifica dos veces
    assert bus.cartas[0]["id"] == bus.cartas[1]["id"]         # mismo id: los consumidores ven el duplicado


def test_desactivada_no_hace_nada(monkeypatch):
    monkeypatch.setenv("CERTIFICAR", "no")
    cat, bus, cap = Catastro(), Bus(), Capacidad()
    assert act._certificar(D, ejecutar=cap, registro=cat, publicador=bus) == {"certificacion": "desactivada"}
    assert cap.llamadas == 0 and not bus.cartas and "evidencia" not in cat.ent


def test_sin_texto_en_el_catastro_falla_para_que_temporal_reintente():
    cat = Catastro()
    del cat.ent["texto"]
    with pytest.raises(RuntimeError):
        act._certificar(D, ejecutar=Capacidad(), registro=cat, publicador=Bus())


def test_estado_de_la_certificacion():
    e = lambda *xs: {"anclajes": [{"estado": x} for x in xs]}  # noqa: E731
    assert act.estado_certificacion(e("pendiente", "confirmado")) == "pendiente"
    assert act.estado_certificacion(e("confirmado", "error")) == "confirmada"
    assert act.estado_certificacion(e("error")) == "error"
