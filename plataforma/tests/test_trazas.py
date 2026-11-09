"""Las trazas cruzan el catastro y Kafka (exportador en memoria, sin red)."""
import pytest

otel = pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from sdk.registro import entidad_activo  # noqa: E402
from sdk.trazas import traceparent, tramo  # noqa: E402
from services.puente.app import crear_app  # noqa: E402

EXP = InMemorySpanExporter()
_p = TracerProvider()
_p.add_span_processor(SimpleSpanProcessor(EXP))
trace.set_tracer_provider(_p)


def id_traza(tp: str) -> str:
    return tp.split("-")[1]


def test_tramo_hijo_por_traceparent():
    with tramo("entrega"):
        tp = traceparent()
    with tramo("aviso", padre={"traceparent": tp}):
        hijo = traceparent()
    assert id_traza(hijo) == id_traza(tp)


def test_el_puente_continua_la_traza_guardada_en_la_ficha():
    with tramo("ingesta en la sala de lectura"):
        tp = traceparent()
    ficha = entidad_activo("archivo-villanueva", signatura="T-1", ark="ark:/99999/x", manifiesto="http://x/manifest",
                           imagenes=1, ingestado_por="m.ortega", traza=tp)

    class Pub:
        visto = None

        def publicar(self, ev):
            Pub.visto = traceparent()

    r = TestClient(crear_app(Pub())).post("/ngsi-ld/notificaciones/archivo-villanueva",
                                          json={"id": "n", "type": "Notification", "data": [ficha]})
    assert r.status_code == 200
    assert id_traza(Pub.visto) == id_traza(tp)   # misma traza al otro lado del catastro
