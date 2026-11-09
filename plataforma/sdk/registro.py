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


def urn_deposito(tenant: str, codigo: str) -> str:
    return f"urn:ngsi-ld:Deposito:{tenant}:{codigo}"


def urn_caja(tenant: str, codigo: str) -> str:
    return f"urn:ngsi-ld:Caja:{tenant}:{codigo}"


def entidad_deposito(tenant: str, codigo: str, *, nombre: str, umbrales: Dict[str, float]) -> Dict[str, Any]:
    prop = lambda v: {"type": "Property", "value": v}  # noqa: E731
    return {"id": urn_deposito(tenant, codigo), "type": "Deposito", "nombre": prop(nombre),
            "estadoAmbiental": prop("ok"), **{k: prop(v) for k, v in umbrales.items()}}


def entidad_caja(tenant: str, codigo: str, deposito: str) -> Dict[str, Any]:
    return {"id": urn_caja(tenant, codigo), "type": "Caja", "nombre": {"type": "Property", "value": codigo},
            "enDeposito": {"type": "Relationship", "object": urn_deposito(tenant, deposito)}}


def entidad_activo(tenant: str, *, signatura: str, ark: str, manifiesto: str,
                   imagenes: int, ingestado_por: str, caja: Optional[str] = None,
                   traza: Optional[str] = None) -> Dict[str, Any]:
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
        **({"enCaja": {"type": "Relationship", "object": urn_caja(tenant, caja)}} if caja else {}),
        **({"traza": prop(traza)} if traza else {}),   # traceparent: el puente continúa la traza
    }


def urn_transcripcion(activo: str, n: int = 1) -> str:
    """urn:ngsi-ld:ActivoPatrimonial:<tenant>:<sig>  →  urn:ngsi-ld:Transcripcion:<tenant>:<sig>-t<n>"""
    _, _, _, tenant, sig = activo.split(":", 4)
    return f"urn:ngsi-ld:Transcripcion:{tenant}:{sig}-t{n}"


def entidad_transcripcion(activo: str, *, modelo: str, lineas: int, texto: str, confianza: float,
                          modelo_run: Optional[str] = None, datos_version: Optional[str] = None,
                          cer: Optional[float] = None) -> Dict[str, Any]:
    """La copia del taller. Con modelo_run y datos_version, la copia cita de qué modelo (run de MLflow)
    y de qué datos (versión DVC) sale: tramo 16 del caso."""
    prop = lambda v: {"type": "Property", "value": v}  # noqa: E731
    return {
        "id": urn_transcripcion(activo),
        "type": "Transcripcion",
        "deActivo": {"type": "Relationship", "object": activo},
        "estado": prop("pendiente-validacion"),
        "modelo": prop(modelo),
        "lineas": prop(lineas),
        "confianza": prop(confianza),
        "texto": prop(texto),
        **({"modeloRun": prop(modelo_run)} if modelo_run else {}),
        **({"datosVersion": prop(datos_version)} if datos_version else {}),
        **({"cerModelo": prop(cer)} if cer is not None else {}),
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

    def listar(self, tenant: str, tipo: str, limite: int = 200) -> list:
        """Entidades de un tipo, con createdAt/modifiedAt (options=sysAttrs)."""
        q = urllib.parse.urlencode({"type": tipo, "limit": limite, "options": "sysAttrs"})
        estado, cuerpo = self._req("GET", f"{ENTIDADES}?{q}", tenant)
        return cuerpo if estado == 200 and isinstance(cuerpo, list) else []

    def crear(self, tenant: str, entidad: Dict[str, Any]) -> int:
        return self._req("POST", ENTIDADES, tenant, entidad)[0]

    def leer(self, tenant: str, entidad_id: str) -> Optional[Dict[str, Any]]:
        estado, cuerpo = self._req("GET", f"{ENTIDADES}/{urllib.parse.quote(entidad_id, safe='')}", tenant)
        return cuerpo if estado == 200 else None

    def anadir_atributos(self, tenant: str, entidad_id: str, attrs: Dict[str, Any]) -> int:
        """Añade o sustituye atributos (POST …/attrs). 204 si todo bien."""
        ruta = f"{ENTIDADES}/{urllib.parse.quote(entidad_id, safe='')}/attrs"
        return self._req("POST", ruta, tenant, attrs)[0]

    def borrar(self, tenant: str, entidad_id: str) -> int:
        return self._req("DELETE", f"{ENTIDADES}/{urllib.parse.quote(entidad_id, safe='')}", tenant)[0]

    def suscripcion(self, tenant: str, sub_id: str) -> Optional[Dict[str, Any]]:
        estado, cuerpo = self._req("GET", f"{SUSCRIPCIONES}/{urllib.parse.quote(sub_id, safe='')}", tenant)
        return cuerpo if estado == 200 else None

    def crear_suscripcion(self, tenant: str, sub: Dict[str, Any]) -> Tuple[int, Any]:
        return self._req("POST", SUSCRIPCIONES, tenant, sub)
