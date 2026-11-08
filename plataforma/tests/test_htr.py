"""El taller de copistas: lo que inscribe y lo que envía cumple los contratos."""
import pytest

from sdk.contratos import validar
from sdk.registro import urn_transcripcion
from services.htr.app import preparar

ACTIVO = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"


def test_copia_pendiente_con_modelo_y_carta_valida():
    ficha, carta = preparar(ACTIVO, "archivo-villanueva")
    assert ficha["id"] == urn_transcripcion(ACTIVO) == "urn:ngsi-ld:Transcripcion:archivo-villanueva:TEST-001-t1"
    assert ficha["estado"]["value"] == "pendiente-validacion"
    assert ficha["deActivo"]["object"] == ACTIVO
    validar(carta)
    assert carta["data"]["modelo"] == ficha["modelo"]["value"]


def test_misma_copia_misma_carta():
    assert preparar(ACTIVO, "archivo-villanueva")[1]["id"] == preparar(ACTIVO, "archivo-villanueva")[1]["id"]


def test_no_transcribe_legajos_de_otro_tenant():
    with pytest.raises(ValueError):
        preparar(ACTIVO, "otro-archivo")
