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


# ---------- parte 3: confirmación periódica ----------

from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation  # noqa: E402
from opentimestamps.core.op import OpSHA256  # noqa: E402
from opentimestamps.core.timestamp import Timestamp  # noqa: E402

from capacidades.certificacion_documental.proveedores.blockchain_ots import BlockchainOTS  # noqa: E402


class Calendario:
    def __init__(self):
        self.minado, self.raiz = False, None

    def __call__(self, url):
        return self

    def submit(self, msg, timeout=None):
        t = Timestamp(msg)
        t.attestations.add(PendingAttestation("https://cal.prueba"))
        return t

    def get_timestamp(self, msg, timeout=None):
        if not self.minado:
            raise KeyError("aún no")
        t = Timestamp(msg)
        hoja = t.ops.add(OpSHA256())
        hoja.attestations.add(BitcoinBlockHeaderAttestation(925001))
        self.raiz = hoja.msg
        return t


class CapacidadCompleta(Capacidad):
    def __call__(self, tenant, entrada, parametros):
        self.llamadas += 1
        if parametros.get("operacion") == "actualizar":
            return motor.actualizar(entrada["texto"], entrada["evidencia"])
        return motor.certificar(entrada["texto"], parametros["anclajes"])


@pytest.fixture
def cal(monkeypatch):
    monkeypatch.setenv("CERTIFICAR_ANCLAJES", "blockchain,nom151")
    c = Calendario()
    proveedores.registrar("blockchain", lambda: BlockchainOTS(
        calendarios=["https://cal.prueba"], calendario=c,
        explorador=lambda h: {"merkle_root": c.raiz[::-1].hex(), "timestamp": 1763580000}))
    return c


def test_confirmacion_publica_cuando_bitcoin_confirma(cal):
    cat, bus, cap = Catastro(), Bus(), CapacidadCompleta()
    assert act._certificar(D, ejecutar=cap, registro=cat, publicador=bus)["certificacion"] == "pendiente"
    assert act._confirmar(D, ejecutar=cap, registro=cat, publicador=bus)["certificacion"] == "pendiente"
    assert [c["type"] for c in bus.cartas] == ["evidencia.anclada"]          # sin bloque, nada nuevo
    cal.minado = True
    assert act._confirmar(D, ejecutar=cap, registro=cat, publicador=bus)["certificacion"] == "confirmada"
    assert cat.ent["certificacion"]["value"] == "confirmada"
    conf = [c for c in bus.cartas if c["type"] == "anclaje.confirmado"]
    assert len(conf) == 1 and conf[0]["data"]["proveedor"] == "blockchain" and conf[0]["data"]["bloque"] == 925001
    ev = act.leer_evidencia(cat.ent)
    assert motor.verificar(cat.ent["texto"]["value"], ev)["integro"]
    # otra vuelta: ya confirmada, no llama a la capacidad ni publica
    n, m = cap.llamadas, len(bus.cartas)
    assert act._confirmar(D, ejecutar=cap, registro=cat, publicador=bus)["certificacion"] == "confirmada"
    assert cap.llamadas == n and len(bus.cartas) == m


def test_confirmacion_certifica_si_al_validar_fallo(cal):
    cat, bus, cap = Catastro(), Bus(), CapacidadCompleta()
    r = act._confirmar(D, ejecutar=cap, registro=cat, publicador=bus)    # no había evidencia
    assert r["certificacion"] == "pendiente" and "evidencia" in cat.ent
    assert [c["type"] for c in bus.cartas] == ["evidencia.anclada"]
