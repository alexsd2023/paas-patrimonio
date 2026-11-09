"""Conector OAI-PMH 2.0 · ListRecords en oai_dc, con resumptionToken, hacia el catastro.

Cada registro se inscribe como ``RegistroCatalografico`` con un id estable derivado de su
identificador OAI: cosechar dos veces actualiza, no duplica. Los registros borrados en el
origen se cuentan y no se inscriben.
"""
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "dc": "http://purl.org/dc/elements/1.1/",
      "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/"}
CAMPOS = {"title": "titulo", "creator": "creadores", "contributor": "colaboradores", "date": "fechas",
          "description": "descripcion", "type": "tipos", "subject": "materias", "language": "idiomas",
          "rights": "derechos", "identifier": "identificadores", "publisher": "editores", "coverage": "cobertura",
          "format": "formatos", "source": "fuentes", "relation": "relaciones"}
UNICOS = {"titulo", "descripcion"}


class ErrorOAI(RuntimeError):
    pass


def urn_registro(tenant: str, identificador: str) -> str:
    h = hashlib.sha1(identificador.encode("utf-8")).hexdigest()[:20]
    return f"urn:ngsi-ld:RegistroCatalografico:{tenant}:{h}"


def leer_pagina(xml: bytes) -> Dict[str, Any]:
    """Una respuesta ListRecords → {registros: [...], token, total?}. Lanza ErrorOAI si el servidor da error."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ErrorOAI(f"la respuesta no es XML: {e}")
    err = raiz.find("oai:error", NS)
    if err is not None:
        codigo = err.get("code", "")
        if codigo == "noRecordsMatch":
            return {"registros": [], "token": None, "total": 0}
        raise ErrorOAI(f"{codigo}: {(err.text or '').strip()}")
    lista = raiz.find("oai:ListRecords", NS)
    if lista is None:
        raise ErrorOAI("la respuesta no trae ListRecords (¿es una dirección OAI-PMH?)")
    registros = []
    for rec in lista.findall("oai:record", NS):
        cab = rec.find("oai:header", NS)
        ident = (cab.findtext("oai:identifier", default="", namespaces=NS) or "").strip()
        r: Dict[str, Any] = {"identificador": ident, "datestamp": cab.findtext("oai:datestamp", default="", namespaces=NS),
                             "conjuntos": [s.text for s in cab.findall("oai:setSpec", NS) if s.text],
                             "borrado": cab.get("status") == "deleted"}
        dc = rec.find("oai:metadata/oai_dc:dc", NS)
        if dc is not None:
            for hijo in dc:
                local = hijo.tag.split("}")[-1]
                campo = CAMPOS.get(local)
                texto = " ".join((hijo.text or "").split())
                if campo and texto:
                    r.setdefault(campo, []).append(texto)
        for c in UNICOS:
            if c in r:
                r[c] = " · ".join(r[c]) if c == "titulo" else r[c][0][:2000]
        registros.append(r)
    tok = lista.find("oai:resumptionToken", NS)
    token = (tok.text or "").strip() if tok is not None else None
    total = tok.get("completeListSize") if tok is not None else None
    return {"registros": registros, "token": token or None, "total": int(total) if total and total.isdigit() else None}


def entidad(tenant: str, r: Dict[str, Any], endpoint: str, ahora: str) -> Dict[str, Any]:
    P = lambda v: {"type": "Property", "value": v}  # noqa: E731
    e = {"id": urn_registro(tenant, r["identificador"]), "type": "RegistroCatalografico",
         "identificadorOai": P(r["identificador"]), "origen": P(endpoint), "cosechadoEn": P(ahora),
         "titulo": P(r.get("titulo") or "(sin título)")}
    if r.get("datestamp"):
        e["modificadoEnOrigen"] = P(r["datestamp"])
    for campo in ("creadores", "colaboradores", "fechas", "tipos", "materias", "idiomas", "derechos",
                  "identificadores", "editores", "cobertura", "formatos", "fuentes", "relaciones", "conjuntos"):
        if r.get(campo):
            e[campo] = P(" | ".join(r[campo]))   # texto: así vuelve del catastro igual que entró
    if r.get("descripcion"):
        e["descripcion"] = P(r["descripcion"])
    return e


def ejecutar(config: Dict[str, Any], ctx) -> Dict[str, Any]:
    endpoint = config["endpoint"].rstrip("?")
    maximo = int(config.get("maximo") or 200)
    params: Optional[Dict[str, str]] = {"verb": "ListRecords", "metadataPrefix": "oai_dc"}
    if config.get("conjunto"):
        params["set"] = config["conjunto"]
    if config.get("desde"):
        params["from"] = config["desde"]
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cuenta = {"nuevos": 0, "actualizados": 0, "borrados": 0, "paginas": 0}
    muestra: List[Dict[str, str]] = []
    total = None
    while params and cuenta["nuevos"] + cuenta["actualizados"] < maximo:
        if ctx.detener():
            break
        r = ctx.http.get(endpoint, params=params, timeout=60)
        if r.status_code >= 400:
            raise ErrorOAI(f"el repositorio respondió {r.status_code}")
        pagina = leer_pagina(r.content)
        cuenta["paginas"] += 1
        total = total or pagina["total"]
        for reg in pagina["registros"]:
            if cuenta["nuevos"] + cuenta["actualizados"] >= maximo:
                break
            if reg["borrado"] or not reg["identificador"]:
                cuenta["borrados"] += 1
                continue
            e = entidad(ctx.tenant, reg, endpoint, ahora)
            res = ctx.inscribir(e)
            cuenta["nuevos" if res == "nueva" else "actualizados"] += 1
            if len(muestra) < 10:
                muestra.append({"titulo": e["titulo"]["value"], "identificador": reg["identificador"],
                                "fecha": (reg.get("fechas") or [""])[0]})
        ctx.avance(f"página {cuenta['paginas']}: {cuenta['nuevos']} nuevos, {cuenta['actualizados']} actualizados")
        params = {"verb": "ListRecords", "resumptionToken": pagina["token"]} if pagina["token"] else None
    return {**cuenta, "total_en_origen": total, "incompleta": bool(params), "muestra": muestra}
