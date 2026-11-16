"""Gemelo patrimonial · del sensor al dashboard y del dashboard al notario, contra la plataforma de verdad.

Recorre la API pública del producto (/api/v1/gemelo/… por la puerta, con el token de m.ortega, archivera y
administradora de archivo-villanueva):
  1. el inmueble piloto está en el catastro (lo inscribe el simulador al arrancar; si no, se crea);
  2. las zonas tienen su evaluación EN 15757 (por la capacidad, a través del catálogo) y lecturas en vivo
     (sensor → catastro → suscripción → puente → zona.medicion → conservación);
  3. una desviación simulada en el sótano abre una alerta alta, que cuenta en el consumo de la capacidad;
  4. la alerta se cierra con su causa y el notario la anota, con la persona que firmó;
  5. el vocabulario JSON-LD es público.
Uso (desde plataforma/, con el venv activo):  python scripts/gemelo_patrimonial_check.py
"""
import urllib.parse

from _comun import env, esperar, http, token  # noqa: I100

API, PROC = env("API_URL"), env("PROCEDENCIA_URL")
G = f"{API}/api/v1/gemelo"
T = "archivo-villanueva"
PISTA = "docker compose logs --tail 40 sensores conservacion catalogo srv-evaluacion-en15757 puente"


def api(ruta, cuerpo=None, usuario="m.ortega"):
    estado, r = http(f"{G}{ruta}", cuerpo, token=token(usuario))
    if estado >= 400:
        raise OSError(f"{ruta} respondió {estado}: {r}")
    return r


# 1 · el inmueble
d = api("/inmueble")
if not d["edificio"]:
    print("· El inmueble aún no está: lo creo (inmueble de ejemplo)")
    api("/semilla", {})
d = esperar("El inmueble piloto está en el catastro con sus zonas", lambda: api("/inmueble"),
            lambda x: isinstance(x, dict) and x.get("edificio") and x["kpis"]["zonas"] >= 4, 120, PISTA)
print(f"✓ {d['edificio']['nombre']}: {d['kpis']['zonas']} zonas · {d['kpis']['sensores']} sensores")

# 2 · evaluación y lecturas en vivo
d = esperar("Las zonas tienen su evaluación EN 15757", lambda: api("/inmueble"),
            lambda x: isinstance(x, dict) and all(z["nivel"] for z in x["zonas"]), 240, PISTA)
print("✓ Evaluadas: " + ", ".join(f"{z['codigo']} {z['nivel']}" for z in d["zonas"]))
d = esperar("Llegan lecturas en vivo de los sensores (zona.medicion)", lambda: api("/inmueble"),
            lambda x: isinstance(x, dict) and any(z["humedad"] is not None for z in x["zonas"]), 120,
            "docker compose logs --tail 40 sensores puente conservacion suscripciones")
z = next(z for z in d["zonas"] if z["humedad"] is not None)
print(f"✓ Lecturas en vivo: {z['nombre']} {z['temperatura']} °C · {z['humedad']} % HR")

# 3 · una fuga en el sótano
uso_antes = (http(f"{API}/api/v1/uso", token=token("m.ortega"))[1] or {}).get("evaluacion-en15757", 0)
r = api("/simular", {"zona": "Z02", "perfil": "desviacion", "dias": 8})
if r["evaluacion"]["nivel"] != "alto":
    raise SystemExit(f"✗ La desviación debía dar riesgo alto y dio {r['evaluacion']['nivel']}: {r['evaluacion']['causa']}")
abiertas = [a for a in api("/alertas") if a["zonaCodigo"] == "Z02"]
if not abiertas:
    raise SystemExit(f"✗ No hay alerta abierta en Z02 tras la desviación (acciones: {r['acciones']})")
alerta = abiertas[0]
print(f"✓ Desviación simulada en Z02: riesgo alto · alerta {alerta['codigo']} ({alerta['causa']})")
uso = (http(f"{API}/api/v1/uso", token=token("m.ortega"))[1] or {}).get("evaluacion-en15757", 0)
if uso <= uso_antes:
    raise SystemExit("✗ La evaluación no contó en el consumo de la capacidad (GET /api/v1/uso)")
print(f"✓ La capacidad evaluacion-en15757 cuenta en el consumo de {T}: {uso} trabajos hoy")

# 4 · cierre firmado y notario
api(f"/alertas/{alerta['codigo']}/cerrar", {"causa": "Prueba de punta a punta: fuga reparada"})
esperar("La alerta queda cerrada", lambda: api("/alertas?estado=todas"),
        lambda xs: any(a["codigo"] == alerta["codigo"] and a["estado"] == "cerrada" for a in xs), 60,
        "docker compose logs --tail 40 conservacion temporal")
q = urllib.parse.quote(alerta["id"], safe="")
actas = esperar("El notario anota el cierre con quien lo firmó", lambda: http(f"{PROC}/actas?activo={q}")[1],
                lambda v: isinstance(v, list) and any(a["tipo"] == "alerta-zona-cerrada" for a in v), 90,
                "docker compose logs --tail 40 conservacion procedencia")
cierre = next(a for a in actas if a["tipo"] == "alerta-zona-cerrada")
if f"urn:paas:usuario:{T}:m.ortega" not in cierre["agentes"]:
    raise SystemExit(f"✗ El acta del cierre no dice quién firmó: {cierre}")
print(f"✓ Cerrada y en el notario: {' → '.join(a['tipo'].replace('alerta-zona-', '') for a in actas)} · firmada por m.ortega")
api("/simular", {"zona": "Z02", "perfil": "estable", "dias": 30})
print("· Z02 vuelve a su clima")

# 5 · vocabulario
estado, ctx = http(f"{API}/contexts/v1/gdp.jsonld")
if estado != 200 or "HeritageZone" not in (ctx or {}).get("@context", {}):
    raise SystemExit(f"✗ El contexto JSON-LD no se publica en /contexts/v1/gdp.jsonld ({estado})")
print("✓ Vocabulario público en /contexts/v1/gdp.jsonld")
print("Gemelo patrimonial completado: sensor → catastro → bus → evaluación EN 15757 → alerta → firma → notario.")
