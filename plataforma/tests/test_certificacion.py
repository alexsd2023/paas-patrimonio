"""Capacidad certificacion-documental: huella, los tres anclajes y la verificación.

Sin red: OpenTimestamps con un calendario falso y eIDAS con una TSA local de OpenSSL (el token es
un RFC 3161 de verdad, así que se prueba el mismo análisis que con FreeTSA o un prestador cualificado).
"""
import shutil
import subprocess
import time

import pytest
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.timestamp import Timestamp

from capacidades.certificacion_documental import motor, proveedores
from capacidades.certificacion_documental.proveedores.blockchain_ots import BlockchainOTS
from capacidades.certificacion_documental.proveedores.eidas_rfc3161 import EidasRFC3161
from capacidades.certificacion_documental.proveedores.nom151_simulado import Nom151Simulado
from sdk.servicios import validar_documento

TEXTO = "En la villa de Veracruz, a 3 de mayo de 1622 años,\r\nel maestre del navío Nuestra Señora de la Concepción…  "


# ---------- dobles ----------

class Calendario:
    """Acepta huellas y, cuando `minado`, las devuelve ancladas en un bloque."""
    def __init__(self, altura=925000):
        self.altura, self.minado, self.raices = altura, False, []

    def __call__(self, url):
        self.url = url
        return self

    def submit(self, msg, timeout=None):
        t = Timestamp(msg)
        t.attestations.add(PendingAttestation("https://cal.prueba"))
        return t

    def get_timestamp(self, msg, timeout=None):
        if not self.minado:
            raise KeyError("aún no está en un bloque")
        t = Timestamp(msg)
        hoja = t.ops.add(OpSHA256())
        hoja.attestations.add(BitcoinBlockHeaderAttestation(self.altura))
        self.raices.append(hoja.msg)
        return t

    def explorador(self, altura):
        assert altura == self.altura
        return {"merkle_root": self.raices[-1][::-1].hex(), "timestamp": 1763540000}


@pytest.fixture(scope="module")
def tsa(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("sin openssl")
    d = tmp_path_factory.mktemp("tsa")
    run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True)  # noqa: E731
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "tsa.key", "-out", "tsa.crt",
        "-days", "30", "-subj", "/CN=TSA de prueba", "-addext", "extendedKeyUsage=critical,timeStamping",
        "-addext", "basicConstraints=CA:FALSE")
    (d / "serial").write_text("01\n")
    (d / "tsa.cnf").write_text(
        "[ tsa ]\ndefault_tsa = t\n[ t ]\nserial = ./serial\ncrypto_device = builtin\nsigner_cert = ./tsa.crt\n"
        "signer_key = ./tsa.key\nsigner_digest = sha256\ndefault_policy = 1.2.3.4.1\ndigests = sha256\n"
        "accuracy = secs:1\nordering = yes\ntsa_name = no\ness_cert_id_chain = no\ness_cert_id_alg = sha256\n")

    def sellar(digest: bytes) -> bytes:
        run("openssl", "ts", "-query", "-digest", digest.hex(), "-sha256", "-cert", "-out", "q.tsq")
        run("openssl", "ts", "-reply", "-config", "tsa.cnf", "-queryfile", "q.tsq", "-token_out", "-out", "t.der")
        return (d / "t.der").read_bytes()
    return sellar


@pytest.fixture
def cal(tsa):
    c = Calendario()
    proveedores.registrar("blockchain", lambda: BlockchainOTS(calendarios=["https://cal.prueba"], calendario=c,
                                                               explorador=c.explorador))
    proveedores.registrar("eidas", lambda: EidasRFC3161(sellar=tsa))
    proveedores.registrar("nom151", lambda: Nom151Simulado(clave="clave-de-prueba"))
    return c


# ---------- huella ----------

def test_misma_huella_para_el_mismo_texto():
    unix = "Señora de la Concepción\nmaestre"
    assert motor.huella(unix) == motor.huella("  Señora de la Concepción\r\nmaestre \n")      # CRLF y espacios
    nfd = "Señora de la Concepción\nmaestre"                                       # tildes descompuestas
    assert motor.huella(unix) == motor.huella(nfd)
    assert motor.huella(unix) != motor.huella(unix.replace("maestre", "maestra"))


# ---------- los tres anclajes ----------

