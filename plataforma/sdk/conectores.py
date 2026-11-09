"""Conectores: traen a la plataforma lo que la institución ya tiene en otros sistemas (o lo llevan allí).

Un conector es una carpeta ``conectores/<id>/`` con:

* ``conector.yaml``: quién es, qué configuración pide a cada institución (un formulario en la
  consola), qué escribe en el catastro y quién puede usarlo.
* ``conector.py`` con ``ejecutar(config, ctx) -> resumen``. ``ctx`` le da lo que necesita del núcleo
  (catastro de la institución, cliente HTTP, un registro de avance); el conector no conoce nada más.

Lo ejecuta el catálogo (núcleo), a petición desde la consola o la API, y guarda cada ejecución.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_ID = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
TIPOS_CAMPO = ("texto", "url", "entero", "booleano", "lista")


class ConectorInvalido(ValueError):
    pass


class ConfiguracionInvalida(ValueError):
    pass


@dataclass
class Conector:
    id: str
    nombre: str
    resumen: str
    autor: str
    sentido: str                      # entrada (trae datos al catastro) | salida (los lleva fuera)
    version: str
    configuracion: Dict[str, dict] = field(default_factory=dict)
    escribe: List[str] = field(default_factory=list)
    acceso: List[str] = field(default_factory=lambda: ["registrado"])
    carpeta: Optional[Path] = None

    def publico(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in ("id", "nombre", "resumen", "autor", "sentido", "version",
                                              "configuracion", "escribe", "acceso")}

    def permite(self, roles: List[str], tenant: str) -> bool:
        for regla in self.acceso:
            if regla == "registrado" or (regla.startswith("rol:") and regla[4:] in roles) \
                    or (regla.startswith("institucion:") and regla[12:] == tenant):
                return True
        return False

    def validar_configuracion(self, dada: Dict[str, Any]) -> Dict[str, Any]:
        dada = dict(dada or {})
        raros = sorted(set(dada) - set(self.configuracion))
        if raros:
            raise ConfiguracionInvalida(f"campos desconocidos: {raros}")
        out, errores = {}, []
        for nombre, d in self.configuracion.items():
            v = dada.get(nombre, d.get("defecto"))
            if v in (None, "") and d.get("obligatorio"):
                errores.append(f"falta {nombre}")
                continue
            if v in (None, ""):
                out[nombre] = None
                continue
            tipo = d.get("tipo", "texto")
            try:
                if tipo == "entero":
                    v = int(v)
                    if "minimo" in d and v < d["minimo"] or "maximo" in d and v > d["maximo"]:
                        errores.append(f"{nombre}: entre {d.get('minimo')} y {d.get('maximo')}")
                elif tipo == "booleano":
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "si", "sí", "on")
                elif tipo == "url":
                    v = str(v).strip()
                    if not re.match(r"^https?://[^\s]+$", v):
                        errores.append(f"{nombre}: una URL http(s)://")
                elif tipo == "lista":
                    v = v if isinstance(v, list) else [x.strip() for x in str(v).split(",") if x.strip()]
                else:
                    v = str(v).strip()
            except (TypeError, ValueError):
                errores.append(f"{nombre}: debe ser {tipo}")
                continue
            if d.get("valores") and v not in d["valores"]:
                errores.append(f"{nombre}: uno de {d['valores']}")
            out[nombre] = v
        if errores:
            raise ConfiguracionInvalida("; ".join(errores))
        return out


def leer_manifiesto(datos: Dict[str, Any], carpeta: Optional[Path] = None) -> Conector:
    e = []
    cid = str(datos.get("id", ""))
    if not _ID.match(cid):
        e.append("id: minúsculas, cifras y guiones")
    if carpeta is not None and carpeta.name not in (cid, cid.replace("-", "_")):
        e.append(f"la carpeta debe llamarse {cid.replace('-', '_')}")
    for k in ("nombre", "resumen", "autor", "version"):
        if not str(datos.get(k, "")).strip():
            e.append(f"falta {k}")
    if datos.get("sentido") not in ("entrada", "salida"):
        e.append("sentido: entrada | salida")
    conf = datos.get("configuracion") or {}
    for nombre, d in conf.items():
        if not isinstance(d, dict) or d.get("tipo", "texto") not in TIPOS_CAMPO:
            e.append(f"configuracion.{nombre}: tipo uno de {TIPOS_CAMPO}")
    if e:
        raise ConectorInvalido(f"conector {cid or carpeta}: " + "; ".join(e))
    return Conector(id=cid, nombre=datos["nombre"], resumen=datos["resumen"], autor=datos["autor"],
                    sentido=datos["sentido"], version=str(datos["version"]), configuracion=conf,
                    escribe=list(datos.get("escribe") or []), acceso=list(datos.get("acceso") or ["registrado"]),
                    carpeta=carpeta)


def cargar(ruta: Path) -> Conector:
    import yaml
    ruta = Path(ruta)
    yml = ruta / "conector.yaml" if ruta.is_dir() else ruta
    return leer_manifiesto(yaml.safe_load(yml.read_text(encoding="utf-8")) or {}, yml.parent)


@dataclass
class Contexto:
    """Lo que el núcleo pone en manos de un conector durante una ejecución."""
    tenant: str
    registro: Any                          # catastro (sdk.registro.Registro): solo esta institución
    http: Any                              # httpx.Client
    avance: Callable[[str], None] = lambda _m: None
    detener: Callable[[], bool] = lambda: False

    def inscribir(self, entidad: Dict[str, Any]) -> str:
        """Crea la entidad o, si ya existe, actualiza sus atributos. Devuelve «nueva» o «actualizada»."""
        estado = self.registro.crear(self.tenant, entidad)
        if estado == 201:
            return "nueva"
        if estado == 409:
            attrs = {k: v for k, v in entidad.items() if k not in ("id", "type")}
            r = self.registro.anadir_atributos(self.tenant, entidad["id"], attrs)
            if r in (204, 207):
                return "actualizada"
            raise RuntimeError(f"el catastro respondió {r} al actualizar {entidad['id']}")
        raise RuntimeError(f"el catastro respondió {estado} al inscribir {entidad['id']}")
