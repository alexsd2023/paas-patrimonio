"""Trazas (OpenTelemetry → Jaeger): el recorrido de un legajo como una sola traza.

El contexto de la traza (cabecera W3C «traceparent») viaja por cuatro caminos:
  · HTTP     → instrumentación de FastAPI, urllib y httpx (automática)
  · Kafka    → cabecera traceparent de cada carta (sdk.eventos)
  · Temporal → interceptor de OpenTelemetry de Temporal (gestoría y trabajador)
  · catastro → Scorpio no lo propaga en sus avisos: el adaptador IIIF guarda el
               traceparent en la ficha del legajo («traza») y el puente lo retoma.

Sin OTEL_EXPORTER_OTLP_ENDPOINT (tests, scripts) todo esto no hace nada.
"""
import os
from contextlib import contextmanager
from typing import Dict, Optional

try:
    from opentelemetry import context as _ctx
    from opentelemetry import propagate, trace
    from opentelemetry.trace import SpanKind
    HAY_OTEL = True
except ImportError:  # sin OpenTelemetry instalado: no-op
    HAY_OTEL = False

_configurado = False


def configurar(servicio: str, app=None) -> None:
    """Activa las trazas del proceso (una vez) e instrumenta la app web que se le pase.
    El nombre del servicio lo manda OTEL_SERVICE_NAME si está definido (un módulo puede
    importarse dentro de otro servicio: el panel importa la gestoría)."""
    global _configurado
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not (HAY_OTEL and endpoint):
        return
    if not _configurado:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        nombre = os.environ.get("OTEL_SERVICE_NAME", servicio)
        proveedor = TracerProvider(resource=Resource.create({"service.name": nombre}))
        proveedor.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
        trace.set_tracer_provider(proveedor)
        try:
            from opentelemetry.instrumentation.urllib import URLLibInstrumentor
            URLLibInstrumentor().instrument()
        except ImportError:
            pass
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except ImportError:
            pass
        _configurado = True
    if app is not None and not getattr(app.state, "trazas", False):
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, excluded_urls="salud")
        app.state.trazas = True


def inyectar(cabeceras: Dict[str, str]) -> Dict[str, str]:
    if HAY_OTEL:
        propagate.inject(cabeceras)
    return cabeceras


def traceparent() -> Optional[str]:
    return inyectar({}).get("traceparent")


@contextmanager
def tramo(nombre: str, *, padre: Optional[Dict[str, str]] = None, tipo: str = "interno", **atributos):
    """Abre un tramo de la traza. padre = cabeceras con traceparent (de Kafka o del catastro)."""
    if not HAY_OTEL:
        yield None
        return
    kind = {"envio": SpanKind.PRODUCER, "recepcion": SpanKind.CONSUMER}.get(tipo, SpanKind.INTERNAL)
    ctx = propagate.extract(padre) if padre else None
    with trace.get_tracer("paas").start_as_current_span(nombre, context=ctx, kind=kind) as s:
        for k, v in atributos.items():
            if v is not None:
                s.set_attribute(k.replace("__", "."), v)
        yield s


def marcar(**atributos) -> None:
    """Pone atributos en el tramo actual (p. ej. paas__legajo=<urn> → paas.legajo)."""
    if HAY_OTEL:
        s = trace.get_current_span()
        for k, v in atributos.items():
            if v is not None:
                s.set_attribute(k.replace("__", "."), v)


def contexto_actual():
    return _ctx.get_current() if HAY_OTEL else None


async def con_contexto(ctx, coro):
    """Ejecuta una corrutina con un contexto de traza capturado en otro hilo."""
    if not HAY_OTEL or ctx is None:
        return await coro
    token = _ctx.attach(ctx)
    try:
        return await coro
    finally:
        _ctx.detach(token)


def interceptores_temporal() -> list:
    if not (HAY_OTEL and os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")):
        return []
    from temporalio.contrib.opentelemetry import TracingInterceptor
    return [TracingInterceptor()]


def legajo_de(ev: dict) -> Optional[str]:
    """El legajo del que trata una carta (para buscar sus trazas en Jaeger)."""
    if ev.get("subject", "").startswith("urn:ngsi-ld:ActivoPatrimonial:"):
        return ev["subject"]
    return (ev.get("data") or {}).get("activo")