def test_certificar_con_los_tres_anclajes(cal):
    ev = validar_documento("evidencia", motor.certificar(TEXTO, ["blockchain", "eidas", "nom151"]))
    por = {a["proveedor"]: a for a in ev["anclajes"]}
    assert por["blockchain"]["estado"] == "pendiente" and por["blockchain"]["modo"] == "real"
    assert por["eidas"]["estado"] == "confirmado" and por["eidas"]["modo"] == "demo"
    assert por["eidas"]["valorLegal"] == "ninguno"
    assert por["nom151"]["modo"] == "simulado" and "SIMULADA" in por["nom151"]["detalle"]
    v = motor.verificar(TEXTO, ev)
    assert v["integro"] and all(a["valido"] for a in v["anclajes"]), v


def test_actualizar_confirma_en_bitcoin(cal):
    ev = motor.certificar(TEXTO, ["blockchain"])
    assert motor.actualizar(TEXTO, ev)["anclajes"][0]["estado"] == "pendiente"   # aún sin bloque
    cal.minado = True
    ev2 = validar_documento("evidencia", motor.actualizar(TEXTO, ev))
    a = ev2["anclajes"][0]
    assert a["estado"] == "confirmado" and a["bloque"] == 925000 and a["fecha"].startswith("2025-11-19")
    v = motor.verificar(TEXTO, ev2)
    assert v["integro"] and "bloque 925000" in v["anclajes"][0]["detalle"]
    with pytest.raises(ValueError):
        motor.actualizar(TEXTO + " (corregido)", ev)


def test_una_letra_cambiada_pone_en_rojo_los_tres(cal):
    ev = motor.certificar(TEXTO, ["blockchain", "eidas", "nom151"])
    v = motor.verificar(TEXTO.replace("maestre", "maestro"), ev)
    assert not v["integro"] and v["resumen"].startswith("ALTERADO")
    assert [a["valido"] for a in v["anclajes"]] == [False, False, False]


def test_un_proveedor_caido_no_tumba_a_los_demas(cal):
    def caido():
        raise RuntimeError("sin conexión con el PSC")
    proveedores.registrar("eidas", lambda: EidasRFC3161(sellar=lambda d: caido()))
    ev = validar_documento("evidencia", motor.certificar(TEXTO, ["eidas", "nom151"]))
    assert [a["estado"] for a in ev["anclajes"]] == ["error", "confirmado"]
    proveedores.registrar("nom151", lambda: Nom151Simulado(clave="x"))
    proveedores.registrar("eidas", lambda: EidasRFC3161(sellar=lambda d: caido()))
    with pytest.raises(RuntimeError):
        motor.certificar(TEXTO, ["eidas"])


def test_constancia_simulada_manipulada(cal):
    import base64, json
    ev = motor.certificar(TEXTO, ["nom151"])
    c = json.loads(base64.b64decode(ev["anclajes"][0]["prueba"]))
    c["fecha"] = "2020-01-01T00:00:00Z"                      # alguien retrocede la fecha
    ev["anclajes"][0]["prueba"] = base64.b64encode(json.dumps(c).encode()).decode()
    assert not motor.verificar(TEXTO, ev)["anclajes"][0]["valido"]


# ---------- la capacidad por su interfaz ----------

def test_capacidad_por_api(cal):
    from fastapi.testclient import TestClient
    from capacidades.certificacion_documental.app import MANIFIESTO, app
    assert MANIFIESTO.publico()["entrada_texto"] is True        # el panel ofrece un cuadro de texto
    c = TestClient(app)
    assert {a["proveedor"] for a in c.get("/anclajes").json()} == {"blockchain", "eidas", "nom151"}

    def trabajo(cuerpo):
        tid = c.post("/trabajos", json=cuerpo).json()["id"]
        for _ in range(100):
            t = c.get(f"/trabajos/{tid}").json()
            if t["estado"] in ("terminado", "error"):
                return t
            time.sleep(0.05)
        raise AssertionError("el trabajo no terminó")

    t = trabajo({"entrada": {"texto": TEXTO}, "parametros": {"anclajes": ["blockchain", "nom151"]}})
    assert t["estado"] == "terminado", t
    ev = t["salida"]
    cal.minado = True
    t2 = trabajo({"entrada": {"texto": TEXTO, "evidencia": ev}, "parametros": {"operacion": "actualizar"}})
    assert t2["salida"]["anclajes"][0]["estado"] == "confirmado"
    assert c.post("/verificar", json={"texto": TEXTO, "evidencia": t2["salida"]}).json()["integro"]
    assert not c.post("/verificar", json={"texto": "otro", "evidencia": ev}).json()["integro"]
    assert c.post("/verificar", json={"texto": TEXTO, "evidencia": {"huella": "x"}}).status_code == 422
    assert c.post("/trabajos", json={"entrada": {"texto": TEXTO},
                                     "parametros": {"anclajes": ["ethereum"]}}).status_code == 422
