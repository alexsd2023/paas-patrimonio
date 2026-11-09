"""FlujoReceta de punta a punta en un Temporal real de pruebas (servicios y catastro simulados).

Necesita el binario de Temporal: TEMPORAL_CLI=/ruta/a/temporal (o lo descarga el SDK si hay red).
"""
import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from services.catalogo.actividades import Actividades
from services.catalogo.catalogo import Catalogo, descubrir
from services.catalogo.flujo import COLA, PROCESO, FlujoReceta
from services.catalogo.recetas import planificar
from capacidades.modernizador_demo.app import procesar as modernizar

A = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"
TEXTO = "En la villa de Villanueva a diez de março de mill e quinientos"


def _http():
    def responder(req: httpx.Request):
        if req.url.host == "srv-modernizador-demo":
            if req.method == "POST":
                cuerpo = json.loads(req.content)
                responder.salida = modernizar(cuerpo["entrada"], cuerpo["parametros"])
                return httpx.Response(202, json={"id": "t1", "estado": "en-cola"})
            return httpx.Response(200, json={"id": "t1", "estado": "terminado", "salida": responder.salida})
        linea = json.loads(req.content)["text"]
        i = linea.find("Villanueva")
        return httpx.Response(200, json=[{"Anotacion": linea, "entities": [
            {"start": i, "end": i + 10, "entity": "Localización", "fields": ["Topónimo"]}]}])
    return httpx.Client(transport=httpx.MockTransport(responder))


class Reg:
    def __init__(self):
        self.creadas = []

    def leer(self, tenant, i):
        if i.startswith("urn:ngsi-ld:Transcripcion:archivo-villanueva:TEST-001"):
            return {"texto": {"type": "Property", "value": TEXTO}}
        return None

    def crear(self, tenant, e):
        self.creadas.append((tenant, e))
        return 201


class Pub:
    def __init__(self):
        self.eventos = []

    def publicar(self, ev):
        self.eventos.append(ev)


async def _entorno():
    from temporalio.testing import WorkflowEnvironment
    cli = os.environ.get("TEMPORAL_CLI")
    if cli:
        return await WorkflowEnvironment.start_local(dev_server_existing_path=cli)
    return await WorkflowEnvironment.start_local()


def test_flujo_de_punta_a_punta(monkeypatch):
    monkeypatch.setenv("NER_TOKEN", "secreto")
    from temporalio.worker import Worker

    async def main():
        try:
            env = await _entorno()
        except RuntimeError as e:
            pytest.skip(f"sin servidor de Temporal de pruebas: {e}")
        cat = Catalogo(descubrir(), http=_http(), sondeo=0.01)
        reg, pub = Reg(), Pub()
        receta = {"nombre": "Modernizar y anotar", "entrada": "transcripcion", "publicar": True,
                  "pasos": [{"servicio": "modernizador-demo"}, {"firma": "paleografa"},
                            {"servicio": "ner-historico"}, {"firma": "paleografa"}]}
        plan = planificar(receta, cat, roles=["archivera"], tenant="archivo-villanueva")
        fid = uuid.uuid4().hex[:12]
        flujo = {"id": fid, "tenant": "archivo-villanueva", "usuario": "m.ortega", "roles": ["archivera"],
                 "plan": plan, "entrada": {"activo": A}}
        async with env, Worker(env.client, task_queue=COLA, workflows=[FlujoReceta],
                               activities=Actividades(cat, reg, pub).todas(),
                               activity_executor=ThreadPoolExecutor(4)):
            h = await env.client.start_workflow(PROCESO, flujo, id=f"flujo:{fid}", task_queue=COLA)

            async def esperar(estado):
                for _ in range(200):
                    e = await h.query("estado")
                    if e["estado"] == estado:
                        return e
                    await asyncio.sleep(0.05)
                raise AssertionError(f"no llegó a {estado}: {e}")

            e = await esperar("esperando-firma")
            assert e["documento"]["texto"].startswith("En la villa de Villanueva a diez de marzo de mil y")
            await h.signal("firmar", {"usuario": "m.ortega", "roles": ["archivera"], "decision": "aprueba"})
            await h.signal("firmar", {"usuario": "paleografa-test", "roles": ["paleografa"], "decision": "aprueba"})
            for _ in range(200):
                e = await h.query("estado")
                if e["estado"] == "esperando-firma" and e["paso"] == 3:
                    break
                await asyncio.sleep(0.05)
            assert e["pasos"][1]["firmadoPor"] == "paleografa-test"  # la firma con otro rol se ignoró
            assert [x["texto"] for x in e["documento"]["entidades"]] == ["Villanueva"]
            await h.signal("firmar", {"usuario": "paleografa-test", "roles": ["paleografa"], "decision": "aprueba"})
            final = await h.result()
        assert final["estado"] == "terminado"
        assert final["resultado"] == f"urn:ngsi-ld:ResultadoFlujo:archivo-villanueva:{fid}"
        tenant, entidad = reg.creadas[0]
        assert entidad["type"] == "ResultadoFlujo" and entidad["deActivo"]["object"] == A
        ev = pub.eventos[0]
        assert ev["type"] == "flujo.completado" and ev["data"]["servicios"][1] == {"servicio": "ner-historico",
                                                                                  "version": "1.3.0"}

    asyncio.run(main())
