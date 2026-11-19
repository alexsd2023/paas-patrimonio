"""eIDAS: sello de tiempo electrónico (RFC 3161).

Es el mismo protocolo que usan los prestadores cualificados europeos. En la demo apunta a un servicio
gratuito (FreeTSA): técnica real, pero el sello NO es cualificado y no tiene presunción legal.
Para producción basta con cambiar la URL y el certificado a los de un prestador cualificado
y poner EIDAS_CUALIFICADO=si.

Entorno:
  EIDAS_TSA_URL      por defecto https://freetsa.org/tsr
  EIDAS_TSA_CERT     ruta al certificado PEM de la TSA (opcional: si falta, se usa el que viene en el sello)
  EIDAS_CUALIFICADO  si | no (por defecto no)
  EIDAS_EMISOR       nombre que se muestra (por defecto «FreeTSA (no cualificado)»)
"""
import os
from typing import Any, Callable, Dict, Optional

import rfc3161ng

from .base import Proveedor, b64, de_b64, iso


class EidasRFC3161(Proveedor):
    nombre = "eidas"

    def __init__(self, url: Optional[str] = None, certificado: Optional[bytes] = None,
                 cualificado: Optional[bool] = None, emisor: Optional[str] = None,
                 sellar: Optional[Callable[[bytes], bytes]] = None):
        self.url = url or os.environ.get("EIDAS_TSA_URL", "https://freetsa.org/tsr")
        ruta = os.environ.get("EIDAS_TSA_CERT")
        self.certificado = certificado if certificado is not None else (open(ruta, "rb").read() if ruta else None)
        if cualificado is None:
            cualificado = os.environ.get("EIDAS_CUALIFICADO", "no").lower() in ("si", "sí", "true", "1")
        self.modo = "real" if cualificado else "demo"
        self.valor_legal = "eidas-cualificado" if cualificado else "ninguno"
        self.emisor = emisor or os.environ.get("EIDAS_EMISOR") or (
            "Prestador cualificado eIDAS" if cualificado else "FreeTSA (no cualificado)")
        self._sellar = sellar or self._sellar_remoto

    @property
    def _cert(self) -> bytes:
        return self.certificado or b""   # b"": rfc3161ng usa el certificado que viene dentro del sello

    def _sellar_remoto(self, digest: bytes) -> bytes:
        tsa = rfc3161ng.RemoteTimestamper(self.url, certificate=self._cert, hashname="sha256",
                                          include_tsa_certificate=True, timeout=15)
        return tsa(digest=digest)

    def anclar(self, digest: bytes) -> Dict[str, Any]:
        token = self._sellar(digest)
        rfc3161ng.check_timestamp(token, certificate=self._cert, digest=digest, hashname="sha256")
        fecha = rfc3161ng.get_timestamp(token, naive=False)
        detalle = "Sello de tiempo RFC 3161" + ("" if self.modo == "real" else " de demostración: sin valor legal")
        return self._anclaje(estado="confirmado", fecha=iso(fecha), prueba=b64(token), detalle=detalle)

    def verificar(self, anclaje: Dict[str, Any], digest: bytes) -> Dict[str, Any]:
        try:
            token = de_b64(anclaje["prueba"])
            rfc3161ng.check_timestamp(token, certificate=self._cert, digest=digest, hashname="sha256")
            fecha = iso(rfc3161ng.get_timestamp(token, naive=False))
        except Exception as ex:  # noqa: BLE001  cualquier fallo es «no válido»
            motivo = "el texto no coincide con la huella sellada" if "imprint" in str(ex).lower() else str(ex)
            return {"valido": False, "detalle": motivo}
        return {"valido": True, "fecha": fecha, "detalle": f"Sello válido de {self.emisor} ({fecha})"}
