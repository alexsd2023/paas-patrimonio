"""Adaptador del NER de Lancaster (Hugging Face): documento común ⇄ su API.

Su API (v1.3.0):
    POST {url}/annotate/text?model=ruler|toponyms     {"text": "..."}     Authorization: Bearer <token>
    → [{"Anotacion": "<una línea>", "entities": [{"start", "end", "entity", "fields": [...]}, ...]}, ...]

Las posiciones vienen por línea; aquí se pasan a posiciones en el texto entero, que es lo que
pide el tipo ``transcripcion-anotada``. El token se lee de la variable de entorno que diga
``externo.token_env`` (nunca va en el manifiesto ni en el repositorio).
"""
import os
from typing import Any, Dict, List, Tuple

K_LINEA = ("Anotacion", "anotacion", "text", "linea", "line")
K_TIPO = ("entity", "label", "entity_group", "type", "tipo")


def _primero(d: dict, claves) -> Any:
    return next((d[k] for k in claves if k in d and d[k] is not None), None)


def normalizar(resp: Any, texto: str, desplazamiento: int = 0) -> List[Dict[str, Any]]:
    """Respuesta por líneas → entidades con posiciones en `texto` (+ desplazamiento del trozo)."""
    filas = resp if isinstance(resp, list) else (resp or {}).get("results", [])
    out: List[Dict[str, Any]] = []
    cursor = 0
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        linea = _primero(fila, K_LINEA)
        if isinstance(linea, str) and linea:
            base = texto.find(linea, cursor)
            if base < 0:
                base = texto.find(linea.strip(), cursor)
            if base < 0:
                continue  # línea que no reconocemos en el texto: mejor no inventar posiciones
            cursor = base + len(linea)
        else:
            base, linea = 0, texto
        for x in fila.get("entities") or []:
            ini, fin, tipo = x.get("start"), x.get("end"), _primero(x, K_TIPO)
            if not isinstance(ini, int) or not isinstance(fin, int) or tipo is None or not 0 <= ini < fin <= len(linea):
                continue
            ent = {"tipo": str(tipo), "texto": linea[ini:fin], "inicio": base + ini + desplazamiento,
                   "fin": base + fin + desplazamiento}
            if x.get("fields"):
                ent["rasgos"] = [str(f) for f in x["fields"]]
            out.append(ent)
    return out


def trocear(texto: str, maximo: int) -> List[Tuple[int, str]]:
    """Trozos de como mucho `maximo` caracteres, cortando en saltos de línea (la API anota por líneas)."""
    trozos, i = [], 0
    while i < len(texto):
        fin = min(len(texto), i + maximo)
        if fin < len(texto):
            corte = texto.rfind("\n", i, fin)
            fin = corte + 1 if corte > i else fin
        trozos.append((i, texto[i:fin]))
        i = fin
    return trozos


def ejecutar(manifiesto, entrada: dict, parametros: dict, http) -> dict:
    cfg = manifiesto.externo or {}
    token = os.environ.get(cfg.get("token_env", "NER_TOKEN"), "")
    if not token:
        raise RuntimeError(f"falta el token del NER: define {cfg.get('token_env', 'NER_TOKEN')} en platform/.env")
    texto = entrada["texto"]
    entidades: List[Dict[str, Any]] = []
    for desde, trozo in trocear(texto, int(cfg.get("max_caracteres", 3000))):
        if not trozo.strip():
            continue
        r = http.post(f"{manifiesto.url}{cfg.get('ruta', '/annotate/text')}",
                      params={"model": parametros.get("modelo") or "ruler"}, json={"text": trozo},
                      headers={"Authorization": f"Bearer {token}"}, timeout=cfg.get("espera_s", 120))
        if r.status_code in (401, 403):
            raise RuntimeError(f"el NER rechaza el token ({r.status_code})")
        if r.status_code >= 400:
            raise RuntimeError(f"el NER respondió {r.status_code}: {r.text[:300]}")
        entidades += normalizar(r.json(), trozo, desde)
    quiero = parametros.get("etiquetas")
    if quiero:
        entidades = [e for e in entidades if e["tipo"] in quiero]
    salida = {"texto": texto, "entidades": entidades}
    if entrada.get("activo"):
        salida["activo"] = entrada["activo"]
    return salida
