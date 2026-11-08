"""Parte 6 · el legajo se inscribe en el catastro (Scorpio) y el aviso llega solo.

Este script hace de adaptador IIIF (que llegará en el paso 6 del plan): inscribe la ficha
del legajo y comprueba que, sin enviar ningún aviso a mano, la gestoría abre el expediente
y el notario levanta acta. También comprueba que otra institución no ve el legajo.

Uso (desde plataforma/, con el venv activo):  python scripts/registro_check.py
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

from sdk.registro import Registro, entidad_activo  # noqa: E402
from services.suscripciones.crear import SUB_ID  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def env(k):
    return (os.environ.get(k) or sys.exit(f"Falta {k} en plataforma/.env")).rstrip("/")


SCORPIO, PROC = env("SCORPIO_URL"), env("PROCEDENCIA_URL")
from _comun import expedientes  # noqa: E402  (la gestoría se consulta por la puerta, con token)
T, OTRO = "archivo-villanueva", "otro-archivo"
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def esperar(desc, leer, cumple, segundos=30):
    fin, valor = time.time() + segundos, None
    while time.time() < fin:
        try:
            valor = leer()
            if cumple(valor):
                return valor
        except OSError:
            pass
        time.sleep(1)
    sys.exit(f"✗ {desc}: no ocurrió en {segundos} s (último valor: {valor}).\n"
             f"  Pista: docker compose logs --tail 30 scorpio puente suscripciones")


reg = Registro(SCORPIO)
if not reg.disponible():
    sys.exit(f"✗ El catastro no responde en {SCORPIO}. ¿Está arriba? (docker compose ps scorpio)")
print(f"✓ Catastro (Scorpio) responde en {SCORPIO}")

if not reg.suscripcion(T, SUB_ID):
    sys.exit("✗ No existe la suscripción al puente. Revisa: docker compose logs suscripciones")
print("✓ Suscripción catastro → puente activa")

ficha = entidad_activo(T, signatura=SIG, ark=f"ark:/99999/av-{SIG.lower()}",
                       manifiesto=f"https://iiif.local/iiif/3/{T}/{SIG}/manifest",
                       imagenes=3, ingestado_por="m.ortega")
estado = reg.crear(T, ficha)
if estado != 201:
    sys.exit(f"✗ El catastro no inscribió el legajo (HTTP {estado})")
print(f"✓ Legajo {SIG} inscrito en el catastro de {T}")

if reg.leer(T, ficha["id"]) is None:
    sys.exit("✗ El legajo no se puede leer en su propio tenant")
if reg.leer(OTRO, ficha["id"]) is not None:
    sys.exit(f"✗ AISLAMIENTO ROTO: {OTRO} ve el legajo de {T}")
print(f"✓ Aislamiento: {OTRO} no ve el legajo")

q = urllib.parse.quote(ficha["id"], safe="")
exp = esperar("La gestoría abre el expediente (aviso del catastro → puente → Kafka)",
              lambda: expedientes(ficha["id"]), lambda v: len(v) == 1)
print(f"✓ Gestoría: expediente {exp[0]['proceso']} {exp[0]['estado']}")
actas = esperar("El notario levanta acta de ingreso",
                lambda: get(f"{PROC}/actas?activo={q}"), lambda v: any(a["tipo"] == "ingreso" for a in v))
print(f"✓ Notario: acta de ingreso con {', '.join(actas[0]['agentes'])}")
print("Parte 6 completada: el aviso ya lo da el catastro, sin scripts (tramos 4–7 y 11–12 de la escena 3).")
