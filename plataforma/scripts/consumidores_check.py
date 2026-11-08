"""Parte 5 · un legajo nuevo entra por el puente y lo recogen, cada uno por su lado,
el notario (procedencia) y la gestoría.

Uso (desde plataforma/, con el venv activo):  python scripts/consumidores_check.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

from sdk.eventos import Publicador, nuevo_evento  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def env(k):
    return (os.environ.get(k) or sys.exit(f"Falta {k} en plataforma/.env")).rstrip("/")


KAFKA, PUENTE, PROC, GEST = env("KAFKA_BOOTSTRAP"), env("PUENTE_URL"), env("PROCEDENCIA_URL"), env("GESTORIA_URL")
from _comun import expedientes  # noqa: E402  (la gestoría se consulta por la puerta, con token)
T = "archivo-villanueva"
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"
ACTIVO = f"urn:ngsi-ld:ActivoPatrimonial:{T}:{SIG}"


def http(url, cuerpo=None):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode() if cuerpo else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if cuerpo else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except OSError as e:
        sys.exit(f"✗ {url}: {e}")


def esperar(desc, leer, cumple, segundos=20):
    fin = time.time() + segundos
    while time.time() < fin:
        try:
            valor = leer()
            if cumple(valor):
                return valor
        except OSError as e:
            valor = str(e)
        time.sleep(1)
    sys.exit(f"✗ {desc}: no ocurrió en {segundos} s (último valor: {valor})")


for nombre, url in [("procedencia", PROC), ("gestoría", GEST)]:
    s = http(f"{url}/salud")
    if not s.get("consumidor", {}).get("conectado"):
        sys.exit(f"✗ El consumidor de {nombre} no está conectado a Kafka: {s}")
print("✓ Notario y gestoría arriba y conectados al bus")

aviso = {"id": "urn:ngsi-ld:Notification:check", "type": "Notification", "data": [{
    "id": ACTIVO, "type": "ActivoPatrimonial", "signatura": SIG, "ark": f"ark:/99999/av-{SIG.lower()}",
    "manifiesto": f"https://iiif.local/iiif/3/{T}/{SIG}/manifest", "imagenes": 3, "ingestadoPor": "m.ortega"}]}

# 1 · La archivera entrega el legajo (el aviso de Scorpio lo simulamos)
http(f"{PUENTE}/ngsi-ld/notificaciones/{T}", aviso)
print(f"✓ Legajo {SIG} inscrito → carta legajo.ingestado")

# 2 · El taller (HTR, aún simulado aquí) termina la copia
Publicador(KAFKA, client_id="consumidores-check").publicar(nuevo_evento(
    "htr.completado", tenant=T, subject=f"urn:ngsi-ld:Transcripcion:{T}:{SIG}-t1",
    source=f"/tenants/{T}/modulos/htr-mock",
    data={"activo": ACTIVO, "estado": "pendiente-validacion", "modelo": "htr-mock@0.1", "lineas": 42}))
print("✓ Carta htr.completado enviada")

q = urllib.parse.quote(ACTIVO, safe="")
exp = esperar("La gestoría abre el expediente", lambda: expedientes(ACTIVO), lambda v: len(v) == 1)
print(f"✓ Gestoría: expediente {exp[0]['proceso']} ({exp[0]['estado']})")
actas = esperar("El notario levanta las dos actas", lambda: http(f"{PROC}/actas?activo={q}"),
                lambda v: [a["tipo"] for a in v] == ["ingreso", "htr"])
print(f"✓ Notario: actas {', '.join(a['tipo'] for a in actas)} · agentes de la copia: {', '.join(actas[1]['agentes'])}")

# 3 · Carta repetida: nadie duplica nada
http(f"{PUENTE}/ngsi-ld/notificaciones/{T}", aviso)
time.sleep(3)
n_exp, n_act = len(expedientes(ACTIVO)), len(http(f"{PROC}/actas?activo={q}"))
if (n_exp, n_act) != (1, 2):
    sys.exit(f"✗ Tras repetir la carta: {n_exp} expedientes y {n_act} actas (esperado 1 y 2)")
print("✓ Carta repetida: sigue habiendo 1 expediente y 2 actas")
print("Parte 5 completada: dos servicios recogen las mismas cartas, cada uno por su lado (tramos 7 y 11–12).")
