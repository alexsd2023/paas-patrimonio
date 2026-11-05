"""Parte 4 · un aviso como el de Scorpio entra por el puente y sale legajo.ingestado en Kafka.

Uso (desde plataforma/, con el venv activo):  python scripts/puente_check.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

from sdk.eventos import Consumidor  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP") or sys.exit("Falta KAFKA_BOOTSTRAP en plataforma/.env")
PUENTE = (os.environ.get("PUENTE_URL") or sys.exit("Falta PUENTE_URL en plataforma/.env")).rstrip("/")

aviso = {
    "id": "urn:ngsi-ld:Notification:prueba", "type": "Notification",
    "subscriptionId": "urn:ngsi-ld:Subscription:puente",
    "data": [{
        "id": "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001", "type": "ActivoPatrimonial",
        "signatura": {"type": "Property", "value": "TEST-001"},
        "ark": {"type": "Property", "value": "ark:/99999/av-test-001"},
        "manifiesto": {"type": "Property", "value": "https://iiif.local/iiif/3/archivo-villanueva/TEST-001/manifest"},
        "imagenes": {"type": "Property", "value": 3},
        "ingestadoPor": {"type": "Property", "value": "m.ortega"},
    }],
}


def enviar(cuerpo, cabeceras=None):
    req = urllib.request.Request(f"{PUENTE}/ngsi-ld/notificaciones/archivo-villanueva",
                                 data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(cabeceras or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except OSError as e:
        sys.exit(f"✗ No se llega al puente en {PUENTE}: {e}. ¿Está arriba? (docker compose ps)")


# 1 · Aviso de Scorpio → carta
estado, r = enviar(aviso)
if estado != 200 or not r.get("publicados"):
    sys.exit(f"✗ El puente respondió {estado}: {r}")
ev_id = r["publicados"][0]
print(f"✓ El puente aceptó el aviso y publicó {ev_id}")

# 2 · Aviso repetido → misma carta
_, r2 = enviar(aviso)
print("✓ Aviso repetido → mismo id de evento" if r2.get("publicados") == [ev_id]
      else f"✗ Aviso repetido dio otro id: {r2}")

# 3 · Otra institución no puede hacerse pasar por Villanueva
estado, _ = enviar(aviso, {"NGSILD-Tenant": "otro-archivo"})
print("✓ Tenant cruzado rechazado (400)" if estado == 400 else f"✗ Tenant cruzado devolvió {estado}")

# 4 · La carta está en el bus y cumple el contrato
for ev in Consumidor(BOOTSTRAP, grupo=f"puente-check-{ev_id}", topics=["activos"],
                     tipos=["legajo.ingestado"], desde_el_principio=True, limite=20):
    if ev["id"] == ev_id:
        print(f"✓ En Kafka: {ev['type']} · {ev['data']['signatura']} · tenant {ev['tenant']} · desde {ev['source']}")
        print("Parte 4 completada: tramos 5–6 funcionan (aviso del registro → carta en el bus).")
        break
else:
    sys.exit("✗ La carta no aparece en activos en 20 s")
