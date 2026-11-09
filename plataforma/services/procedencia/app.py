"""Procedencia · el notario (tramos 11–12 del caso).

Escucha todas las cartas del bus y levanta acta en PROV-O de cada una: qué pasó,
cuándo, qué servicio lo hizo, qué persona intervino y qué modelo produjo cada copia.

Dónde guarda el libro:
  · Fuseki (parte 10): un grafo con nombre por institución, <urn:paas:grafo:<tenant>>,
    consultable con SPARQL desde fuera.             → FUSEKI_URL definido
  · un fichero Turtle local (tests, o sin Fuseki).   → PROCEDENCIA_RUTA

    GET /actas?activo=<urn>   actas de un legajo (o de un depósito), en orden
    GET /prov.ttl             el grafo completo
    GET /salud
"""
import base64
import json
import logging
import os
import re
import threading
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, XSD

from sdk.servicio import lanzar_consumidor
from sdk.trazas import configurar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("procedencia")

PAAS = Namespace("https://paas-patrimonio.example/ns#")
AGENTES = "https://paas-patrimonio.example/agentes"
URN = re.compile(r"^urn:ngsi-ld:[A-Za-z]+:[a-z0-9-]+:[A-Za-z0-9-]+$")
PREFIJOS = f"PREFIX prov: <{PROV}>\nPREFIX paas: <{PAAS}>\nPREFIX xsd: <{XSD}>\n"
CUERPO_ACTAS = """
    ?act paas:sobre {activo} ; paas:tipoActa ?tipo ; prov:endedAtTime ?t .
    OPTIONAL {{ ?act prov:wasAssociatedWith ?ag }}
    OPTIONAL {{ ?act paas:detalle ?d }}"""
SELECT_ACTAS = """SELECT ?act ?tipo ?t (SAMPLE(?d) AS ?detalle) (GROUP_CONCAT(STR(?ag); separator=" ") AS ?agentes)
WHERE {{ {cuerpo} }} GROUP BY ?act ?tipo ?t ORDER BY ?t"""


def actividad(ev: dict) -> URIRef:
    return URIRef(f"urn:uuid:{ev['id']}")


