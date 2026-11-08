"""Identidad (regla ID del contrato): verificar el token de Keycloak y saber quién llama.

El token dice tres cosas que usan los servicios:
    usuario  → preferred_username          (m.ortega, paleografa-test…)
    tenant   → claim «tenant»              (la institución; hoy, el grupo de Keycloak)
    roles    → realm_access.roles          (archivera, paleografa…)

APISIX ya comprueba el token en la puerta; los servicios lo vuelven a comprobar
(firma, caducidad y emisor) para que nadie pueda saltarse la puerta llamándolos directamente.
"""
import json
import urllib.parse
import urllib.request
from typing import List, NamedTuple, Optional


class Identidad(NamedTuple):
    usuario: str
    tenant: str
    roles: List[str]

    def tiene(self, rol: str) -> bool:
        return rol in self.roles


class NoAutorizado(Exception):
    def __init__(self, codigo: int, motivo: str):
        super().__init__(motivo)
        self.codigo, self.motivo = codigo, motivo


def token_de(authorization: Optional[str], x_access_token: Optional[str] = None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_access_token:  # APISIX lo añade también en esta cabecera
        return x_access_token.strip()
    raise NoAutorizado(401, "falta el token (Authorization: Bearer …)")


def identidad_de_claims(claims: dict) -> Identidad:
    tenants = claims.get("tenant") or []
    if isinstance(tenants, str):
        tenants = [tenants]
    tenants = [t.strip("/") for t in tenants]
    if len(tenants) != 1:
        raise NoAutorizado(403, f"el usuario debe pertenecer a una sola institución (tiene {tenants})")
    usuario = claims.get("preferred_username")
    if not usuario:
        raise NoAutorizado(401, "el token no trae preferred_username")
    return Identidad(usuario, tenants[0], list(claims.get("realm_access", {}).get("roles", [])))


class Verificador:
    def __init__(self, jwks_url: str, emisor: str):
        import jwt
        self._jwt = jwt
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True)
        self.emisor = emisor

    def verificar(self, token: str) -> Identidad:
        try:
            clave = self._jwks.get_signing_key_from_jwt(token).key
            claims = self._jwt.decode(token, clave, algorithms=["RS256"], issuer=self.emisor,
                                      options={"verify_aud": False})
        except self._jwt.PyJWTError as e:
            raise NoAutorizado(401, f"token no válido: {e}")
        return identidad_de_claims(claims)


def pedir_token(keycloak_url: str, usuario: str, clave: str, realm: str = "paas", cliente: str = "paas-cli") -> str:
    """Para scripts y tests: token con usuario y contraseña (flujo password del cliente paas-cli)."""
    datos = urllib.parse.urlencode({"grant_type": "password", "client_id": cliente,
                                    "username": usuario, "password": clave}).encode()
    url = f"{keycloak_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=datos, method="POST"), timeout=15) as r:
        return json.loads(r.read())["access_token"]
