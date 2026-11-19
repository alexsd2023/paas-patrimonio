"""El pasaporte de cada activo digital: lo que todos los productos leen igual.

Cuatro pilares: identidad (huella y anclajes), procedencia (el libro del notario), derechos y uso por IA.
Aquí solo lo común para leerlos de una entidad del catastro; la página pública vive en la consola
(services/panel/pasaporte.py) y la certificación, en la capacidad certificacion-documental.
"""
import json
import re
from typing import Any, Dict, List, Optional

URN_TRANSCRIPCION = re.compile(r"^urn:ngsi-ld:Transcripcion:[a-z0-9-]+:[A-Za-z0-9-]+$")
SIN_DECLARAR = {"estado": "sin-declarar", "texto": "Sin declarar: la institución aún no ha fijado su política"}

# Cómo se llama cada acta del notario en el pasaporte público
ACTAS = {"ingreso": "Entrada del legajo", "htr": "Transcripción automática",
         "validacion": "Validación por una persona experta", "certificacion": "Certificación",
         "anclaje": "Un tercero confirma la fecha"}


def valor(entidad: Optional[dict], attr: str, defecto=None):
    if not entidad or attr not in entidad:
        return defecto
    a = entidad[attr]
    return a.get("value", a.get("object", defecto)) if isinstance(a, dict) else a


def leer_evidencia(entidad: Optional[dict]) -> Optional[dict]:
    """La evidencia se guarda como texto JSON (el catastro no reinterpreta sus claves); se acepta también objeto."""
    v = valor(entidad, "evidencia")
    return json.loads(v) if isinstance(v, str) else v


def estado_certificacion(evidencia: dict) -> str:
    """confirmada · pendiente (algún anclaje espera, p. ej. Bitcoin) · error (ninguno vale)"""
    estados = [a["estado"] for a in evidencia["anclajes"]]
    if all(e == "error" for e in estados):
        return "error"
    return "pendiente" if "pendiente" in estados else "confirmada"


def anclajes_publicos(evidencia: Optional[dict]) -> List[Dict[str, Any]]:
    """Los anclajes sin la prueba (que se descarga aparte)."""
    campos = ("proveedor", "modo", "valorLegal", "estado", "emisor", "fecha", "bloque", "detalle")
    return [{k: a[k] for k in campos if k in a} for a in (evidencia or {}).get("anclajes", [])]


def actas_publicas(actas: List[dict]) -> List[Dict[str, Any]]:
    """El libro del notario para cualquiera: sin nombres de usuario (las personas salen como tales)."""
    out = []
    for a in actas:
        agentes = []
        for x in a.get("agentes", []):
            if x.startswith("urn:paas:usuario:"):
                agentes.append("una persona de la institución")
            elif x.startswith(("urn:paas:modelo:", "urn:paas:capacidad:", "urn:paas:anclaje:")):
                agentes.append(x.split(":", 3)[3])
        out.append({"tipo": a.get("tipo"), "nombre": ACTAS.get(a.get("tipo"), a.get("tipo")), "tiempo": a.get("tiempo"),
                    "detalle": a.get("detalle"), "agentes": sorted(set(agentes))})
    return out
