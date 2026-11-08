"""Parte 7 · escenas 3 a 5: el legajo se inscribe, se transcribe solo y la paleógrafa lo valida.

Uso (desde plataforma/, con el venv activo):  python scripts/proceso_check.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

from sdk.registro import Registro, entidad_activo, urn_transcripcion  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def env(k):
    return (os.environ.get(k) or sys.exit(f"Falta {k} en plataforma/.env")).rstrip("/")


SCORPIO, PROC, GEST = env("SCORPIO_URL"), env("PROCEDENCIA_URL"), env("GESTORIA_URL")
T = "archivo-villanueva"
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"
reg = Registro(SCORPIO)


def http(url, cuerpo=None):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode() if cuerpo else None,
                                 method="POST" if cuerpo else "GET", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def esperar(desc, leer, cumple, segundos=60):
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
             f"  Pista: docker compose logs --tail 40 gestoria procesos htr temporal")


# Escena 3 · la archivera entrega el legajo
ficha = entidad_activo(T, signatura=SIG, ark=f"ark:/99999/av-{SIG.lower()}",
                       manifiesto=f"https://iiif.local/iiif/3/{T}/{SIG}/manifest", imagenes=3, ingestado_por="m.ortega")
if reg.crear(T, ficha) != 201:
    sys.exit("✗ El catastro no inscribió el legajo")
activo = ficha["id"]
q = urllib.parse.quote(activo, safe="")
print(f"✓ Escena 3 · legajo {SIG} inscrito")

# Escena 4 · se abre el proceso y el taller transcribe
exp = esperar("La gestoría abre el proceso y la copia queda pendiente",
              lambda: http(f"{GEST}/expedientes?activo={q}")[1],
              lambda v: isinstance(v, list) and v and v[0].get("estado") == "pendiente-validacion")[0]
print(f"✓ Escena 4 · proceso {exp['proceso']} en Temporal: {exp['estado']} (copia de {exp['modelo']})")
copia = reg.leer(T, urn_transcripcion(activo))
if not copia or copia["estado"]["value"] != "pendiente-validacion":
    sys.exit(f"✗ La transcripción no está en el catastro como pendiente: {copia}")
print(f"✓ Escena 4 · transcripción inscrita en el catastro, {copia['lineas']['value']} líneas, pendiente de validar")

# Escena 5 · la paleógrafa valida
estado, r = http(f"{GEST}/expedientes/validar", {"activo": activo, "por": "paleografa-test"})
if estado != 200:
    sys.exit(f"✗ La validación fue rechazada ({estado}): {r}")
esperar("El proceso termina", lambda: http(f"{GEST}/expedientes?activo={q}")[1],
        lambda v: v and v[0].get("estado") == "completado", 30)
copia = reg.leer(T, urn_transcripcion(activo))
if copia["estado"]["value"] != "validada" or copia.get("validadoPor", {}).get("value") != "paleografa-test":
    sys.exit(f"✗ El catastro no refleja la validación: {copia.get('estado')}, {copia.get('validadoPor')}")
print("✓ Escena 5 · la paleógrafa firma; el proceso termina y el catastro marca la copia como validada")
estado, _ = http(f"{GEST}/expedientes/validar", {"activo": activo, "por": "paleografa-test"})
print("✓ Una segunda firma se rechaza (409)" if estado == 409 else f"✗ Segunda firma devolvió {estado}")

actas = esperar("El notario levanta las tres actas", lambda: http(f"{PROC}/actas?activo={q}")[1],
                lambda v: isinstance(v, list) and {"ingreso", "htr", "validacion"} <= {a["tipo"] for a in v}, 30)
print(f"✓ Notario: actas {', '.join(a['tipo'] for a in actas)}")
print("Parte 7 completada: escenas 3, 4 y 5 de punta a punta (tramos 4–13).")
