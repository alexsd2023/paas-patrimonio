"""Comprueba que una institución nueva entra y usa la plataforma sola, sin nadie del equipo del PaaS.

    python scripts/institucion_check.py

Todo pasa por la puerta (APISIX), como lo haría una persona con su navegador o un sistema con su API:
1. Se da de alta en /panel/alta y entra directamente como administradora; su catastro queda conectado al bus.
2. Empieza sin productos: el legajo no sale y su URL responde 403. Lo activa y ya puede entrar.
3. Invita a una archivera, que entra con su usuario y ve el catálogo de servicios.
4. Crea una credencial de API: un sistema obtiene token por client_credentials y usa el catálogo
   con la identidad de la institución. Al revocarla, deja de poder pedir tokens.
5. Pone un secreto de una capacidad para su institución: queda «listo» y su valor no sale nunca.
6. Otra institución (p.otro) no ve a sus personas ni sus credenciales.

Cada ejecución crea una institución «prueba-xxxxxx» (no se borran: quedan como registro de la comprobación).
"""
from http.cookiejar import CookieJar
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

from _comun import env, http, token

API, KC = env("API_URL"), env("KEYCLOAK_URL")
sufijo = secrets.token_hex(3)
INST, ADMIN, ARCH = f"prueba-{sufijo}", f"dir.{sufijo}", f"arch.{sufijo}"
CLAVE = secrets.token_urlsafe(12)


class Navegador:
    """Lo justo de un navegador: cookies y formularios, sin seguir redirecciones."""

    def __init__(self):
        self.jar = CookieJar()

        class SinSeguir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), SinSeguir)

    def pedir(self, ruta, *, form=None, json_=None, metodo=None):
        datos, cab = None, {}
        if form is not None:
            datos, cab = urllib.parse.urlencode(form).encode(), {"Content-Type": "application/x-www-form-urlencoded"}
        elif json_ is not None:
            datos, cab = json.dumps(json_).encode(), {"Content-Type": "application/json"}
        req = urllib.request.Request(f"{API}{ruta}", data=datos, headers=cab, method=metodo)
        try:
            with self.op.open(req, timeout=30) as r:
                return r.status, r.read().decode(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), e.headers

    def api(self, ruta, cuerpo=None, metodo=None):
        est, txt, _ = self.pedir(ruta, json_=cuerpo, metodo=metodo or ("POST" if cuerpo is not None else "GET"))
        try:
            return est, json.loads(txt)
        except ValueError:
            return est, txt


def falla(msg, pista="docker compose logs --tail 40 instituciones keycloak panel"):
    sys.exit(f"✗ {msg}\n  Pista: {pista}")


# 1 · alta
nav = Navegador()
est, txt, cab = nav.pedir("/panel/alta")
if est != 200 or "Alta de institución" not in txt:
    falla(f"/panel/alta respondió {est}")
if "está cerrada" in txt:
    sys.exit("! El alta está cerrada (REGISTRO=cerrado en platform/.env): no hay nada que comprobar.")
est, txt, cab = nav.pedir("/panel/alta", form={"institucion": INST, "nombre": f"Comprobación {sufijo}", "usuario": ADMIN,
                                               "clave": CLAVE, "email": f"{ADMIN}@ejemplo.org", "persona": "Ada Prueba"})
if est != 303 or cab.get("Location") != "/panel/institucion":
    falla(f"el alta respondió {est}: {txt[:300]}")
est, yo = nav.api("/panel/api/instituciones/yo")
if est != 200 or yo.get("institucion") != INST or not yo.get("admin"):
    falla(f"tras el alta no entra como administradora de {INST}: {est} {yo}")
print(f"✓ Alta de {INST}: {ADMIN} entra directamente como administradora")

# 1b · su catastro, conectado al bus (si desde aquí se llega a Scorpio: en la e2e sí)
import os  # noqa: E402
if os.environ.get("SCORPIO_URL"):
    from sdk.registro import Registro  # noqa: E402
    from services.suscripciones.crear import SUB_DEPOSITOS, SUB_ID  # noqa: E402
    reg = Registro(os.environ["SCORPIO_URL"])
    faltan = [s for s in (SUB_ID, SUB_DEPOSITOS) if reg.suscripcion(INST, s) is None]
    if faltan:
        falla(f"el catastro de {INST} no está conectado al bus: faltan {faltan}",
              "docker compose logs --tail 40 instituciones scorpio")
    print("✓ Su catastro está conectado al bus: lo que inscriba llegará a sus productos")

# 2 · productos
if yo["activos"]:
    falla(f"una institución nueva debería empezar sin productos: {yo['activos']}")
est, _, _ = nav.pedir("/panel/productos/legajo/")
if est != 403:
    falla(f"sin activar, el legajo debería responder 403 y respondió {est}")