def tripletas(ev: dict) -> Graph:
    """El acta de un evento como grafo PROV-O (puro: sin red ni almacén)."""
    g, act = Graph(), actividad(ev)
    tenant, data = ev["tenant"], ev.get("data") or {}
    g.add((act, RDF.type, PROV.Activity))
    g.add((act, RDFS.label, Literal(ev["type"])))
    g.add((act, PROV.endedAtTime, Literal(ev["time"], datatype=XSD.dateTime)))
    g.add((act, PAAS.tenant, Literal(tenant)))
    emisor = URIRef(AGENTES + ev["source"])
    g.add((emisor, RDF.type, PROV.SoftwareAgent))
    g.add((act, PROV.wasAssociatedWith, emisor))

    if ev["type"] == "legajo.ingestado":
        activo = URIRef(ev["subject"])
        persona = URIRef(f"urn:paas:usuario:{tenant}:{data['ingestadoPor']}")
        g.add((act, PAAS.tipoActa, Literal("ingreso")))
        g.add((act, PAAS.sobre, activo))
        g.add((activo, RDF.type, PROV.Entity))
        g.add((persona, RDF.type, PROV.Person))
        g.add((act, PROV.wasAssociatedWith, persona))
    elif ev["type"] == "htr.completado":
        trans, activo = URIRef(ev["subject"]), URIRef(data["activo"])
        modelo = URIRef(f"urn:paas:modelo:{data['modelo']}")
        g.add((act, PAAS.tipoActa, Literal("htr")))
        g.add((act, PAAS.sobre, activo))
        g.add((act, PROV.used, activo))
        g.add((trans, RDF.type, PROV.Entity))
        g.add((trans, PROV.wasGeneratedBy, act))
        g.add((trans, PROV.wasDerivedFrom, activo))
        g.add((modelo, RDF.type, PROV.SoftwareAgent))
        g.add((act, PROV.wasAssociatedWith, modelo))
        # tramos 14–16: el modelo es también una entidad que sale de un entrenamiento (run) sobre unos datos
        detalle = [f"modelo {data['modelo']}"]
        if data.get("datosVersion"):
            datos = URIRef(f"urn:paas:datos:{data['datosVersion']}")
            g.add((datos, RDF.type, PROV.Entity))
            g.add((modelo, RDF.type, PROV.Entity))
            g.add((modelo, PROV.wasDerivedFrom, datos))
            detalle.append(f"datos {data['datosVersion'][:10]}")
        if data.get("modeloRun"):
            entreno = URIRef(f"urn:paas:mlflow:run:{data['modeloRun']}")
            g.add((entreno, RDF.type, PROV.Activity))
            g.add((modelo, PROV.wasGeneratedBy, entreno))
            detalle.append(f"run {data['modeloRun'][:8]}")
        if data.get("cerModelo") is not None:
            g.add((modelo, PAAS.cer, Literal(data["cerModelo"], datatype=XSD.decimal)))
            detalle.append(f"CER {data['cerModelo']:.3f}")
        g.add((act, PAAS.detalle, Literal(" · ".join(detalle))))
    elif ev["type"] == "transcripcion.validada":
        trans, activo = URIRef(ev["subject"]), URIRef(data["activo"])
        persona = URIRef(f"urn:paas:usuario:{tenant}:{data['validadoPor']}")
        g.add((act, PAAS.tipoActa, Literal("validacion")))
        g.add((act, PAAS.sobre, activo))
        g.add((act, PROV.used, trans))
        g.add((persona, RDF.type, PROV.Person))
        g.add((act, PROV.wasAssociatedWith, persona))
        g.add((trans, PROV.wasAttributedTo, persona))
    elif ev["type"] in ("conservacion.alerta", "conservacion.normalizada"):
        dep = URIRef(ev["subject"])
        alerta = ev["type"] == "conservacion.alerta"
        unidad = "°C" if data["variable"] == "temperatura" else "%"
        detalle = f"{data.get('nombre', '')}: {data['variable']} {data['valor']} {unidad}"
        if alerta:
            detalle += f" ({'máx.' if data.get('sentido') == 'alta' else 'mín.'} {data['limite']} {unidad})"
        g.add((act, PAAS.tipoActa, Literal("alerta-conservacion" if alerta else "fin-alerta")))
        g.add((act, PAAS.detalle, Literal(detalle)))
        g.add((act, PAAS.sobre, dep))
        g.add((dep, RDF.type, PROV.Entity))
        for leg in data.get("legajos", []):  # consta también en el libro de cada legajo afectado
            g.add((act, PAAS.sobre, URIRef(leg)))
    else:
        g.add((act, PAAS.tipoActa, Literal(ev["type"])))
        g.add((act, PAAS.sobre, URIRef(ev["subject"])))
    return g


def _fila(act, tipo, t, detalle, agentes) -> dict:
    return {"evento": str(act).replace("urn:uuid:", ""), "tipo": str(tipo), "tiempo": str(t),
            "agentes": sorted(str(agentes or "").split()), **({"detalle": str(detalle)} if detalle else {})}


class Registro:
    """Libro en memoria, guardado en un fichero Turtle (tests, o sin Fuseki)."""

    almacen = "fichero"

    def __init__(self, ruta: Optional[str] = None):
        self.g = Graph()
        self.g.bind("prov", PROV)
        self.g.bind("paas", PAAS)
        self.ruta = Path(ruta) if ruta else None
        self._lock = threading.Lock()
        if self.ruta and self.ruta.exists():
            self.g.parse(self.ruta, format="turtle")
            log.info("cargadas %d tripletas de %s", len(self.g), self.ruta)

    def anotar(self, ev: dict) -> bool:
        """Levanta acta del evento. Devuelve False si ya constaba (evento repetido)."""
        with self._lock:
            if (actividad(ev), RDF.type, PROV.Activity) in self.g:
                return False
            self.g += tripletas(ev)
            if self.ruta:
                tmp = self.ruta.with_suffix(".tmp")
                self.g.serialize(tmp, format="turtle")
                tmp.replace(self.ruta)
        log.info("acta %s %s", ev["type"], ev["subject"])
        return True

    def actas(self, activo: str) -> List[dict]:
        """Actas de una entidad (un legajo o un depósito), en orden."""
        q = SELECT_ACTAS.format(cuerpo=CUERPO_ACTAS.format(activo="?activo"))
        with self._lock:
            filas = self.g.query(q, initNs={"paas": PAAS, "prov": PROV}, initBindings={"activo": URIRef(activo)})
        return [_fila(f.act, f.tipo, f.t, f.detalle, f.agentes) for f in filas]

    def turtle(self) -> str:
        with self._lock:
            return self.g.serialize(format="turtle")

    def tamano(self) -> int:
        return len(self.g)


