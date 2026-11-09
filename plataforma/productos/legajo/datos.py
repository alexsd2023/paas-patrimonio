"""Lo que el producto del legajo sabe de cada legajo, reunido de cada pieza del núcleo (sin dibujar nada)."""
from typing import Any, Dict, List, Optional


def v(entidad: Optional[dict], attr: str, defecto=None):
    """Valor de un atributo NGSI-LD (Property o Relationship), o el defecto."""
    if not entidad or attr not in entidad:
        return defecto
    a = entidad[attr]
    if isinstance(a, dict):
        return a.get("value", a.get("object", defecto))
    return a


def resumen(activo: dict, copia: Optional[dict]) -> Dict[str, Any]:
    estado_copia = v(copia, "estado")
    return {
        "activo": activo["id"],
        "signatura": v(activo, "signatura"),
        "imagenes": v(activo, "imagenes"),
        "ingestadoPor": v(activo, "ingestadoPor"),
        "creado": activo.get("createdAt"),
        "estado": {"validada": "validada", "pendiente-validacion": "pendiente"}.get(estado_copia, "sin copia"),
    }


def pasos(activo: dict, copia: Optional[dict], proceso: Optional[dict], actas: List[dict]) -> List[Dict[str, Any]]:
    """El recorrido del producto para un legajo: cada paso con su estado (hecho, esperando, pendiente)."""
    acta = {a["tipo"]: a for a in actas}
    estado_proc = (proceso or {}).get("estado")
    validada = v(copia, "estado") == "validada"

    def paso(escena, nombre, hecho, detalle, cuando=None, esperando=False):
        return {"escena": escena, "nombre": nombre,
                "estado": "hecho" if hecho else ("esperando" if esperando else "pendiente"),
                "detalle": detalle, "cuando": cuando}

    return [
        paso("1–2", "La archivera entrega el legajo", True,
             f"{v(activo, 'ingestadoPor')} · {v(activo, 'imagenes')} imágenes"),
        paso("3", "Ficha inscrita en el catastro", True, v(activo, "ark"), activo.get("createdAt")),
        paso("3", "Carta «ha llegado un legajo»", "ingreso" in acta,
             "legajo.ingestado en el buzón activos", (acta.get("ingreso") or {}).get("tiempo")),
        paso("4", "La gestoría abre el expediente", proceso is not None,
             f"TranscripcionEstandar · {estado_proc}" if proceso else "sin proceso en Temporal"),
        paso("4", "El taller hace la copia", copia is not None,
             (f"{v(copia, 'modelo')} · {v(copia, 'lineas')} líneas"
              + (f" · datos {v(copia, 'datosVersion')[:10]}" if v(copia, "datosVersion") else "")) if copia else "—",
             (copia or {}).get("createdAt"), esperando=proceso is not None and copia is None),
        paso("4", "Carta «copia terminada»", "htr" in acta,
             "htr.completado en el buzón htr", (acta.get("htr") or {}).get("tiempo")),
        paso("5", "La paleógrafa firma", validada,
             f"firmada por {v(copia, 'validadoPor')}" if validada else "esperando la firma",
             None, esperando=estado_proc == "pendiente-validacion"),
        paso("5", "Acta de la validación", "validacion" in acta,
             "transcripcion.validada", (acta.get("validacion") or {}).get("tiempo")),
    ]
