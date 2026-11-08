"""Parte 7 · escenas 3 a 5: el legajo se inscribe, se transcribe solo y la paleógrafa lo valida.

Desde la parte 8, la gestoría se usa a través de la puerta, con el token de cada persona.
Uso (desde plataforma/, con el venv activo):  python scripts/proceso_check.py
"""
import urllib.parse
import uuid

from _comun import env, esperar, expedientes, http, validar  # noqa: I100
from sdk.registro import Registro, entidad_activo, urn_transcripcion

SCORPIO, PROC = env("SCORPIO_URL"), env("PROCEDENCIA_URL")
T = "archivo-villanueva"
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"
reg = Registro(SCORPIO)

# Escena 3 · la archivera entrega el legajo
ficha = entidad_activo(T, signatura=SIG, ark=f"ark:/99999/av-{SIG.lower()}",
                       manifiesto=f"https://iiif.local/iiif/3/{T}/{SIG}/manifest", imagenes=3, ingestado_por="m.ortega")
if reg.crear(T, ficha) != 201:
    raise SystemExit("✗ El catastro no inscribió el legajo")
activo = ficha["id"]
print(f"✓ Escena 3 · legajo {SIG} inscrito")

# Escena 4 · se abre el proceso y el taller transcribe
exp = esperar("La gestoría abre el proceso y la copia queda pendiente", lambda: expedientes(activo),
              lambda v: v and v[0].get("estado") == "pendiente-validacion")[0]
print(f"✓ Escena 4 · proceso {exp['proceso']} en Temporal: {exp['estado']} (copia de {exp['modelo']})")
copia = reg.leer(T, urn_transcripcion(activo))
if not copia or copia["estado"]["value"] != "pendiente-validacion":
    raise SystemExit(f"✗ La transcripción no está en el catastro como pendiente: {copia}")
print(f"✓ Escena 4 · transcripción en el catastro, {copia['lineas']['value']} líneas, pendiente de validar")

# Escena 5 · la paleógrafa valida (con su token)
estado, r = validar(activo, "paleografa-test")
if estado != 200:
    raise SystemExit(f"✗ La validación fue rechazada ({estado}): {r}")
esperar("El proceso termina", lambda: expedientes(activo), lambda v: v and v[0].get("estado") == "completado", 30)
copia = reg.leer(T, urn_transcripcion(activo))
if copia["estado"]["value"] != "validada" or copia.get("validadoPor", {}).get("value") != "paleografa-test":
    raise SystemExit(f"✗ El catastro no refleja la validación: {copia.get('estado')}, {copia.get('validadoPor')}")
print("✓ Escena 5 · la paleógrafa firma; el proceso termina y el catastro marca la copia como validada")
estado, _ = validar(activo, "paleografa-test")
print("✓ Una segunda firma se rechaza (409)" if estado == 409 else f"✗ Segunda firma devolvió {estado}")

q = urllib.parse.quote(activo, safe="")
actas = esperar("El notario levanta las tres actas", lambda: http(f"{PROC}/actas?activo={q}")[1],
                lambda v: isinstance(v, list) and {"ingreso", "htr", "validacion"} <= {a["tipo"] for a in v}, 30)
print(f"✓ Notario: actas {', '.join(a['tipo'] for a in actas)}")
print("Parte 7 completada: escenas 3, 4 y 5 de punta a punta (tramos 4–13).")
