"""Parte 3 · la librería publica un legajo.ingestado en el Kafka del servidor y lo recibe validado.

Uso (desde plataforma/, con el venv activo):  python scripts/eventos_check.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

from sdk.contratos import ContratoInvalido  # noqa: E402
from sdk.eventos import Consumidor, Publicador, nuevo_evento  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP") or sys.exit("Falta KAFKA_BOOTSTRAP en plataforma/.env")

ev = nuevo_evento(
    "legajo.ingestado", tenant="archivo-villanueva",
    subject="urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001",
    source="/tenants/archivo-villanueva/servicios/puente",
    data={"signatura": "TEST-001", "ark": "ark:/99999/av-test-001",
          "manifiesto": "https://iiif.local/iiif/3/archivo-villanueva/TEST-001/manifest",
          "imagenes": 3, "ingestadoPor": "m.ortega"})

# 1 · Un evento roto no sale nunca
roto = dict(ev, tenant=None)
try:
    Publicador(BOOTSTRAP).publicar(roto)
    sys.exit("✗ Se publicó un evento sin tenant: la validación no funciona")
except ContratoInvalido:
    print("✓ Un evento sin tenant se rechaza antes de enviarlo")

# 2 · Publicar y leerlo con un grupo nuevo desde el principio del topic.
#     Los mensajes de prueba de la parte 1 no son CloudEvents: se ignoran con un aviso.
Publicador(BOOTSTRAP, client_id="eventos-check").publicar(ev)
consumidor = Consumidor(BOOTSTRAP, grupo=f"eventos-check-{ev['id']}", topics=["activos"],
                        tipos=["legajo.ingestado"], desde_el_principio=True, limite=20)
print(f"✓ Publicado legajo.ingestado {ev['id']} en activos")

for recibido in consumidor:
    if recibido["id"] == ev["id"]:
        assert recibido == ev, "el evento llegó distinto"
        print(f"✓ Recibido y validado: {recibido['type']} · {recibido['data']['signatura']} · tenant {recibido['tenant']}")
        print("Parte 3 completada: la librería de eventos funciona contra el Kafka del servidor.")
        break
else:
    sys.exit("✗ No llegó en 20 s")
