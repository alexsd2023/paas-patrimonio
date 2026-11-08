"""Cliente mínimo del registro canónico (Scorpio, NGSI-LD).

Cada llamada lleva su tenant en la cabecera NGSILD-Tenant: Scorpio guarda cada
institución en su propia base de datos y una no ve las entidades de otra.
Solo usa la biblioteca estándar, para que cualquier módulo pueda importarlo.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

ENTIDADES = "/ngsi-ld/v1/entities"
SUSCRIPCIONES = "/ngsi-ld/v1/subscriptions"


def urn_activo(tenant: str, signatura: str) -> str:
    return f"urn:ngsi-ld:ActivoPatrimonial:{tenant}:{signatura}"


def entidad_activo(tenant: str, *, signatura: str, ark: str, manifiesto: str,
                   imagenes: int, ingestado_por: str) -> Dict[str, Any]:
    """La ficha del legajo tal como se inscribe en el catastro (formato normalizado NGSI-LD)."""
    prop = lambda v: {"type": "Property", "value": v}  # noqa: E731
    return {
        "id": urn_activo(tenant, signatura),
        "type": "ActivoPatrimonial",
        "signatura": prop(signatura),
        "ark": prop(ark),
        "manifiesto": prop(manifiesto),
        "imagenes": prop(imagenes),
        "ingestadoPor": prop(ingestado_por),
    }


class Registro:
    def __init__(self, url: str, timeout: float = 10.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    def _req(self, metodo: str, ruta: str, tenant: Optional[str], cuerpo: Any = None) -> Tuple[int, Any]:
        cab = {"Accept": "application/json"}
        if tenant:
            cab["NGSILD-Tenant"] = tenant
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode()
            cab["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + ruta, data=datos, method=metodo, headers=cab)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                texto = r.read().decode() or "null"
                return r.status, json.loads(texto) if texto.strip()[:1] in "[{n" else texto
        except urllib.error.HTTPError as e:
            texto = e.read().decode()
            try:
                return e.code, json.loads(texto)
            except ValueError:
                return e.code, texto

    def disponible(self) -> bool:
        try:
            return self._req("GET", "/ngsi-ld/v1/types", None)[0] == 200
        except OSError:
            return False

    def crear(self, tenant: str, entidad: Dict[str, Any]) -> int:
        return self._req("POST", ENTIDADES, tenant, entidad)[0]

    def leer(self, tenant: str, entidad_id: str) -> Optional[Dict[str, Any]]:
        estado, cuerpo = self._req("GET", f"{ENTIDADES}/{urllib.parse.quote(entidad_id, safe='')}", tenant)
        return cuerpo if estado == 200 else None

    def borrar(self, tenant: str, entidad_id: str) -> int:
        return self._req("DELETE", f"{ENTIDADES}/{urllib.parse.quote(entidad_id, safe='')}", tenant)[0]

    def suscripcion(self, tenant: str, sub_id: str) -> Optional[Dict[str, Any]]:
        estado, cuerpo = self._req("GET", f"{SUSCRIPCIONES}/{urllib.parse.quote(sub_id, safe='')}", tenant)
        return cuerpo if estado == 200 else None

    def crear_suscripcion(self, tenant: str, sub: Dict[str, Any]) -> Tuple[int, Any]:
        return self._req("POST", SUSCRIPCIONES, tenant, sub)