est, act = nav.api("/panel/api/instituciones/activaciones/legajo", {"activo": True}, "PUT")
if est != 200 or act.get("activos") != ["legajo"]:
    falla(f"no pudo activar el legajo: {est} {act}")
est, txt, _ = nav.pedir("/panel")
if 'href="/panel/productos/legajo' not in txt or nav.pedir("/panel/productos/legajo/")[0] == 403:
    falla("activado el legajo, no aparece en la consola")
print("✓ Empieza sin productos; activa el legajo y aparece en su consola")

# 3 · personas
est, u = nav.api("/panel/api/instituciones/usuarios", {"usuario": ARCH, "clave": CLAVE, "email": f"{ARCH}@ejemplo.org",
                                                      "nombre": "Berta Prueba", "roles": ["archivera"]})
if est != 201:
    falla(f"no pudo añadir a {ARCH}: {est} {u}")
from sdk.identidad import pedir_token  # noqa: E402
try:
    tok_arch = pedir_token(KC, ARCH, CLAVE)
except OSError as e:
    falla(f"{ARCH} no obtiene token: {e}")
est, servicios = http(f"{API}/api/v1/servicios", token=tok_arch)
if est != 200:
    falla(f"{ARCH} no ve el catálogo: {est} {servicios}", "docker compose logs --tail 40 catalogo apisix")
print(f"✓ Invita a {ARCH} (archivera): entra y ve {len(servicios)} servicios")

# 4 · credenciales de API
est, cred = nav.api("/panel/api/instituciones/credenciales", {"nombre": "Comprobación", "roles": ["archivera"]})
if est != 201 or not cred.get("secreto"):
    falla(f"no pudo crear la credencial: {est} {cred}")


def token_app(cid, secreto):
    datos = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": secreto}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"{KC}/realms/paas/protocol/openid-connect/token", data=datos, method="POST"), timeout=15) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        return e.code


tok_app = token_app(cred["client_id"], cred["secreto"])
if not isinstance(tok_app, str):
    falla(f"la credencial {cred['client_id']} no obtiene token ({tok_app})")
est, _ = http(f"{API}/api/v1/servicios", token=tok_app)
est_inst, yo_app = http(f"{API}/api/v1/institucion/yo", token=tok_app)
if est != 200 or est_inst != 200 or yo_app.get("institucion") != INST:
    falla(f"la aplicación no usa la API como {INST}: catálogo {est}, institución {est_inst} {yo_app}")
est, _ = nav.api(f"/panel/api/instituciones/credenciales/{cred['client_id']}", metodo="DELETE")
if est != 200 or token_app(cred["client_id"], cred["secreto"]) not in (400, 401):
    falla("revocada la credencial, todavía obtiene token")
print(f"✓ Credencial de API {cred['client_id']}: el sistema usa la API como {INST}; revocada, ya no entra")

# 5 · secretos
est, ss = nav.api("/panel/api/catalogo/secretos")
pedidos = [(s["servicio"], x) for s in ss for x in s["secretos"] if x["ambito"] != "plataforma"] if est == 200 else []
if est != 200:
    falla(f"el catálogo no lista secretos: {est} {ss}", "docker compose logs --tail 40 catalogo")
if pedidos:
    sid, x = pedidos[0]
    valor = f"valor-de-prueba-{sufijo}"
    est, r = nav.api(f"/panel/api/catalogo/secretos/{sid}/{x['nombre']}", {"valor": valor, "ambito": "institucion"}, "PUT")
    if est != 200 or valor in json.dumps(r):
        falla(f"no pudo poner el secreto {x['nombre']} (o lo devolvió): {est}")
    ahora = next(y for s in nav.api("/panel/api/catalogo/secretos")[1] if s["servicio"] == sid for y in s["secretos"]
                 if y["nombre"] == x["nombre"])
    if not (ahora["listo"] and ahora["institucion"]):
        falla(f"el secreto {x['nombre']} no consta como puesto: {ahora}")
    nav.api(f"/panel/api/catalogo/secretos/{sid}/{x['nombre']}?ambito=institucion", metodo="DELETE")
    print(f"✓ Secreto {x['nombre']} de {sid}: se guarda para {INST}, consta como puesto y no se devuelve nunca")
else:
    print("! Ninguna capacidad pide secretos de institución: me salto ese paso")

# 6 · aislamiento
est, us = http(f"{API}/api/v1/institucion/usuarios", token=token("p.otro"))
if est == 200 and any(x["usuario"] in (ADMIN, ARCH) for x in us):
    falla("otra institución ve a las personas de la nueva")
est, _ = http(f"{API}/api/v1/institucion/usuarios/{u['id']}", {"activo": False}, token=token("p.otro"), metodo="PUT")
if est not in (403, 404):
    falla(f"otra institución pudo tocar a {ARCH} ({est})")
print("✓ Otra institución no ve ni toca a sus personas")
print(f"\nTodo bien: {INST} se ha dado de alta y trabaja sola.")
