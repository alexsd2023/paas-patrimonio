"""Lo que se inscribe en el catastro debe producir una carta válida al pasar por el puente."""
from sdk.contratos import validar
from sdk.registro import entidad_activo, urn_activo
from services.puente.app import a_evento
from services.suscripciones.crear import suscripcion


def ficha():
    return entidad_activo("archivo-villanueva", signatura="TEST-001", ark="ark:/99999/av-test-001",
                          manifiesto="https://iiif.local/iiif/3/archivo-villanueva/TEST-001/manifest",
                          imagenes=3, ingestado_por="m.ortega")


def test_ficha_del_catastro_produce_legajo_ingestado_valido():
    ev = validar(a_evento(ficha(), "archivo-villanueva"))
    assert ev["subject"] == urn_activo("archivo-villanueva", "TEST-001")
    assert ev["data"]["ingestadoPor"] == "m.ortega"


def test_tipo_expandido_tambien_se_reconoce():
    f = ficha()
    f["type"] = "https://uri.etsi.org/ngsi-ld/default-context/ActivoPatrimonial"
    assert a_evento(f, "archivo-villanueva")["type"] == "legajo.ingestado"


def test_suscripcion_apunta_al_puente_de_su_tenant():
    s = suscripcion("otro-archivo")
    assert s["notification"]["endpoint"]["uri"].endswith("/ngsi-ld/notificaciones/otro-archivo")
    assert s["entities"] == [{"type": "ActivoPatrimonial"}]
