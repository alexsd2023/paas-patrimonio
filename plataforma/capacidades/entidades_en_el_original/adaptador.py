"""Adaptador del «entity matcher» de Ameyalli: texto-modernizado → edicion-anotada (/paleo-ner/map).

Entra un texto modernizado, que trae consigo su original paleográfico: no hace falta pasar dos documentos.
Respuesta (MapOut): {entities: [{text, label, fields, line, start, end,
                                 paleographic: {start, end, text, similarity} | null}], mapped, unmatched, …}

Las posiciones se comprueban contra el texto: si no cuadran (p. ej. vienen por línea) se busca el fragmento
cerca de donde dice el servicio. Una entidad que no aparece tal cual en el texto no se marca.
"""
from typing import Any, Dict, List, Optional

from capacidades._ameyalli import inicios_de_linea, llamar, localizar


def _mapear(manifiesto, paleo: str, moderno: str, parametros: dict, http, secretos) -> List[Dict[str, Any]]:
    cuerpo = {"paleographic": paleo, "modern": moderno, "model": parametros.get("modelo") or "ruler",
              "settings": {"threshold": float(parametros.get("umbral") if parametros.get("umbral") is not None else 0.45),
                           "line_margin": int(parametros.get("margen_lineas") if parametros.get("margen_lineas") is not None else 1)}}
    return list((llamar(manifiesto, "/paleo-ner/map", cuerpo, http, secretos) or {}).get("entities") or [])


def _bloques(paleo: str, moderno: str, maximo: int):
    """Si cabe, un solo bloque. Si no, por grupos de líneas, solo cuando ambas versiones tienen las mismas
    líneas (si no, cortar las desalinearía)."""
    if len(paleo) <= maximo and len(moderno) <= maximo:
        return [(0, paleo, 0, moderno)]
    lp, lm = paleo.split("\n"), moderno.split("\n")
    if len(lp) != len(lm):
        raise RuntimeError(f"el texto pasa de {maximo} caracteres y sus dos versiones no tienen las mismas líneas: "
                           f"divídelo (p. ej. por folios) antes de lanzarlo")
    out, i, dp, dm = [], 0, 0, 0
    while i < len(lp):
        j, tam = i, 0
        while j < len(lp) and tam + max(len(lp[j]), len(lm[j])) + 1 <= maximo:
            tam += max(len(lp[j]), len(lm[j])) + 1
            j += 1
        j = max(j, i + 1)
        bp, bm = "\n".join(lp[i:j]), "\n".join(lm[i:j])
        out.append((dp, bp, dm, bm))
        dp += len(bp) + 1
        dm += len(bm) + 1
        i = j
    return out


def ejecutar(manifiesto, entrada: dict, parametros: dict, http, secretos: Optional[dict] = None) -> dict:
    paleo, moderno = entrada["original"], entrada["texto"]
    maximo = int((manifiesto.externo or {}).get("max_caracteres", 18000))
    entidades, modernas, perdidas = [], [], []
    for dp, bp, dm, bm in _bloques(paleo, moderno, maximo):
        lin_p, lin_m = inicios_de_linea(bp), inicios_de_linea(bm)
        for e in _mapear(manifiesto, bp, bm, parametros, http, secretos):
            tipo, txt = str(e.get("label") or "?"), str(e.get("text") or "")
            linea = e.get("line") if isinstance(e.get("line"), int) else None
            pista_linea = lin_m[linea] + e["start"] if linea is not None and linea < len(lin_m) and isinstance(e.get("start"), int) else None
            pos_m = localizar(bm, txt, [e.get("start"), pista_linea])
            if pos_m:
                modernas.append({"tipo": tipo, "texto": txt, "inicio": pos_m[0] + dm, "fin": pos_m[1] + dm})
            m = e.get("paleographic") or {}
            pos_p = None
            if m.get("text"):
                # la pista por línea: la misma línea en la versión paleográfica, si existe
                pl = lin_p[linea] + m["start"] if linea is not None and linea < len(lin_p) and isinstance(m.get("start"), int) else None
                pos_p = localizar(bp, str(m["text"]), [m.get("start"), pl])
            if pos_p:
                ent = {"tipo": tipo, "texto": bp[pos_p[0]:pos_p[1]], "inicio": pos_p[0] + dp, "fin": pos_p[1] + dp,
                       "moderno": txt}
                if isinstance(m.get("similarity"), (int, float)):
                    ent["confianza"] = round(float(m["similarity"]), 3)
                if e.get("fields"):
                    ent["rasgos"] = [str(f) for f in e["fields"]]
                entidades.append(ent)
            else:
                perdidas.append({"tipo": tipo, "texto": txt})
    salida = {"texto": paleo, "entidades": sorted(entidades, key=lambda x: x["inicio"]),
              "modernizado": {"texto": moderno, "entidades": sorted(modernas, key=lambda x: x["inicio"])},
              "sin_localizar": perdidas}
    if entrada.get("activo"):
        salida["activo"] = entrada["activo"]
    return salida
