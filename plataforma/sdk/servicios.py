"""Servicios del catálogo: la plantilla única con la que cualquiera ofrece un servicio a la plataforma.

Un servicio es una carpeta ``capacidades/<id>/`` con un ``servicio.yaml``. Puede ser:

* **interno**: un contenedor propio que cumple la interfaz estándar. Se escribe en pocas líneas
  con ``crear_servicio(manifiesto, procesar)``, que pone las rutas, la cola de trabajos y las
  comprobaciones de tipos.
* **externo**: una API que ya existe en otro sitio (por ejemplo un Space de Hugging Face). Se
  conecta con un ``adaptador.py`` que traduce el documento común a esa API y de vuelta.

Interfaz estándar (la cumplen los internos; el catálogo la ofrece igual para los externos):

    POST /trabajos            {"entrada": <documento>, "parametros": {...}}  → {"id", "estado"}
    GET  /trabajos/{id}       → {"id", "estado": en-cola|en-curso|terminado|error, "salida"?, "error"?}
    GET  /describir           → el manifiesto
    GET  /salud

Los documentos que entran y salen tienen un tipo común (``contracts/tipos``): así la salida de
un servicio encaja en la entrada del siguiente aunque los hayan escrito personas distintas.
"""
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from jsonschema import Draft202012Validator

RAIZ = Path(__file__).resolve().parents[1]
TIPOS_DIR = RAIZ / "contracts" / "tipos"
_ID = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_SECRETO = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

# Dónde corre una capacidad (las mismas tres etiquetas que los productos del Marketplace):
#   integrada · del equipo del PaaS, dentro de la plataforma (su contenedor, interfaz estándar)
#   alojada   · de un tercero, dentro de la plataforma pero en su propio contenedor aislado (interfaz estándar)
#   externa   · en los servidores de su autor; la plataforma la llama (adaptador) y el texto SALE de la plataforma
MODOS = {"integrada": "Integrada", "alojada": "Alojada en la plataforma", "externa": "Externa"}
ALIAS_MODO = {"interno": "integrada", "externo": "externa"}   # manifiestos anteriores


# ---------------- tipos de documento ----------------

def _cargar_tipos() -> Dict[str, dict]:
    return {p.name.replace(".schema.json", ""): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(TIPOS_DIR.glob("*.schema.json"))}


TIPOS: Dict[str, dict] = _cargar_tipos()
_VALIDADORES = {n: Draft202012Validator(s) for n, s in TIPOS.items()}


def linaje(tipo: str) -> List[str]:
    """transcripcion-anotada → [transcripcion-anotada, transcripcion, texto]"""
    out = []
    while tipo and tipo not in out:
        out.append(tipo)
        tipo = TIPOS.get(tipo, {}).get("x-es-un")
    return out


def encaja(salida: str, entrada: str) -> bool:
    """¿Un documento de tipo `salida` sirve como entrada de tipo `entrada`?"""
    return entrada in linaje(salida)


class DocumentoInvalido(ValueError):
    pass


