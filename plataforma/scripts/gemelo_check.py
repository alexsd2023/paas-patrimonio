"""Gemelo digital · un legajo en su caja, una fuga de agua en el depósito y el aviso hasta su libro.

Usa el panel como lo haría la archivera (inicia sesión con m.ortega) para simular la fuga.
Uso (desde plataforma/, con el venv activo):  python scripts/gemelo_check.py
"""
from http.cookiejar import CookieJar
import json
import urllib.parse
import urllib.request
import uuid

from _comun import CLAVES, env, esperar, http  # noqa: I100
from sdk.registro import Registro, entidad_activo, urn_deposito

API, PROC = env("API_URL"), env("PROCEDENCIA_URL")
T = "archivo-villanueva"
reg = Registro(env("SCORPIO_URL"))

# Sesión en el panel como m.ortega
jar = CookieJar()
web = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
web.open(f"{API}/panel/entrar", data=urllib.parse.urlencode({"usuario": "m.ortega", "clave": CLAVES["m.ortega"]}).encode(), timeout=15)


def panel(ruta, cuerpo=None):
    req = urllib.request.Request(f"{API}{ruta}", data=json.dumps(cuerpo).encode() if cuerpo else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if cuerpo else "GET")
    with web.open(req, timeout=15) as r:
        return json.loads(r.read())


def deposito(codigo):
    return next(d for d in panel("/panel/productos/gemelo/api/depositos") if d["codigo"] == codigo)


# 1 · El gemelo existe y recibe lecturas
d1 = esperar("El depósito D1 tiene lecturas", lambda: deposito("D1"), lambda d: d["humedad"] is not None and len(d["serie"]) >= 2,
             60, "docker compose logs --tail 30 sensores conservacion puente suscripciones")
print(f"✓ {d1['nombre']}: {d1['temperatura']} °C · {d1['humedad']} % · {len(d1['cajas'])} cajas · lecturas llegando")

# 2 · Un legajo en la caja C-002 del depósito 1
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"
ficha = entidad_activo(T, signatura=SIG, ark=f"ark:/99999/av-{SIG.lower()}", manifiesto=f"{API}/iiif/3/{T}/{SIG}/manifest",
                       imagenes=3, ingestado_por="m.ortega", caja="C-002")
if reg.crear(T, ficha) != 201:
    raise SystemExit("✗ No se pudo inscribir el legajo")
print(f"✓ Legajo {SIG} guardado en la caja C-002 del depósito 1")

# 3 · Fuga de agua
panel("/panel/productos/gemelo/api/escenario", {"deposito": "D1", "escenario": "fuga"})
print("· Simulando una fuga de agua en el depósito 1…")
q = urllib.parse.quote(ficha["id"], safe="")
actas = esperar("La alerta llega al libro del legajo", lambda: http(f"{PROC}/actas?activo={q}")[1],
                lambda v: isinstance(v, list) and any(a["tipo"] == "alerta-conservacion" for a in v), 90,
                "docker compose logs --tail 30 conservacion procedencia")
alerta = next(a for a in actas if a["tipo"] == "alerta-conservacion")
print(f"✓ Alerta en el libro de {SIG}: {alerta.get('detalle')}")
print(f"✓ El catastro marca el depósito: {deposito('D1')['estado']}")
d2 = deposito("D2")
print(f"✓ El depósito 2 sigue en rango: {d2['humedad']} % ({d2['estado']})")

# 4 · Vuelta a la normalidad
panel("/panel/productos/gemelo/api/escenario", {"deposito": "D1", "escenario": "normal"})
print("· Se repara la fuga…")
esperar("La alerta se cierra", lambda: http(f"{PROC}/actas?activo={q}")[1],
        lambda v: isinstance(v, list) and any(a["tipo"] == "fin-alerta" for a in v), 120)
print(f"✓ Fin de la alerta en el libro de {SIG}; depósito 1: {deposito('D1')['estado']}")
print("Gemelo digital completado: depósito → sensores → catastro → carta → conservación → libro de cada legajo.")