class RegistroFuseki:
    """Libro en Jena Fuseki: un grafo con nombre por institución."""

    almacen = "fuseki"

    def __init__(self, url: str, dataset: str = "paas", usuario: Optional[str] = None, clave: Optional[str] = None,
                 enviar=None):
        self.base = f"{url.rstrip('/')}/{dataset}"
        self._auth = ("Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()) if usuario else None
        self._enviar = enviar or self._http

    @staticmethod
    def grafo(tenant: str) -> str:
        return f"urn:paas:grafo:{tenant}"

    def _http(self, servicio: str, campo: str, texto: str, acepta: str) -> bytes:
        cab = {"Content-Type": "application/x-www-form-urlencoded", "Accept": acepta}
        if self._auth:
            cab["Authorization"] = self._auth
        req = urllib.request.Request(f"{self.base}/{servicio}", data=urllib.parse.urlencode({campo: texto}).encode(),
                                     method="POST", headers=cab)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()

    def _select(self, q: str) -> list:
        res = json.loads(self._enviar("query", "query", PREFIJOS + q, "application/sparql-results+json"))
        return [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]

    def _ask(self, q: str) -> bool:
        return json.loads(self._enviar("query", "query", PREFIJOS + q, "application/sparql-results+json"))["boolean"]

    def anotar(self, ev: dict) -> bool:
        g = self.grafo(ev["tenant"])
        if self._ask(f"ASK {{ GRAPH <{g}> {{ <{actividad(ev)}> a prov:Activity }} }}"):
            return False
        nt = tripletas(ev).serialize(format="nt")
        self._enviar("update", "update", f"INSERT DATA {{ GRAPH <{g}> {{\n{nt}\n}} }}", "text/plain")
        log.info("acta %s %s → %s", ev["type"], ev["subject"], g)
        return True

    def actas(self, activo: str) -> List[dict]:
        if not URN.match(activo):
            raise ValueError(activo)
        cuerpo = f"GRAPH <{self.grafo(activo.split(':')[3])}> {{ {CUERPO_ACTAS.format(activo=f'<{activo}>')} }}"
        filas = self._select(SELECT_ACTAS.format(cuerpo=cuerpo))
        return [_fila(f["act"], f["tipo"], f["t"], f.get("detalle"), f.get("agentes")) for f in filas]

    def turtle(self) -> str:
        q = "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }"
        return self._enviar("query", "query", PREFIJOS + q, "text/turtle").decode()

    def tamano(self) -> int:
        f = self._select("SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }")
        return int(f[0]["n"]) if f else 0


def crear_app(registro, bootstrap: Optional[str] = None, grupo: str = "procedencia") -> FastAPI:
    estado: dict = {}

    @asynccontextmanager
    async def ciclo(app):
        if bootstrap:
            lanzar_consumidor(bootstrap=bootstrap, grupo=grupo, topics=["activos", "htr", "conservacion"],
                              manejar=registro.anotar, estado=estado)
        yield

    app = FastAPI(title="Procedencia (PROV-O)", version="0.3.0", lifespan=ciclo)

    @app.get("/salud")
    def salud():
        try:
            n = registro.tamano()
        except OSError as e:
            n = f"no disponible: {e}"
        return {"ok": True, "almacen": registro.almacen, "consumidor": estado, "tripletas": n}

    @app.get("/actas")
    def actas(activo: str = Query(..., pattern=URN.pattern)):  # legajo o depósito
        try:
            return registro.actas(activo)
        except OSError as e:
            raise HTTPException(503, f"el almacén del notario no responde: {e}")

    @app.get("/prov.ttl", response_class=PlainTextResponse)
    def prov():
        return PlainTextResponse(registro.turtle(), media_type="text/turtle")

    return app


def _crear() -> FastAPI:
    fuseki = os.environ.get("FUSEKI_URL")
    if fuseki:
        reg = RegistroFuseki(fuseki, os.environ.get("FUSEKI_DATASET", "paas"),
                             os.environ.get("FUSEKI_USUARIO"), os.environ.get("FUSEKI_CLAVE"))
        # Grupo de lectura nuevo: al estrenar Fuseki, el notario relee las cartas que Kafka aún guarda
        return crear_app(reg, os.environ.get("KAFKA_BOOTSTRAP"), grupo="procedencia-fuseki")
    return crear_app(Registro(os.environ.get("PROCEDENCIA_RUTA")), os.environ.get("KAFKA_BOOTSTRAP"))


app = _crear()
configurar("procedencia", app)
