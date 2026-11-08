"""Publicar y consumir eventos del bus (CloudEvents en Kafka, modo binario).

    from sdk.eventos import Publicador, Consumidor, nuevo_evento

    ev = nuevo_evento("legajo.ingestado", tenant="archivo-villanueva",
                      subject="urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001",
                      source="/tenants/archivo-villanueva/servicios/puente", data={...})
    Publicador(bootstrap).publicar(ev)

    for ev in Consumidor(bootstrap, grupo="procedencia", topics=["activos", "htr"]):
        ...   # si el bloque termina sin excepción, el mensaje queda confirmado

Reglas que aplica la librería, para que cada servicio no tenga que acordarse:
- valida el contrato ANTES de enviar: un evento inválido nunca llega al bus;
- clave del mensaje = subject (los eventos de una entidad, en orden);
- atributos del sobre en cabeceras ce_*, data como valor JSON;
- el topic se deduce del tipo;
- al consumir, ignora lo que no es un CloudEvent válido (y lo avisa) y confirma
  cada mensaje solo después de procesarlo (entrega «al menos una vez»).
"""
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Iterable, Iterator, List, Optional, Tuple

from .contratos import ContratoInvalido, errores, validar

TOPIC_POR_TIPO = {
    "legajo.ingestado": "activos",
    "htr.completado": "htr",
    "transcripcion.validada": "htr",
}
_SOBRE = ["specversion", "id", "source", "type", "time", "subject", "tenant", "traceparent"]


def nuevo_evento(tipo: str, *, tenant: str, subject: str, source: str, data: dict,
                 traceparent: Optional[str] = None, id: Optional[str] = None) -> dict:
    """Crea y valida un evento. Pasa `id` fijo si el mismo hecho puede notificarse dos veces
    (así los consumidores reconocen el duplicado)."""
    ev = {
        "specversion": "1.0",
        "id": id or str(uuid.uuid4()),
        "source": source,
        "type": tipo,
        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "subject": subject,
        "datacontenttype": "application/json",
        "tenant": tenant,
        "data": data,
    }
    if traceparent:
        ev["traceparent"] = traceparent
    return validar(ev)


# --- Traducción evento ↔ mensaje de Kafka (funciones puras, sin red) ---

def a_kafka(evento: dict) -> Tuple[str, bytes, bytes, List[Tuple[str, bytes]]]:
    """evento → (topic, clave, valor, cabeceras)"""
    validar(evento)
    tipo = evento["type"]
    if tipo not in TOPIC_POR_TIPO:
        raise ContratoInvalido([f"sin topic asignado para {tipo!r} (TOPIC_POR_TIPO)"])
    cabeceras = [("ce_" + k if k != "traceparent" else k, str(evento[k]).encode())
                 for k in _SOBRE if k in evento]
    cabeceras.append(("content-type", evento["datacontenttype"].encode()))
    valor = json.dumps(evento["data"], ensure_ascii=False, separators=(",", ":")).encode()
    return TOPIC_POR_TIPO[tipo], evento["subject"].encode(), valor, cabeceras


def de_kafka(valor: Optional[bytes], cabeceras: Optional[Iterable[Tuple[str, bytes]]]) -> dict:
    """(valor, cabeceras) → evento. Lanza ContratoInvalido si no cumple el contrato."""
    cab = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in (cabeceras or [])}
    if "ce_type" not in cab:
        raise ContratoInvalido(["no es un CloudEvent (falta la cabecera ce_type)"])
    ev = {k: cab["ce_" + k] for k in _SOBRE if k != "traceparent" and "ce_" + k in cab}
    if "traceparent" in cab:
        ev["traceparent"] = cab["traceparent"]
    ev["datacontenttype"] = cab.get("content-type", "application/json")
    try:
        ev["data"] = json.loads(valor) if valor else None
    except ValueError:
        raise ContratoInvalido(["el valor no es JSON"])
    return validar(ev)


# --- Clientes de Kafka ---

class Publicador:
    def __init__(self, bootstrap: str, client_id: str = "paas"):
        from confluent_kafka import Producer
        self._p = Producer({"bootstrap.servers": bootstrap, "client.id": client_id,
                            "enable.idempotence": True, "acks": "all"})

    def publicar(self, evento: dict, timeout: float = 10.0) -> None:
        """Valida, envía y espera confirmación del broker. Lanza excepción si algo falla."""
        topic, clave, valor, cabeceras = a_kafka(evento)
        resultado = {}
        self._p.produce(topic, key=clave, value=valor, headers=cabeceras,
                        on_delivery=lambda err, msg: resultado.update(err=err))
        self._p.flush(timeout)
        if not resultado:
            raise TimeoutError(f"Kafka no confirmó el evento {evento['id']} en {timeout} s")
        if resultado["err"]:
            raise RuntimeError(f"Kafka rechazó el evento {evento['id']}: {resultado['err']}")


class Consumidor:
    """Itera eventos válidos. Cada servicio usa su propio `grupo`: así todos reciben todas las cartas."""

    def __init__(self, bootstrap: str, grupo: str, topics: List[str],
                 tipos: Optional[List[str]] = None, desde_el_principio: bool = False,
                 espera: float = 1.0, limite: Optional[float] = None):
        from confluent_kafka import Consumer
        self._c = Consumer({"bootstrap.servers": bootstrap, "group.id": grupo,
                            "auto.offset.reset": "earliest" if desde_el_principio else "latest",
                            "enable.auto.commit": False})
        self._c.subscribe(topics)
        self._tipos = set(tipos) if tipos else None
        self._espera, self._limite = espera, limite

    def __iter__(self) -> Iterator[dict]:
        import time
        from confluent_kafka import KafkaException
        fin = time.time() + self._limite if self._limite else None
        try:
            while fin is None or time.time() < fin:
                msg = self._c.poll(self._espera)
                if msg is None:
                    continue
                if msg.error():
                    raise KafkaException(msg.error())
                try:
                    ev = de_kafka(msg.value(), msg.headers())
                except ContratoInvalido as e:
                    print(f"[eventos] ignorado {msg.topic()}/{msg.partition()}@{msg.offset()}: {e}", file=sys.stderr)
                    self._c.commit(message=msg, asynchronous=False)
                    continue
                if self._tipos is None or ev["type"] in self._tipos:
                    yield ev                      # el servicio procesa aquí
                self._c.commit(message=msg, asynchronous=False)
        finally:
            self._c.close()
