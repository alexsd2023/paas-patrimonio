"""Lo poco que el servicio de instituciones necesita de la API de administración de Keycloak.

Se autentica como el cliente confidencial «paas-gestion» (client credentials), cuyo usuario de servicio
tiene los roles de realm-management justos: usuarios, grupos y clientes del realm «paas». Nunca usa
la cuenta de administrador de Keycloak.
"""
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx


class ErrorKeycloak(RuntimeError):
    def __init__(self, codigo: int, detalle: str):
        super().__init__(f"Keycloak respondió {codigo}: {detalle}")
        self.codigo = codigo


class KeycloakAdmin:
    def __init__(self, url: str, secreto: str, realm: str = "paas", cliente: str = "paas-gestion",
                 http: Optional[httpx.Client] = None):
        self.url, self.realm, self.cliente, self.secreto = url.rstrip("/"), realm, cliente, secreto
        self.http = http or httpx.Client(timeout=15)
        self._token, self._caduca = None, 0.0

    # ---------- transporte ----------
    def _tok(self) -> str:
        if self._token and time.monotonic() < self._caduca - 30:
            return self._token
        r = self.http.post(f"{self.url}/realms/{self.realm}/protocol/openid-connect/token",
                           data={"grant_type": "client_credentials", "client_id": self.cliente,
                                 "client_secret": self.secreto})
        if r.status_code != 200:
            raise ErrorKeycloak(r.status_code, f"el cliente {self.cliente} no obtiene token: {r.text[:200]}")
        d = r.json()
        self._token, self._caduca = d["access_token"], time.monotonic() + d.get("expires_in", 60)
        return self._token

    def _req(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        r = self.http.request(metodo, f"{self.url}/admin/realms/{self.realm}{ruta}",
                              headers={"Authorization": f"Bearer {self._tok()}"}, **kw)
        if r.status_code >= 400:
            raise ErrorKeycloak(r.status_code, r.text[:300])
        return r

    @staticmethod
    def _id_creado(r: httpx.Response) -> str:
        return r.headers["location"].rstrip("/").rsplit("/", 1)[-1]

    # ---------- grupos (= instituciones) ----------
    def grupo(self, nombre: str) -> Optional[Dict[str, Any]]:
        r = self._req("GET", "/groups", params={"search": nombre, "exact": "true", "briefRepresentation": "false"})
        return next((g for g in r.json() if g["name"] == nombre), None)

    def grupos(self) -> List[Dict[str, Any]]:
        return self._req("GET", "/groups", params={"briefRepresentation": "false", "max": 1000}).json()

    def crear_grupo(self, nombre: str, atributos: Dict[str, List[str]]) -> str:
        return self._id_creado(self._req("POST", "/groups", json={"name": nombre, "attributes": atributos}))

    def miembros(self, gid: str) -> List[Dict[str, Any]]:
        return self._req("GET", f"/groups/{gid}/members", params={"briefRepresentation": "false", "max": 1000}).json()

    def borrar_grupo(self, gid: str) -> None:
        self._req("DELETE", f"/groups/{gid}")

    # ---------- usuarios ----------
    def usuario_por_nombre(self, nombre: str) -> Optional[Dict[str, Any]]:
        r = self._req("GET", "/users", params={"username": nombre, "exact": "true"})
        return next((u for u in r.json() if u["username"] == nombre.lower()), None)

    def usuario(self, uid: str) -> Dict[str, Any]:
        return self._req("GET", f"/users/{uid}").json()

    def grupos_de(self, uid: str) -> List[str]:
        return [g["name"] for g in self._req("GET", f"/users/{uid}/groups").json()]

    def crear_usuario(self, nombre: str, clave: str, email: Optional[str] = None, nombre_visible: str = "") -> str:
        cuerpo = {"username": nombre, "enabled": True, "emailVerified": bool(email),
                  "credentials": [{"type": "password", "value": clave, "temporary": False}]}
        if email:
            cuerpo["email"] = email
        # Keycloak 26 exige perfil completo (email, nombre y apellidos) para poder entrar
        partes = (nombre_visible.strip() or nombre).split(" ", 1)
        cuerpo["firstName"], cuerpo["lastName"] = partes[0], (partes[1] if len(partes) > 1 else partes[0])
        return self._id_creado(self._req("POST", "/users", json=cuerpo))

    def borrar_usuario(self, uid: str) -> None:
        self._req("DELETE", f"/users/{uid}")

    def poner_en_grupo(self, uid: str, gid: str) -> None:
        self._req("PUT", f"/users/{uid}/groups/{gid}")

    def activar(self, uid: str, activo: bool) -> None:
        self._req("PUT", f"/users/{uid}", json={"enabled": activo})

    def poner_clave(self, uid: str, clave: str) -> None:
        self._req("PUT", f"/users/{uid}/reset-password", json={"type": "password", "value": clave, "temporary": False})

    # ---------- roles del realm ----------
    def roles_de(self, uid: str) -> List[str]:
        return [x["name"] for x in self._req("GET", f"/users/{uid}/role-mappings/realm").json()]

    def _roles(self, nombres: List[str]) -> List[Dict[str, Any]]:
        return [self._req("GET", f"/roles/{urllib.parse.quote(n)}").json() for n in nombres]

    def dar_roles(self, uid: str, nombres: List[str]) -> None:
        if nombres:
            self._req("POST", f"/users/{uid}/role-mappings/realm", json=self._roles(nombres))

    def quitar_roles(self, uid: str, nombres: List[str]) -> None:
        if nombres:
            self._req("DELETE", f"/users/{uid}/role-mappings/realm", json=self._roles(nombres))

    # ---------- clientes (credenciales de API de una institución) ----------
    def crear_cliente_app(self, client_id: str, nombre: str) -> str:
        """Cliente confidencial solo para client credentials, con el claim «tenant» como paas-cli."""
        cuerpo = {"clientId": client_id, "name": nombre, "enabled": True, "publicClient": False,
                  "serviceAccountsEnabled": True, "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
                  "protocolMappers": [{"name": "tenant", "protocol": "openid-connect",
                                       "protocolMapper": "oidc-group-membership-mapper",
                                       "config": {"claim.name": "tenant", "full.path": "false", "id.token.claim": "true",
                                                  "access.token.claim": "true", "userinfo.token.claim": "true"}}]}
        return self._id_creado(self._req("POST", "/clients", json=cuerpo))

    def cliente_por_id(self, client_id: str) -> Optional[Dict[str, Any]]:
        r = self._req("GET", "/clients", params={"clientId": client_id})
        return next(iter(r.json()), None)

    def secreto_de(self, cid: str) -> str:
        return self._req("GET", f"/clients/{cid}/client-secret").json()["value"]

    def usuario_de_servicio(self, cid: str) -> Dict[str, Any]:
        return self._req("GET", f"/clients/{cid}/service-account-user").json()

    def borrar_cliente(self, cid: str) -> None:
        self._req("DELETE", f"/clients/{cid}")
