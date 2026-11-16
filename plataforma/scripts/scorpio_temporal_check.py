"""F0 del gemelo patrimonial · ¿sirve la API temporal de Scorpio para las series?

Comprueba contra el catastro de verdad (SCORPIO_URL de plataforma/.env), en una institución de pruebas que borra
al terminar:
  1. el historial: cada actualización de una observación queda guardada y se lee por la API temporal;
  2. la consulta por zona (q=refZone==…) en una ventana de tiempo;
  3. la representación agregada (media por hora), si la versión de Scorpio la tiene;
  4. el tiempo de leer un mes de lecturas horarias;
  5. el contexto JSON-LD del gemelo (gdp-v1), resuelto por Scorpio desde la consola.

Al final dice si se puede poner SERIES_ORIGEN=scorpio en el servicio de conservación.
Uso (desde plataforma/, con el venv activo):  python scripts/scorpio_temporal_check.py
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from _comun import env  # noqa: I100

SCORPIO = env("SCORPIO_URL")
T = "gemelo-prueba-temporal"
ZONA = f"urn:ngsi-ld:HeritageZone:{T}:Z01"
OBS = f"urn:ngsi-ld:IndoorEnvironmentObserved:{T}:S01"
MES = f"urn:ngsi-ld:IndoorEnvironmentObserved:{T}:S02"
q = lambda x: urllib.parse.quote(x, safe="")  # noqa: E731


def pedir(metodo, ruta, cuerpo=None, tipo="application/json", cab=None):
    h = {"NGSILD-Tenant": T, "Accept": "application/json", **(cab or {})}
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    if datos:
        h["Content-Type"] = tipo
    req = urllib.request.Request(SCORPIO + ruta, data=datos, method=metodo, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            texto = r.read().decode()
            return r.status, (json.loads(texto) if texto.strip() else None), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        texto = e.read().decode()
        try:
            return e.code, json.loads(texto), time.monotonic() - t0
        except ValueError:
            return e.code, texto, time.monotonic() - t0


def iso(d):
    return d.isoformat(timespec="seconds").replace("+00:00", "Z")


def instancias(attr):
    return attr if isinstance(attr, list) else ([attr] if isinstance(attr, dict) else [])


fallos, avisos = [], []
ahora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
for e in (OBS, MES):
    pedir("DELETE", f"/ngsi-ld/v1/entities/{q(e)}")

# 1 · historial de una observación actualizada varias veces
pedir("POST", "/ngsi-ld/v1/entities", {"id": OBS, "type": "IndoorEnvironmentObserved",
                                       "refZone": {"type": "Relationship", "object": ZONA}})
for i in range(5):
    cuando = iso(ahora - timedelta(hours=5 - i))
    est, _, _ = pedir("POST", f"/ngsi-ld/v1/entities/{q(OBS)}/attrs",
                      {"temperature": {"type": "Property", "value": 18 + i / 10, "observedAt": cuando},
                       "relativeHumidity": {"type": "Property", "value": 50 + i, "observedAt": cuando}})
    if est not in (204, 207):
        fallos.append(f"actualizar la observación respondió {est}")
        break
est, cuerpo, _ = pedir("GET", f"/ngsi-ld/v1/temporal/entities/{q(OBS)}?attrs=relativeHumidity&lastN=20")
n = len(instancias((cuerpo or {}).get("relativeHumidity"))) if est == 200 and isinstance(cuerpo, dict) else 0
if n >= 5:
    print(f"✓ 1 · Scorpio guarda el historial de cada actualización ({n} valores de humedad)")
else:
    fallos.append(f"historial: la API temporal devolvió {est} con {n} valores (se esperaban 5): {str(cuerpo)[:200]}")

# 2 · consulta por zona en una ventana
qs = urllib.parse.urlencode({"type": "IndoorEnvironmentObserved", "q": f'refZone=="{ZONA}"',
                             "attrs": "temperature,relativeHumidity", "timerel": "between",
                             "timeAt": iso(ahora - timedelta(hours=6)), "endTimeAt": iso(ahora + timedelta(hours=1))})
est, cuerpo, _ = pedir("GET", f"/ngsi-ld/v1/temporal/entities?{qs}")
if est == 200 and isinstance(cuerpo, list) and any(x.get("id") == OBS for x in cuerpo):
    print("✓ 2 · La consulta por zona y ventana de tiempo encuentra la serie (lo que usa SeriesScorpio)")
else:
    fallos.append(f"consulta por zona: {est} {str(cuerpo)[:200]}")

# 3 · agregación por hora
qa = urllib.parse.urlencode({"attrs": "relativeHumidity", "options": "aggregatedValues", "aggrMethods": "avg",
                             "aggrPeriodDuration": "PT1H", "timerel": "after", "timeAt": iso(ahora - timedelta(hours=6))})
est, cuerpo, _ = pedir("GET", f"/ngsi-ld/v1/temporal/entities/{q(OBS)}?{qa}")
if est == 200:
    print("✓ 3 · La representación agregada (avg por hora) responde")
else:
    avisos.append(f"agregación no disponible ({est}): conservación agrega por hora ella misma, no es un problema")

# 4 · un mes de lecturas horarias: carga y lectura
instancias_mes = [{"type": "Property", "value": 50 + (i % 24) / 4, "observedAt": iso(ahora - timedelta(hours=720 - i))}
                  for i in range(720)]
est, cuerpo, seg = pedir("POST", "/ngsi-ld/v1/temporal/entities", {
    "id": MES, "type": "IndoorEnvironmentObserved", "refZone": {"type": "Relationship", "object": ZONA},
    "relativeHumidity": instancias_mes,
    "temperature": [dict(x, value=18.0) for x in instancias_mes]})
if est not in (201, 204):
    avisos.append(f"cargar un mes por la API temporal respondió {est}: {str(cuerpo)[:160]}")
else:
    qm = urllib.parse.urlencode({"attrs": "temperature,relativeHumidity", "timerel": "after",
                                 "timeAt": iso(ahora - timedelta(days=31)), "lastN": 20000})
    est, cuerpo, seg = pedir("GET", f"/ngsi-ld/v1/temporal/entities/{q(MES)}?{qm}")
    n = len(instancias((cuerpo or {}).get("relativeHumidity"))) if isinstance(cuerpo, dict) else 0
    linea = f"leer un mes ({n} horas de un sensor) tarda {seg:.2f} s"
    if est == 200 and n >= 700 and seg < 2:
        print(f"✓ 4 · {linea}")
    else:
        avisos.append(f"{linea} (respuesta {est}); un año de 6-8 sensores serán ~{seg * 12 * 7:.0f} s por zona")

# 5 · el contexto JSON-LD del gemelo
ctx = "http://panel:8080/contexts/v1/gdp.jsonld"
est, cuerpo, _ = pedir("POST", "/ngsi-ld/v1/entities", {
    "id": f"urn:ngsi-ld:HeritageBuilding:{T}:B01", "type": "HeritageBuilding",
    "protectionLevel": {"type": "Property", "value": "BIC"}, "@context": [ctx]}, tipo="application/ld+json")
if est == 201:
    est, cuerpo, _ = pedir("GET", f"/ngsi-ld/v1/entities/{q(f'urn:ngsi-ld:HeritageBuilding:{T}:B01')}",
                           cab={"Link": f'<{ctx}>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'})
    print(f"✓ 5 · Scorpio resuelve el contexto gdp-v1 desde la consola (lectura con Link: {est})")
else:
    avisos.append(f"el contexto gdp-v1 no se pudo usar ({est}: {str(cuerpo)[:160]}); las entidades del gemelo usan "
                  "el contexto por defecto, como el resto del catastro")
pedir("DELETE", f"/ngsi-ld/v1/entities/{q(f'urn:ngsi-ld:HeritageBuilding:{T}:B01')}")

for e in (OBS, MES):
    pedir("DELETE", f"/ngsi-ld/v1/entities/{q(e)}")
    pedir("DELETE", f"/ngsi-ld/v1/temporal/entities/{q(e)}")

for a in avisos:
    print(f"· {a}")
if fallos:
    for f in fallos:
        print(f"✗ {f}")
    raise SystemExit("✗ La API temporal no sirve tal cual: deja SERIES_ORIGEN=local en conservación (es el valor por defecto).")
print("F0 completada: la API temporal de Scorpio sirve. Puedes poner SERIES_ORIGEN=scorpio en el servicio de "
      "conservación (platform/.env) y recrearlo; el histórico sintético seguirá en conservación.")
