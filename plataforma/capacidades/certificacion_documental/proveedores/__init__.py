"""Los proveedores de anclaje disponibles. Se crean al primer uso (leen su configuración del entorno)."""
from typing import Callable, Dict

from .base import Proveedor

_FABRICAS: Dict[str, Callable[[], Proveedor]] = {}
_CREADOS: Dict[str, Proveedor] = {}


def registrar(nombre: str, fabrica: Callable[[], Proveedor]) -> None:
    _FABRICAS[nombre] = fabrica
    _CREADOS.pop(nombre, None)


def obtener(nombre: str) -> Proveedor:
    if nombre not in _FABRICAS:
        raise ValueError(f"anclaje desconocido: {nombre!r} (hay {sorted(_FABRICAS)})")
    if nombre not in _CREADOS:
        _CREADOS[nombre] = _FABRICAS[nombre]()
    return _CREADOS[nombre]


def disponibles():
    return sorted(_FABRICAS)


def _blockchain():
    from .blockchain_ots import BlockchainOTS
    return BlockchainOTS()


def _eidas():
    from .eidas_rfc3161 import EidasRFC3161
    return EidasRFC3161()


def _nom151():
    from .nom151_simulado import Nom151Simulado
    return Nom151Simulado()


registrar("blockchain", _blockchain)
registrar("eidas", _eidas)
registrar("nom151", _nom151)
