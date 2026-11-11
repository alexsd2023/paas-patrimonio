"""Lo común a las capacidades que llaman a la API de Ameyalli (Scriptorium · New Spain Fleets).

La API de Ameyalli es una pasarela delante de varios Spaces de Hugging Face, Groq y LatamGPT. Desde el PaaS
cada herramienta es una capacidad: aquí solo está cómo se le habla.

* URL: la del manifiesto, o AMEYALLI_URL si la plataforma usa otro despliegue.
* Clave: el secreto SCRIPTORIUM_API_KEY (de la plataforma o de la institución). Si el despliegue de
  Ameyalli no exige clave, se puede dejar sin poner.
* Errores: Ameyalli siempre responde {"detail": …}; 502/504 = el Space no respondió (suelen tardar en
  despertar), 503 = la herramienta no está configurada en ese despliegue.
"""
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

CLAVE = "SCRIPTORIUM_API_KEY"


class ErrorAmeyalli(RuntimeError):
    def __init__(self, codigo: int, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo


def _detalle(r) -> str:
    try:
        d = r.json()
        return str(d.get("detail") if isinstance(d, dict) else d)[:300]
    except ValueError:
        return r.text[:300]


def llamar(manifiesto, ruta: str, cuerpo: Dict[str, Any], http, secretos: Optional[dict] = None) -> Any:
    base = (os.environ.get("AMEYALLI_URL") or manifiesto.url).rstrip("/")
    clave = (secretos or {}).get(CLAVE) or os.environ.get(CLAVE, "")
    cab = {"Authorization": f"Bearer {clave}"} if clave else {}
    espera = float((manifiesto.externo or {}).get("espera_s", 180))
    r = http.post(f"{base}{ruta}", json=cuerpo, headers=cab, timeout=espera)
    if r.status_code < 400:
        return r.json()
    d = _detalle(r)
    if r.status_code == 401:
        raise ErrorAmeyalli(401, f"Ameyalli rechaza la clave: pon {CLAVE} en Mi institución → Secretos ({d})")
    if r.status_code in (502, 504):
        raise ErrorAmeyalli(r.status_code, f"el servicio de Ameyalli no respondió a tiempo; los Spaces de Hugging Face "
                                           f"tardan en despertar, reintenta ({d})")
    if r.status_code == 503:
        raise ErrorAmeyalli(503, f"esa herramienta no está configurada en el despliegue de Ameyalli ({d})")
    if r.status_code == 429:
        raise ErrorAmeyalli(429, f"el proveedor del modelo ha llegado a su límite de uso ({d})")
    raise ErrorAmeyalli(r.status_code, f"Ameyalli respondió {r.status_code}: {d}")


def trocear(texto: str, maximo: int) -> List[Tuple[int, str]]:
    """Trozos de como mucho `maximo` caracteres, cortando en saltos de línea. (desde, trozo)."""
    trozos, i = [], 0
    while i < len(texto):
        fin = min(len(texto), i + maximo)
        if fin < len(texto):
            corte = texto.rfind("\n", i, fin)
            fin = corte + 1 if corte > i else fin
        trozos.append((i, texto[i:fin]))
        i = fin
    return trozos or [(0, "")]


def inicios_de_linea(texto: str) -> List[int]:
    out = [0]
    for i, c in enumerate(texto):
        if c == "\n":
            out.append(i + 1)
    return out


def localizar(texto: str, fragmento: str, pistas: Iterable[Optional[int]]) -> Optional[Tuple[int, int]]:
    """Dónde está `fragmento` en `texto`. Prueba primero las posiciones que sugiere el servicio (que pueden ser
    absolutas o por línea) y, si ninguna cuadra, la aparición más cercana a la primera pista.
    Nunca inventa: si el fragmento no está en el texto, devuelve None."""
    if not fragmento:
        return None
    pistas = [p for p in pistas if isinstance(p, int) and p >= 0]
    for p in pistas:
        if texto[p:p + len(fragmento)] == fragmento:
            return p, p + len(fragmento)
    apariciones, i = [], texto.find(fragmento)
    while i >= 0:
        apariciones.append(i)
        i = texto.find(fragmento, i + 1)
    if not apariciones:
        return None
    ref = pistas[0] if pistas else 0
    p = min(apariciones, key=lambda x: abs(x - ref))
    return p, p + len(fragmento)
