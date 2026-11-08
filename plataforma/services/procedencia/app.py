"""Procedencia · el notario (tramos 11–12 del caso).

Escucha todas las cartas del bus y levanta acta en PROV-O de cada una: qué pasó,
cuándo, qué servicio lo hizo, qué persona intervino y qué modelo produjo cada copia.

Hoy guarda el grafo en un fichero Turtle; en el paso 5 del plan se escribe en
Jena Fuseki. Las consultas ya son SPARQL, así que no cambian.

    GET /actas?activo=<urn>   actas de un legajo, en orden
    GET /prov.ttl             el grafo completo
    GET /salud
"""
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, XSD

from sdk.servicio import lanzar_consumidor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("procedencia")

PAAS = Namespace("https://paas-patrimonio.example/ns#")
AGENTES = "https://paas-patrimonio.example/agentes"


class Registro:
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
        g, act = self.g, URIRef(f"urn:uuid:{ev['id']}")
        with self._lock:
            if (act, RDF.type, PROV.Activity) in g:
                return False
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
            elif ev["type"] == "transcripcion.validada":
                trans, activo = URIRef(ev["subject"]), URIRef(data["activo"])
                persona = URIRef(f"urn:paas:usuario:{tenant}:{data['validadoPor']}")
                g.add((act, PAAS.tipoActa, Literal("validacion")))
                g.add((act, PAAS.sobre, activo))
                g.add((act, PROV.used, trans))
                g.add((persona, RDF.type, PROV.Person))
                g.add((act, PROV.wasAssociatedWith, persona))
                g.add((trans, PROV.wasAttributedTo, persona))
            else:
                g.add((act, PAAS.tipoActa, Literal(ev["type"])))
                g.add((act, PAAS.sobre, URIRef(ev["subject"])))

            if self.ruta:
                tmp = self.ruta.with_suffix(".tmp")
                g.serialize(tmp, format="turtle")
                tmp.replace(self.ruta)
        log.info("acta %s %s", ev["type"], ev["subject"])
        return True

    def actas(self, activo: str) -> List[dict]:
        q = """
        SELECT ?act ?tipo ?t (GROUP_CONCAT(STR(?ag); separator=" ") AS ?agentes) WHERE {
            ?act paas:sobre ?activo ; paas:tipoActa ?tipo ; prov:endedAtTime ?t .
            OPTIONAL { ?act prov:wasAssociatedWith ?ag }
        } GROUP BY ?act ?tipo ?t ORDER BY ?t"""
        with self._lock:
            filas = self.g.query(q, initNs={"paas": PAAS, "prov": PROV},
                                 initBindings={"activo": URIRef(activo)})
        return [{"evento": str(f.act).replace("urn:uuid:", ""), "tipo": str(f.tipo),
                 "tiempo": str(f.t), "agentes": sorted(str(f.agentes).split())} for f in filas]

    def turtle(self) -> str:
        with self._lock:
            return self.g.serialize(format="turtle")


def crear_app(registro: Registro, bootstrap: Optional[str] = None) -> FastAPI:
    estado: dict = {}

    @asynccontextmanager
    async def ciclo(app):
        if bootstrap:
            lanzar_consumidor(bootstrap=bootstrap, grupo="procedencia", topics=["activos", "htr"],
                              manejar=registro.anotar, estado=estado)
        yield

    app = FastAPI(title="Procedencia (PROV-O)", version="0.1.0", lifespan=ciclo)

    @app.get("/salud")
    def salud():
        return {"ok": True, "consumidor": estado, "tripletas": len(registro.g)}

    @app.get("/actas")
    def actas(activo: str = Query(..., pattern=r"^urn:ngsi-ld:[A-Za-z]+:[a-z0-9-]+:[A-Za-z0-9-]+$")):
        return registro.actas(activo)

    @app.get("/prov.ttl", response_class=PlainTextResponse)
    def prov():
        return PlainTextResponse(registro.turtle(), media_type="text/turtle")

    return app


app = crear_app(Registro(os.environ.get("PROCEDENCIA_RUTA")), os.environ.get("KAFKA_BOOTSTRAP"))
