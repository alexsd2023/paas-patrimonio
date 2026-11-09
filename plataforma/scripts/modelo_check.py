"""Parte 12 · comprueba que la copia de un legajo cita el modelo en producción, su run y sus datos.

    python modelos/htr/entrenar.py --produccion     # antes: un modelo en producción
    python scripts/modelo_check.py

1. MLflow responde y htr-paleografico tiene versión en producción (alias «produccion»), con su versión de datos.
2. La archivera entrega un legajo por la puerta; el taller lo copia con ESE modelo.
3. La copia en el catastro cita modelo, run y datos; la carta y el acta del notario también.
"""
import sys
import urllib.parse

from _comun import env, esperar, http
from ingesta_ligera import entregar  # noqa: I100

MLFLOW, PROC = env("MLFLOW_URL"), env("PROCEDENCIA_URL")
NOMBRE = "htr-paleografico"

est, r = http(f"{MLFLOW}/api/2.0/mlflow/registered-models/alias?name={NOMBRE}&alias=produccion")
if est != 200:
    sys.exit(f"✗ No hay {NOMBRE} en producción en {MLFLOW} ({est}).\n"
             f"  Pista: python modelos/htr/entrenar.py --produccion")
v = r["model_version"]
etq = {t["key"]: t["value"] for t in v.get("tags", [])}
version, run, datos = v["version"], v["run_id"], etq.get("datos.version", "")
print(f"✓ En producción: {NOMBRE}@{version} · run {run[:8]} · datos {datos[:10]} ({etq.get('datos.origen')}) · CER {etq.get('cer')}")
if etq.get("datos.origen") != "dvc":
    print("! Los datos de ese modelo no estaban bajo DVC (md5 calculado). Haz «dvc add datos/gt» y vuelve a entrenar.")

activo = entregar()
print(f"✓ Legajo entregado: {activo}")

from sdk.registro import Registro, urn_transcripcion  # noqa: E402
reg = Registro(env("SCORPIO_URL"))
tenant = activo.split(":")[3]
copia = esperar("copia del taller", lambda: reg.leer(tenant, urn_transcripcion(activo)), lambda c: bool(c), 90,
                pista="docker compose logs --tail 40 htr procesos gestoria")
val = lambda k: (copia.get(k) or {}).get("value")  # noqa: E731
assert val("modelo") == f"{NOMBRE}@{version}", f"la copia dice {val('modelo')}: ¿el taller ve MLflow? (docker compose logs htr)"
assert val("modeloRun") == run and val("datosVersion") == datos, (val("modeloRun"), val("datosVersion"))
print(f"✓ La copia cita {val('modelo')} · run {run[:8]} · datos {datos[:10]}")

q = urllib.parse.quote(activo, safe="")
actas = esperar("acta del taller en el notario", lambda: http(f"{PROC}/actas?activo={q}")[1],
                lambda a: isinstance(a, list) and any(x.get("tipo") == "htr" for x in a), 60,
                pista="docker compose logs --tail 40 procedencia")
acta = next(x for x in actas if x["tipo"] == "htr")
assert f"{NOMBRE}@{version}" in (acta.get("detalle") or "") and datos[:10] in acta["detalle"], acta
print(f"✓ Acta del notario: «{acta['detalle']}»")
print(f"\nParte 12 completada: copia → modelo {NOMBRE}@{version} → run {run[:8]} → datos {datos[:10]} → commit {etq.get('git.commit', '?')[:12]}")
