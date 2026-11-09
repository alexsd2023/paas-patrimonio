"""Lo que el núcleo sabe de sí mismo: si sus piezas responden y qué hay en cada buzón del bus.

No sabe nada de legajos ni de depósitos: eso es de cada producto.
"""
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

# (pieza, nombre, cómo se sondea, dónde). Nombres de la red de docker compose.
SONDAS: List[Tuple[str, str, str, str]] = [
    ("identidad", "Identidad · Keycloak", "http", "http://keycloak:8080/realms/paas"),
    ("identidad", "Instituciones · alta y personas", "http", "http://instituciones:8080/salud"),
    ("puerta", "Puerta · APISIX", "tcp", "apisix:9080"),
    ("correos", "Correos · Kafka", "tcp", "kafka:29092"),
    ("correos", "Puente catastro → correos", "http", "http://puente:8080/salud"),
    ("catastro", "Catastro · Scorpio", "tcp", "scorpio:9090"),
    ("procesos", "Procesos · Temporal", "tcp", "temporal:7233"),
    ("notario", "Notario", "http", "http://procedencia:8080/salud"),
    ("notario", "Libro del notario · Fuseki", "tcp", "fuseki:3030"),
    ("trazas", "Trazas · Jaeger", "tcp", "jaeger:16686"),
    ("modelos", "Modelos · MLflow", "http", "http://mlflow:5000/health"),
    ("servicios", "Catálogo de servicios y flujos", "http", "http://catalogo:8080/salud"),
    ("correos", "Visor del bus · Kafka UI", "tcp", "kafka-ui:8080"),
]


def _sondear(s: Tuple[str, str, str, str], espera: float) -> Dict[str, Any]:
    pieza, nombre, modo, destino = s
    t0 = time.monotonic()
    try:
        if modo == "http":
            with urllib.request.urlopen(destino, timeout=espera) as r:
                ok = r.status < 500
        else:
            host, puerto = destino.rsplit(":", 1)
            with socket.create_connection((host, int(puerto)), timeout=espera):
                ok = True
        detalle = None
    except Exception as e:  # noqa: BLE001  una pieza caída es un dato, no un error de la consola
        ok, detalle = False, type(e).__name__
    return {"pieza": pieza, "nombre": nombre, "destino": destino, "ok": ok,
            "ms": round((time.monotonic() - t0) * 1000), "detalle": detalle}


def sondear(sondas=SONDAS, espera: float = 1.5) -> List[Dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=len(sondas) or 1) as ex:
        return list(ex.map(lambda s: _sondear(s, espera), sondas))


class Bus:
    """Mira los buzones de Kafka sin consumir para nadie (no confirma offsets)."""

    def __init__(self, bootstrap: str, cache_s: float = 3.0):
        self.bootstrap = bootstrap
        self.cache_s = cache_s
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def _consumidor(self):
        from confluent_kafka import Consumer
        return Consumer({"bootstrap.servers": self.bootstrap, "group.id": "panel-mirador",
                         "enable.auto.commit": False, "socket.timeout.ms": 3000})

    def _cacheado(self, clave, fn):
        ahora = time.monotonic()
        if clave in self._cache and ahora - self._cache[clave][0] < self.cache_s:
            return self._cache[clave][1]
        valor = fn()
        self._cache[clave] = (ahora, valor)
        return valor

    def buzones(self) -> List[Dict[str, Any]]:
        def leer():
            from confluent_kafka import TopicPartition
            c = self._consumidor()
            try:
                md = c.list_topics(timeout=3)
                out = []
                for nombre, t in sorted(md.topics.items()):
                    if nombre.startswith("_"):
                        continue
                    total = 0
                    for p in t.partitions:
                        bajo, alto = c.get_watermark_offsets(TopicPartition(nombre, p), timeout=2)
                        total += max(0, alto - bajo)
                    out.append({"buzon": nombre, "cartas": total, "particiones": len(t.partitions)})
                return out
            finally:
                c.close()
        return self._cacheado("buzones", leer)

    def ultimas(self, tenant: str, por_buzon: int = 15) -> List[Dict[str, Any]]:
        """Las últimas cartas de cada buzón que son de mi institución (cabecera ce_tenant)."""
        def leer():
            from confluent_kafka import TopicPartition
            c = self._consumidor()
            try:
                md = c.list_topics(timeout=3)
                asignar, fin = [], {}
                for nombre, t in md.topics.items():
                    if nombre.startswith("_"):
                        continue
                    for p in t.partitions:
                        bajo, alto = c.get_watermark_offsets(TopicPartition(nombre, p), timeout=2)
                        if alto > bajo:
                            asignar.append(TopicPartition(nombre, p, max(bajo, alto - por_buzon)))
                            fin[(nombre, p)] = alto
                if not asignar:
                    return []
                c.assign(asignar)
                cartas, limite = [], time.monotonic() + 4
                while fin and time.monotonic() < limite:
                    m = c.poll(0.5)
                    if m is None or m.error():
                        continue
                    cab = {k: (v.decode("utf-8", "replace") if isinstance(v, bytes) else v) for k, v in (m.headers() or [])}
                    cartas.append({"buzon": m.topic(), "tipo": cab.get("ce_type"), "sujeto": cab.get("ce_subject"),
                                   "fuente": cab.get("ce_source"), "tiempo": cab.get("ce_time"),
                                   "tenant": cab.get("ce_tenant"), "id": cab.get("ce_id"),
                                   "traza": (cab.get("traceparent") or "").split("-")[1:2] or [None]})
                    if m.offset() + 1 >= fin.get((m.topic(), m.partition()), 0):
                        fin.pop((m.topic(), m.partition()), None)
                for x in cartas:
                    x["traza"] = x["traza"][0]
                return cartas
            finally:
                c.close()
        todas = self._cacheado("ultimas", leer)
        mias = [x for x in todas if x["tenant"] == tenant]
        return sorted(mias, key=lambda x: x["tiempo"] or "", reverse=True)


def resumen_bus(bus: Optional[Bus]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if bus is None:
        return [], "sin bus configurado"
    try:
        return bus.buzones(), None
    except Exception as e:  # noqa: BLE001
        return [], f"Kafka no responde: {e}"
