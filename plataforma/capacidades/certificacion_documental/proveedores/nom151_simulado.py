"""NOM-151 SIMULADA, solo para demostraciones.

Imita la forma de una constancia de conservación (huella, fecha, PSC, política) y la firma con una
clave de la plataforma. NO la emite un Prestador de Servicios de Certificación acreditado y NO tiene
ningún valor legal: sirve para enseñar el flujo. Para producción, se sustituye por un conector
con la API de un PSC acreditado (misma interfaz: anclar · verificar).

Entorno:
  NOM151_SIM_CLAVE  clave HMAC de la simulación (por defecto una de demostración)
"""
import hashlib
import hmac
import json
import os
from typing import Any, Dict, Optional

from .base import Proveedor, ahora, b64, de_b64

_AVISO = "Constancia SIMULADA para demostración: no la emite un PSC acreditado y no tiene valor legal"


class Nom151Simulado(Proveedor):
    nombre, modo, valor_legal = "nom151", "simulado", "ninguno"
    emisor = "PSC simulado (demo)"

    def __init__(self, clave: Optional[str] = None):
        self.clave = (clave or os.environ.get("NOM151_SIM_CLAVE") or "demo-nom151-no-usar-en-produccion").encode()

    def _firma(self, cuerpo: Dict[str, Any]) -> str:
        datos = json.dumps(cuerpo, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self.clave, datos, hashlib.sha256).hexdigest()

    def anclar(self, digest: bytes) -> Dict[str, Any]:
        cuerpo = {"tipo": "constancia-nom151-simulada", "psc": self.emisor, "politica": "0.0.0.0",
                  "algoritmo": "sha256", "huella": digest.hex(), "fecha": ahora(), "aviso": _AVISO}
        constancia = dict(cuerpo, firma=self._firma(cuerpo))
        return self._anclaje(estado="confirmado", fecha=cuerpo["fecha"],
                             prueba=b64(json.dumps(constancia, ensure_ascii=False).encode()), detalle=_AVISO)

    def verificar(self, anclaje: Dict[str, Any], digest: bytes) -> Dict[str, Any]:
        try:
            constancia = json.loads(de_b64(anclaje["prueba"]))
            firma = constancia.pop("firma")
        except Exception as ex:  # noqa: BLE001
            return {"valido": False, "detalle": f"constancia ilegible: {ex}"}
        if not hmac.compare_digest(firma, self._firma(constancia)):
            return {"valido": False, "detalle": "la firma de la constancia no es válida"}
        if constancia.get("huella") != digest.hex():
            return {"valido": False, "detalle": "el texto no coincide con la huella de la constancia"}
        return {"valido": True, "fecha": constancia["fecha"], "detalle": f"Constancia válida ({_AVISO.lower()})"}
