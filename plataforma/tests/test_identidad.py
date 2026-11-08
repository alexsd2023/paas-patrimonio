"""Leer la identidad de un token de Keycloak (sin red)."""
import pytest

from sdk.identidad import NoAutorizado, identidad_de_claims, token_de


def test_claims_de_keycloak():
    yo = identidad_de_claims({"preferred_username": "m.ortega", "tenant": ["archivo-villanueva"],
                              "realm_access": {"roles": ["archivera", "default-roles-paas"]}})
    assert yo.usuario == "m.ortega" and yo.tenant == "archivo-villanueva" and yo.tiene("archivera")


def test_tenant_con_ruta_de_grupo():
    assert identidad_de_claims({"preferred_username": "x", "tenant": ["/otro-archivo"]}).tenant == "otro-archivo"


@pytest.mark.parametrize("tenant", [[], ["a", "b"], None])
def test_una_sola_institucion(tenant):
    with pytest.raises(NoAutorizado) as e:
        identidad_de_claims({"preferred_username": "x", "tenant": tenant})
    assert e.value.codigo == 403


def test_token_de_cabeceras():
    assert token_de("Bearer abc") == "abc"
    assert token_de(None, "xyz") == "xyz"
    with pytest.raises(NoAutorizado):
        token_de(None, None)
