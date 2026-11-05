"""Parte 1 · comprueba que el Mac publica y lee en el Kafka del servidor.

Uso (desde plataforma/, con el venv activo):
    python scripts/kafka_check.py
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

from confluent_kafka import Consumer, KafkaException, Producer
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP")
TOPIC = "activos"

if not BOOTSTRAP:
    sys.exit("Falta KAFKA_BOOTSTRAP en plataforma/.env (ejemplo: servidor:9092)")

marca = str(uuid.uuid4())
mensaje = {"tipo": "prueba", "signatura": "TEST-001", "tenant": "archivo-villanueva", "marca": marca}

# 0 · Diagnóstico: ¿a qué dirección nos manda Kafka?
from confluent_kafka.admin import AdminClient
try:
    md = AdminClient({"bootstrap.servers": BOOTSTRAP}).list_topics(timeout=10)
except KafkaException as e:
    sys.exit(f"✗ No hay conexión con {BOOTSTRAP}: {e}. Revisa IP, puerto y firewall, y que el contenedor esté arriba.")
anunciados = [f"{b.host}:{b.port}" for b in md.brokers.values()]
print(f"✓ Conectado a {BOOTSTRAP}; Kafka anuncia: {', '.join(anunciados)}")
if BOOTSTRAP.split(":")[0] not in [a.split(":")[0] for a in anunciados]:
    print(f"! Aviso: el servidor anuncia una dirección distinta de la que usas ({BOOTSTRAP}).\n"
          f"  Si falla, pon KAFKA_HOST={BOOTSTRAP.split(':')[0]} en platform/.env del servidor y haz: docker compose up -d")
faltan = {"activos", "htr"} - set(md.topics)
if faltan:
    sys.exit(f"✗ Faltan los topics {sorted(faltan)}: revisa 'docker compose logs kafka-init'.")

# 1 · Publicar
p = Producer({"bootstrap.servers": BOOTSTRAP, "client.id": "kafka-check"})
entregado = {}
p.produce(TOPIC, key="TEST-001", value=json.dumps(mensaje).encode(),
          headers={"ce_tenant": "archivo-villanueva"},
          on_delivery=lambda err, msg: entregado.update(err=err, msg=msg))
p.flush(15)
if not entregado or entregado["err"]:
    sys.exit(f"✗ No se pudo publicar en {BOOTSTRAP}: {entregado.get('err', 'sin respuesta en 15 s')}")
m = entregado["msg"]
print(f"✓ Publicado en {TOPIC} (partición {m.partition()}, offset {m.offset()})")

# 2 · Leer el mismo mensaje
c = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": f"kafka-check-{marca}",
              "auto.offset.reset": "earliest", "enable.auto.commit": False})
c.subscribe([TOPIC])
limite = time.time() + 20
try:
    while time.time() < limite:
        msg = c.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            raise KafkaException(msg.error())
        if json.loads(msg.value()).get("marca") == marca:
            cab = dict(msg.headers() or [])
            print(f"✓ Leído de vuelta (tenant en cabecera: {cab.get('ce_tenant', b'').decode()})")
            print("Parte 1 completada: Mac ↔ Kafka del servidor funcionando.")
            break
    else:
        sys.exit("✗ Publicado pero no leído en 20 s. Revisa KAFKA_HOST en el .env del servidor (listener anunciado).")
finally:
    c.close()
