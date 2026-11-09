"""Cómo se enchufa un producto a la consola del núcleo.

Un producto es una carpeta en ``productos/<id>/`` con dos cosas:

* ``producto.yaml``: quién es (nombre, color, resumen), qué usa del núcleo, qué capacidades requiere,
  qué contenedores y buzones
  son suyos, y qué vistas tiene. La consola lo lee para pintar la barra lateral y el catálogo.
* ``__init__.py`` con ``montar(nucleo, producto) -> APIRouter``: sus vistas y su API. La consola lo monta
  en ``/panel/productos/<id>``. Todo lo que el producto necesita del PaaS le llega por ``nucleo``
  (identidad, catastro, procesos, notario, la plantilla de la consola); no importa nada del panel.

Así queda separado lo que es del PaaS (este paquete, ``sdk/`` y los servicios comunes) de lo que
es de cada producto. Un producto nuevo no toca el núcleo: añade su carpeta y la consola lo descubre.
"""
import importlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

log = logging.getLogger("panel.productos")

# Las piezas del núcleo que un producto puede declarar en «usa». Son las mismas en todos los productos.
PIEZAS_NUCLEO = {
    "identidad": "Identidad · Keycloak",
    "puerta": "Puerta · APISIX",
    "correos": "Correos · Kafka",
    "catastro": "Catastro · Scorpio",
    "procesos": "Procesos · Temporal",
    "notario": "Notario · Fuseki",
    "trazas": "Trazas · Jaeger",
    "imagenes": "Imágenes · IIIF",
    "servicios": "Servicios · catálogo y flujos",
    "modelos": "Modelos · MLflow",
}
CARPETA = Path(os.environ.get("PRODUCTOS_DIR", Path(__file__).resolve().parents[2] / "productos"))
_ID = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ProductoInvalido(ValueError):
    pass


@dataclass
class Vista:
    id: str
    nombre: str
    ruta: str  # relativa al producto: "" es la vista de entrada


@dataclass
class Producto:
    id: str
    nombre: str
    color: str
    resumen: str
    usa: List[str]
    contenedores: List[str] = field(default_factory=list)
    requiere: List[str] = field(default_factory=list)
    buzones: List[str] = field(default_factory=list)
    vistas: List[Vista] = field(default_factory=list)
    tramos: List[Dict[str, Any]] = field(default_factory=list)
    estado: str = "conectado"
    montar: Optional[Callable] = None

    @property
    def base(self) -> str:
        return f"/panel/productos/{self.id}"

    def url(self, vista: str = "") -> str:
        v = next((x for x in self.vistas if x.id == vista), None)
        return self.base + (f"/{v.ruta}" if v and v.ruta else "")

    def ficha(self) -> Dict[str, Any]:
        """Lo que se publica del producto (catálogo y API)."""
        return {"id": self.id, "nombre": self.nombre, "color": self.color, "resumen": self.resumen,
                "usa": self.usa, "requiere": self.requiere, "contenedores": self.contenedores, "buzones": self.buzones, "estado": self.estado,
                "url": self.base, "vistas": [{"id": v.id, "nombre": v.nombre, "url": self.url(v.id)} for v in self.vistas]}


def leer_manifiesto(datos: Dict[str, Any], id_carpeta: str) -> Producto:
    """Valida un producto.yaml y lo convierte en Producto. Los errores dicen qué falta, para quien lo escribe."""
    errores = []
    cid = datos.get("id", id_carpeta)
    if cid != id_carpeta:
        errores.append(f"id {cid!r} no coincide con la carpeta {id_carpeta!r}")
    if not _ID.match(str(cid)):
        errores.append("id: minúsculas, cifras y guiones")
    for k in ("nombre", "resumen"):
        if not str(datos.get(k, "")).strip():
            errores.append(f"falta {k}")
    color = str(datos.get("color", ""))
    if not _COLOR.match(color):
        errores.append("color: #RRGGBB")
    usa = [str(u) for u in datos.get("usa", [])]
    raras = [u for u in usa if u not in PIEZAS_NUCLEO]
    if raras:
        errores.append(f"usa: {raras} no son piezas del núcleo ({', '.join(PIEZAS_NUCLEO)})")
    vistas = []
    for n, v in enumerate(datos.get("vistas", [])):
        if not isinstance(v, dict) or not v.get("id") or not v.get("nombre"):
            errores.append(f"vistas[{n}]: necesita id y nombre")
            continue
        vistas.append(Vista(str(v["id"]), str(v["nombre"]), str(v.get("ruta", ""))))
    if not vistas:
        errores.append("vistas: al menos una")
    if errores:
        raise ProductoInvalido(f"productos/{id_carpeta}/producto.yaml: " + "; ".join(errores))
    return Producto(id=cid, nombre=datos["nombre"], color=color, resumen=datos["resumen"], usa=usa,
                contenedores=[str(x) for x in datos.get("contenedores", datos.get("servicios", []))],
                requiere=[str(x) for x in datos.get("requiere", [])],
                buzones=[str(b) for b in datos.get("buzones", [])], vistas=vistas,
                tramos=list(datos.get("tramos", [])), estado=str(datos.get("estado", "conectado")))


def descubrir(carpeta: Path = CARPETA, paquete: str = "productos") -> List[Producto]:
    """Todos los productos de ``productos/*/producto.yaml``, en el orden que pida cada uno (``orden``)."""
    encontrados = []
    for yml in sorted(Path(carpeta).glob("*/producto.yaml")):
        cid = yml.parent.name
        try:
            datos = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
            producto = leer_manifiesto(datos, cid)
            if producto.estado == "conectado":
                producto.montar = getattr(importlib.import_module(f"{paquete}.{cid}"), "montar")
            encontrados.append((datos.get("orden", 99), producto))
        except Exception as e:  # un producto roto no tumba la consola: se avisa y se sigue
            log.error("No se pudo cargar el producto %s: %s", cid, e)
    return [c for _, c in sorted(encontrados, key=lambda x: (x[0], x[1].id))]
