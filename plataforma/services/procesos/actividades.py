"""Actividades del proceso de transcripción: lo que el proceso encarga a otros.

Temporal las reintenta solas si fallan (el taller caído, el catastro lento…).
Por eso son idempotentes.
"""
import asyncio
import json
import os
import urllib.request
import uuid

from temporalio import activity

ESPACIO_IDS = uuid.UUID("5b0f4c1e-7a2d-4e8b-9c3f-0d1a2b3c4d5e")


def _post(url: str, cuerpo: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


@activity.defn(name="transcribir")
async def transcribir(datos: dict) -> dict:
    """Encarga la copia al taller (módulo HTR, por su API)."""
    url = os.environ.get("HTR_URL", "http://htr:8080").rstrip("/") + "/transcripciones"
    return await asyncio.to_thread(_post, url, {"activo": datos["activo"], "tenant": datos["tenant"]})


def _registrar_validacion(d: dict) -> dict:
    from sdk.eventos import Publicador, nuevo_evento
    from sdk.registro import Registro

    prop = lambda v: {"type": "Property", "value": v}  # noqa: E731
    codigo = Registro(os.environ["SCORPIO_URL"]).anadir_atributos(
        d["tenant"], d["transcripcion"], {"estado": prop("validada"), "validadoPor": prop(d["validadoPor"])})
    if codigo not in (204, 207):
        raise RuntimeError(f"el catastro respondió {codigo} al marcar la transcripción como validada")
    carta = nuevo_evento(
        "transcripcion.validada",
        id=str(uuid.uuid5(ESPACIO_IDS, f"transcripcion.validada|{d['transcripcion']}")),
        tenant=d["tenant"], subject=d["transcripcion"], source=f"/tenants/{d['tenant']}/servicios/procesos",
        data={"activo": d["activo"], "estado": "validada", "modelo": d["modelo"], "validadoPor": d["validadoPor"]},
    )
    Publicador(os.environ["KAFKA_BOOTSTRAP"], client_id="procesos").publicar(carta)
    return {"evento": carta["id"]}


@activity.defn(name="registrar_validacion")
async def registrar_validacion(d: dict) -> dict:
    """Marca la transcripción como validada en el catastro y envía transcripcion.validada."""
    return await asyncio.to_thread(_registrar_validacion, d)


# ---------- certificación (capacidad certificacion-documental, por el catálogo) ----------

def _activada() -> bool:
    return os.environ.get("CERTIFICAR", "no").strip().lower() in ("si", "sí", "true", "1")


def _anclajes_por_defecto() -> list:
    return [a.strip() for a in os.environ.get("CERTIFICAR_ANCLAJES", "blockchain").split(",") if a.strip()]


def estado_certificacion(evidencia: dict) -> str:
    """confirmada · pendiente (algún anclaje espera, p. ej. Bitcoin) · error (ninguno vale)"""
    estados = [a["estado"] for a in evidencia["anclajes"]]
    if all(e == "error" for e in estados):
        return "error"
    return "pendiente" if "pendiente" in estados else "confirmada"


def leer_evidencia(ent: dict):
    """La evidencia se guarda como texto JSON (el catastro no reinterpreta sus claves); se acepta también objeto."""
    v = (ent.get("evidencia") or {}).get("value")
    return json.loads(v) if isinstance(v, str) else v


def ejecutar_capacidad(tenant: str, entrada: dict, parametros: dict) -> dict:
    """Usa la capacidad por el catálogo (uso interno, como conservación con EN 15757): cuenta en el consumo."""
    url = os.environ.get("CATALOGO_INTERNO", "http://catalogo:8080").rstrip("/")
    clave = os.environ.get("CATALOGO_INTERNO_CLAVE")
    if not clave:
        raise RuntimeError("falta CATALOGO_INTERNO_CLAVE: el proceso no puede usar la capacidad de certificación")
    req = urllib.request.Request(
        f"{url}/interno/servicios/certificacion-documental/ejecutar", method="POST",
        data=json.dumps({"tenant": tenant, "entrada": entrada, "parametros": parametros}).encode(),
        headers={"Content-Type": "application/json", "X-Clave-Interna": clave, "X-Producto": "legajo"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["salida"]


def _certificar(d: dict, ejecutar=None, registro=None, publicador=None) -> dict:
    from sdk.eventos import Publicador, nuevo_evento
    from sdk.registro import Registro

    if not _activada():
        return {"certificacion": "desactivada"}
    tenant, trans = d["tenant"], d["transcripcion"]
    registro = registro or Registro(os.environ["SCORPIO_URL"])
    ent = registro.leer(tenant, trans)
    if not ent or "texto" not in ent:
        raise RuntimeError(f"no encuentro el texto de {trans} en el catastro")
    texto = ent["texto"]["value"]
    previa = leer_evidencia(ent)
    if previa:                       # idempotente: Temporal puede repetir la actividad
        evidencia = previa
    else:
        evidencia = (ejecutar or ejecutar_capacidad)(tenant, {"texto": texto},
                                                      {"anclajes": d.get("anclajes") or _anclajes_por_defecto()})
        prop = lambda v: {"type": "Property", "value": v}  # noqa: E731
        codigo = registro.anadir_atributos(tenant, trans, {
            "huella": prop(evidencia["huella"]),
            "evidencia": prop(json.dumps(evidencia, ensure_ascii=False, separators=(",", ":"))),
            "certificacion": prop(estado_certificacion(evidencia))})
        if codigo not in (204, 207):
            raise RuntimeError(f"el catastro respondió {codigo} al guardar la evidencia")
    carta = nuevo_evento(
        "evidencia.anclada",
        id=str(uuid.uuid5(ESPACIO_IDS, f"evidencia.anclada|{trans}|{evidencia['huella']}")),
        tenant=tenant, subject=trans, source=f"/tenants/{tenant}/servicios/procesos",
        data={"activo": d["activo"], "huella": evidencia["huella"], "certificacion": estado_certificacion(evidencia),
              "anclajes": [{k: a[k] for k in ("proveedor", "modo", "estado")} for a in evidencia["anclajes"]],
              "certificadoPor": os.environ.get("CERTIFICADO_POR", "certificacion-documental@0.1.0")})
    (publicador or Publicador(os.environ["KAFKA_BOOTSTRAP"], client_id="procesos")).publicar(carta)
    return {"certificacion": estado_certificacion(evidencia), "huella": evidencia["huella"], "evento": carta["id"]}


@activity.defn(name="certificar")
async def certificar(d: dict) -> dict:
    """Certifica la transcripción validada y envía evidencia.anclada. No toca la validación: si falla, se reintenta."""
    return await asyncio.to_thread(_certificar, d)
