"""Interfaz común de los anclajes: cada proveedor ancla una huella fuera de la plataforma.

Un anclaje es un dict del tipo «evidencia» (contracts/tipos/evidencia.schema.json, anclajes[]).
Añadir un proveedor (otro PSC, otro prestador eIDAS, otra cadena) es escribir una clase con estos
tres métodos y registrarla en proveedores/__init__.py. El resto de la capacidad no cambia.
"""
import base64
from datetime import datetime, timezone
from typing import Any, Dict


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def de_b64(texto: str) -> bytes:
    return base64.b64decode(texto.encode("ascii"))


class Proveedor:
    nombre = ""          # blockchain | eidas | nom151
    modo = "real"        # real | demo | simulado
    valor_legal = "ninguno"
    emisor = ""

    def describir(self) -> Dict[str, Any]:
        return {"proveedor": self.nombre, "modo": self.modo, "valorLegal": self.valor_legal, "emisor": self.emisor}

    def _anclaje(self, **campos) -> Dict[str, Any]:
        return {"proveedor": self.nombre, "modo": self.modo, "valorLegal": self.valor_legal,
                "emisor": self.emisor, **campos}

    def anclar(self, digest: bytes) -> Dict[str, Any]:
        """Ancla la huella (32 bytes). Devuelve el anclaje: pendiente o confirmado."""
        raise NotImplementedError

    def actualizar(self, anclaje: Dict[str, Any], digest: bytes) -> Dict[str, Any]:
        """Intenta completar un anclaje pendiente. Por defecto no hay nada que completar."""
        return anclaje

    def verificar(self, anclaje: Dict[str, Any], digest: bytes) -> Dict[str, Any]:
        """¿La prueba ampara esta huella? → {valido, detalle, fecha?, bloque?}"""
        raise NotImplementedError
