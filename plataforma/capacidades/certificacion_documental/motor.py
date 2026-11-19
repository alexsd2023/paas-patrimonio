"""Certificar, completar y verificar evidencias. Sin estado: todo entra y sale en el documento.

La huella se calcula sobre el texto normalizado («nfc-lf-strip»), para que el mismo texto dé siempre
la misma huella aunque cambien los saltos de línea (Windows/Unix) o la forma Unicode de las tildes.
"""
import hashlib
import unicodedata
from typing import Any, Dict, List

from . import proveedores
from .proveedores.base import ahora

NORMALIZACION = "nfc-lf-strip"


def normalizar(texto: str) -> str:
    t = texto.replace("\r\n", "\n").replace("\r", "\n").strip()
    return unicodedata.normalize("NFC", t)


def huella(texto: str) -> bytes:
    return hashlib.sha256(normalizar(texto).encode("utf-8")).digest()


def certificar(texto: str, anclajes: List[str]) -> Dict[str, Any]:
    digest = huella(texto)
    resultado, errores = [], []
    for nombre in dict.fromkeys(anclajes or ["blockchain"]):   # sin repetidos, en el orden pedido
        p = proveedores.obtener(nombre)
        try:
            resultado.append(p.anclar(digest))
        except Exception as ex:  # noqa: BLE001  un proveedor caído no tumba a los demás
            errores.append(f"{nombre}: {ex}")
            resultado.append(dict(p.describir(), estado="error", detalle=str(ex)[:500]))
    if all(a["estado"] == "error" for a in resultado):
        raise RuntimeError("no se pudo anclar en ningún proveedor: " + "; ".join(errores))
    return {"huella": digest.hex(), "algoritmo": "sha256", "normalizacion": NORMALIZACION,
            "fecha": ahora(), "anclajes": resultado}


def actualizar(texto: str, evidencia: Dict[str, Any]) -> Dict[str, Any]:
    digest = huella(texto)
    if digest.hex() != evidencia.get("huella"):
        raise ValueError("el texto no coincide con la huella de la evidencia")
    nuevos = []
    for a in evidencia["anclajes"]:
        if a.get("estado") == "pendiente":
            a = proveedores.obtener(a["proveedor"]).actualizar(a, digest)
        nuevos.append(a)
    return dict(evidencia, anclajes=nuevos)


def verificar(texto: str, evidencia: Dict[str, Any]) -> Dict[str, Any]:
    """Comprueba el texto ACTUAL contra cada anclaje por separado (cada uno con su propia prueba)."""
    digest = huella(texto)
    integro = digest.hex() == evidencia.get("huella")
    resultados = []
    for a in evidencia.get("anclajes", []):
        base = {k: a.get(k) for k in ("proveedor", "modo", "valorLegal", "emisor", "estado")}
        if a.get("estado") == "error" or not a.get("prueba"):
            resultados.append(dict(base, valido=False, detalle=a.get("detalle") or "sin prueba"))
            continue
        try:
            r = proveedores.obtener(a["proveedor"]).verificar(a, digest)
        except Exception as ex:  # noqa: BLE001
            r = {"valido": False, "detalle": str(ex)}
        resultados.append(dict(base, **r))
    validos = [r for r in resultados if r["valido"]]
    if not integro:
        resumen = "ALTERADO: el texto no coincide con el que se certificó"
    elif not validos:
        resumen = "SIN PRUEBA VÁLIDA: la huella coincide, pero ningún anclaje la ampara"
    else:
        resumen = "ÍNTEGRO: " + " · ".join(f"{r['proveedor']} ({r['modo']})" for r in validos)
    return {"integro": integro and bool(validos), "huellaActual": digest.hex(),
            "huellaCertificada": evidencia.get("huella"), "resumen": resumen, "anclajes": resultados}