def validar_documento(tipo: str, doc: Any) -> dict:
    if tipo not in _VALIDADORES:
        raise DocumentoInvalido(f"tipo de documento desconocido: {tipo!r}")
    errs = sorted(_VALIDADORES[tipo].iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errs:
        raise DocumentoInvalido("; ".join(f"{'/'.join(map(str, e.absolute_path)) or '(raíz)'}: {e.message}" for e in errs[:5]))
    return doc


# ---------------- manifiesto ----------------

class ManifiestoInvalido(ValueError):
    pass


@dataclass
class Manifiesto:
    id: str
    nombre: str
    resumen: str
    autor: str
    tipo: str                 # tarea | consulta
    entrada: str
    salida: str
    version: str
    modo: str                 # integrada | alojada | externa (MODOS)
    url: str
    parametros: Dict[str, dict] = field(default_factory=dict)
    acceso: List[str] = field(default_factory=lambda: ["registrado"])
    cuota: Dict[str, int] = field(default_factory=dict)
    externo: Dict[str, Any] = field(default_factory=dict)
    secretos: List[Dict[str, Any]] = field(default_factory=list)   # [{nombre, descripcion, ambito, opcional}]
    carpeta: Optional[Path] = None

    def publico(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in ("id", "nombre", "resumen", "autor", "tipo", "entrada", "salida",
                                              "version", "modo", "parametros", "acceso", "cuota")} | {
            "modo_nombre": MODOS[self.modo], "datos_salen": self.modo == "externa",
            "secretos": [{k: x[k] for k in ("nombre", "descripcion", "ambito", "opcional")} for x in self.secretos]}

    def permite(self, roles: List[str], tenant: str) -> bool:
        """acceso: registrado (cualquiera con sesión) · rol:<rol> · institucion:<tenant>"""
        for regla in self.acceso:
            if regla == "registrado":
                return True
            if regla.startswith("rol:") and regla[4:] in roles:
                return True
            if regla.startswith("institucion:") and regla[12:] == tenant:
                return True
        return False

    def parametros_con_defecto(self, dados: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        dados = dict(dados or {})
        raros = sorted(set(dados) - set(self.parametros))
        if raros:
            raise DocumentoInvalido(f"parámetros desconocidos para {self.id}: {raros}")
        out = {}
        for nombre, d in self.parametros.items():
            v = dados.get(nombre, d.get("defecto"))
            if v is None and d.get("obligatorio"):
                raise DocumentoInvalido(f"falta el parámetro {nombre!r}")
            valores = d.get("valores")
            if valores and v is not None:
                lista = v if isinstance(v, list) else [v]
                fuera = [x for x in lista if x not in valores]
                if fuera:
                    raise DocumentoInvalido(f"{nombre}: {fuera} no está entre {valores}")
            out[nombre] = v
        return out


def leer_manifiesto(datos: Dict[str, Any], carpeta: Optional[Path] = None) -> Manifiesto:
    e = []
    sid = str(datos.get("id", ""))
    if not _ID.match(sid):
        e.append("id: minúsculas, cifras y guiones")
    if carpeta is not None and carpeta.name not in (sid, sid.replace("-", "_")):
        e.append(f"la carpeta debe llamarse {sid.replace('-', '_')}")
    for k in ("nombre", "resumen", "autor"):
        if not str(datos.get(k, "")).strip():
            e.append(f"falta {k}")
    if datos.get("tipo") not in ("tarea", "consulta"):
        e.append("tipo: tarea | consulta")
    for k in ("entrada", "salida"):
        if datos.get(k) not in TIPOS:
            e.append(f"{k}: uno de {sorted(TIPOS)}")
    if not _VERSION.match(str(datos.get("version", ""))):
        e.append("version: X.Y.Z")
    modo = ALIAS_MODO.get(datos.get("modo", "integrada"), datos.get("modo"))
    if modo not in MODOS:
        e.append("modo: " + " | ".join(MODOS))
    if modo == "externa" and not datos.get("url"):
        e.append("una capacidad externa necesita url")
    for regla in datos.get("acceso", ["registrado"]):
        if not (regla == "registrado" or str(regla).startswith(("rol:", "institucion:"))):
            e.append(f"acceso: {regla!r} no es registrado, rol:<rol> ni institucion:<id>")
    secretos = []
    for x in datos.get("secretos") or []:
        x = {"nombre": str((x or {}).get("nombre", "")), "descripcion": str((x or {}).get("descripcion", "")),
             "ambito": str((x or {}).get("ambito", "ambos")), "opcional": bool((x or {}).get("opcional", False))}
        if not _SECRETO.match(x["nombre"]):
            e.append(f"secretos: {x['nombre']!r} debe ir en MAYÚSCULAS_CON_GUIONES_BAJOS")
        if x["ambito"] not in ("plataforma", "institucion", "ambos"):
            e.append(f"secretos: ámbito de {x['nombre']} debe ser plataforma | institucion | ambos")
        secretos.append(x)
    token_env = (datos.get("externo") or {}).get("token_env")
    if token_env and not any(x["nombre"] == token_env for x in secretos):
        # compatibilidad: el token de un externo es un secreto aunque el manifiesto no lo declare
        secretos.append({"nombre": str(token_env), "descripcion": "Token de la API externa", "ambito": "ambos",
                         "opcional": False})
    if e:
        raise ManifiestoInvalido(f"servicio {sid or carpeta}: " + "; ".join(e))
    url = str(datos.get("url") or f"http://srv-{sid}:8080").rstrip("/")
    return Manifiesto(id=sid, nombre=datos["nombre"], resumen=datos["resumen"], autor=datos["autor"],
                      tipo=datos["tipo"], entrada=datos["entrada"], salida=datos["salida"],
                      version=str(datos["version"]), modo=modo, url=url,
                      parametros=dict(datos.get("parametros") or {}), acceso=list(datos.get("acceso") or ["registrado"]),
                      cuota=dict(datos.get("cuota") or {}), externo=dict(datos.get("externo") or {}),
                      secretos=secretos, carpeta=carpeta)


def cargar(ruta: Path) -> Manifiesto:
    import yaml
    ruta = Path(ruta)
    yml = ruta / "servicio.yaml" if ruta.is_dir() else ruta
    return leer_manifiesto(yaml.safe_load(yml.read_text(encoding="utf-8")) or {}, yml.parent)


# ---------------- servicio interno: la interfaz estándar ----------------

def crear_servicio(manifiesto: Manifiesto, procesar: Callable[[dict, Dict[str, Any]], dict]):
    """Una app FastAPI con la interfaz estándar. `procesar(entrada, parametros) -> salida`.

    Los trabajos se procesan de uno en uno en un hilo; el estado vive en memoria
    (suficiente para el walking skeleton: el motor de flujos reintenta si el servicio se reinicia).
    """
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title=manifiesto.nombre, version=manifiesto.version, docs_url="/docs")
    trabajos: Dict[str, Dict[str, Any]] = {}
    cola: List[str] = []
    hay = threading.Condition()

    def obrero():
        while True:
            with hay:
                while not cola:
                    hay.wait()
                tid = cola.pop(0)
            t = trabajos[tid]
            t["estado"] = "en-curso"
            try:
                salida = procesar(t.pop("_entrada"), t.pop("_parametros"))
                t["salida"] = validar_documento(manifiesto.salida, salida)
                t["estado"] = "terminado"
            except Exception as ex:  # noqa: BLE001  el error es parte de la respuesta
                t["estado"], t["error"] = "error", str(ex)
            t["terminado"] = time.time()

    threading.Thread(target=obrero, daemon=True, name="obrero").start()

    @app.get("/salud")
    def salud():
        return {"ok": True, "servicio": manifiesto.id, "version": manifiesto.version}

    @app.get("/describir")
    def describir():
        return manifiesto.publico()

    @app.post("/trabajos", status_code=202)
    def nuevo(peticion: Dict[str, Any] = Body(...)):
        try:
            entrada = validar_documento(manifiesto.entrada, peticion.get("entrada"))
            params = manifiesto.parametros_con_defecto(peticion.get("parametros"))
        except DocumentoInvalido as ex:
            raise HTTPException(422, str(ex))
        tid = uuid.uuid4().hex[:16]
        trabajos[tid] = {"id": tid, "estado": "en-cola", "servicio": manifiesto.id, "version": manifiesto.version,
                         "creado": time.time(), "_entrada": entrada, "_parametros": params}
        with hay:
            cola.append(tid)
            hay.notify()
        return {"id": tid, "estado": "en-cola"}

    @app.get("/trabajos/{tid}")
    def ver(tid: str):
        t = trabajos.get(tid)
        if not t:
            raise HTTPException(404, "no existe ese trabajo")
        return {k: v for k, v in t.items() if not k.startswith("_")}

    return app
