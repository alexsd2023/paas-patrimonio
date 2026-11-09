"""Recetas de flujo: lo que un ciudadano escribe para encadenar servicios y firmas.

    nombre: Modernizar y anotar
    entrada: transcripcion          # tipo del documento con que empieza
    pasos:
      - servicio: modernizador-demo
      - firma: paleografa           # una persona con ese rol revisa y aprueba
        instrucciones: Revisa la grafía modernizada
      - servicio: ner-historico
        parametros: {etiquetas: [PER, LOC]}
      - firma: paleografa
    publicar: true                  # el resultado queda en el catastro y sale una carta

Antes de aceptarla se comprueba: que cada servicio existe y quien la lanza tiene acceso, que la
salida de cada paso encaja en la entrada del siguiente, que los parámetros son válidos y que
nada se publica sin una firma humana después del último servicio. Las versiones quedan fijadas.
"""
from typing import Any, Dict, List

from sdk.servicios import TIPOS, DocumentoInvalido, encaja

MAX_PASOS = 20


class RecetaInvalida(ValueError):
    def __init__(self, errores: List[str]):
        super().__init__("; ".join(errores))
        self.errores = errores


def planificar(receta: Dict[str, Any], catalogo, *, roles: List[str], tenant: str) -> Dict[str, Any]:
    """Receta → plan ejecutable (versiones fijadas y tipos de cada paso). Lanza RecetaInvalida."""
    e: List[str] = []
    if not isinstance(receta, dict):
        raise RecetaInvalida(["la receta debe ser un objeto con nombre, entrada y pasos"])
    nombre = str(receta.get("nombre") or "").strip()
    if not nombre:
        e.append("falta nombre")
    tipo = receta.get("entrada")
    if tipo not in TIPOS:
        e.append(f"entrada: uno de {sorted(TIPOS)}")
    pasos = receta.get("pasos")
    if not isinstance(pasos, list) or not pasos:
        raise RecetaInvalida(e + ["pasos: al menos uno"])
    if len(pasos) > MAX_PASOS:
        e.append(f"como mucho {MAX_PASOS} pasos")
    plan: List[Dict[str, Any]] = []
    ultimo_servicio, ultima_firma = -1, -1
    for n, p in enumerate(pasos, 1):
        if not isinstance(p, dict) or ("servicio" in p) == ("firma" in p):
            e.append(f"paso {n}: debe tener «servicio» o «firma» (uno de los dos)")
            continue
        if "firma" in p:
            rol = str(p["firma"] or "").strip()
            if not rol:
                e.append(f"paso {n}: firma necesita el rol de quien firma")
                continue
            plan.append({"n": n, "clase": "firma", "rol": rol, "instrucciones": str(p.get("instrucciones") or "")})
            ultima_firma = n
            continue
        sid = p["servicio"]
        try:
            m = catalogo.get(sid)
        except KeyError:
            e.append(f"paso {n}: no hay ningún servicio {sid!r} en el catálogo")
            continue
        if not m.permite(roles, tenant):
            e.append(f"paso {n}: no tienes acceso a {sid}")
        if m.tipo != "tarea":
            e.append(f"paso {n}: {sid} es de consulta; en un flujo solo van servicios de tipo tarea")
        if tipo in TIPOS and not encaja(tipo, m.entrada):
            e.append(f"paso {n}: {sid} necesita {m.entrada} y le llega {tipo}")
        try:
            params = m.parametros_con_defecto(p.get("parametros"))
        except DocumentoInvalido as ex:
            e.append(f"paso {n}: {ex}")
            params = {}
        plan.append({"n": n, "clase": "servicio", "servicio": sid, "version": m.version, "parametros": params,
                     "recibe": tipo, "entrega": m.salida})
        tipo = m.salida
        ultimo_servicio = n
    if ultimo_servicio < 0:
        e.append("un flujo necesita al menos un servicio")
    publicar = bool(receta.get("publicar", False))
    if publicar and ultima_firma < ultimo_servicio:
        e.append("para publicar, una persona tiene que firmar después del último servicio")
    if e:
        raise RecetaInvalida(e)
    return {"nombre": nombre, "entrada": receta["entrada"], "salida": tipo, "pasos": plan, "publicar": publicar}
