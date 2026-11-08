"""Parte 8 · la puerta: quién eres lo dice Keycloak, y APISIX no deja pasar sin token.

Uso (desde plataforma/, con el venv activo):  python scripts/puerta_check.py
"""
import uuid

from _comun import env, esperar, expedientes, http, token, validar  # noqa: I100
from sdk.registro import Registro, entidad_activo

API, GEST = env("API_URL"), env("GESTORIA_URL")
T = "archivo-villanueva"

# Escena 1 · la archivera saca su DNI
yo_tok = token("m.ortega")
print("✓ Escena 1 · Keycloak emite el token de m.ortega")

# Escena 2 · la puerta
estado, _ = http(f"{API}/api/v1/yo")
if estado != 401:
    raise SystemExit(f"✗ Sin token la puerta debería responder 401 y respondió {estado}")
print("✓ Escena 2 · sin token, la puerta no deja pasar (401)")
estado, _ = http(f"{API}/api/v1/yo", token=yo_tok[:-6] + "AAAAAA")
print("✓ Token manipulado rechazado (401)" if estado == 401 else f"✗ Token manipulado devolvió {estado}")
estado, yo = http(f"{API}/api/v1/yo", token=yo_tok)
if estado != 200 or yo.get("tenant") != T or "archivera" not in yo.get("roles", []):
    raise SystemExit(f"✗ La puerta no reconoce a la archivera ({estado}): {yo}")
print(f"✓ Escena 2 · con token: {yo['usuario']} · {yo['tenant']} · {', '.join(r for r in yo['roles'] if not r.startswith('default'))}")

estado, _ = http(f"{GEST}/yo")
print("✓ Saltarse la puerta tampoco sirve: la gestoría pide token (401)" if estado == 401
      else f"✗ La gestoría directa respondió {estado} sin token")

# La firma: solo la paleógrafa de la institución
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"
ficha = entidad_activo(T, signatura=SIG, ark=f"ark:/99999/av-{SIG.lower()}",
                       manifiesto=f"https://iiif.local/iiif/3/{T}/{SIG}/manifest", imagenes=3, ingestado_por="m.ortega")
Registro(env("SCORPIO_URL")).crear(T, ficha)
activo = ficha["id"]
esperar("La copia queda pendiente", lambda: expedientes(activo), lambda v: v and v[0].get("estado") == "pendiente-validacion")
print(f"✓ Legajo {SIG}: copia pendiente de validar")

estado, _ = http(f"{API}/api/v1/expedientes?activo={activo}", token=token("p.otro"))
print("✓ Otra institución no puede ver el expediente (403)" if estado == 403 else f"✗ p.otro vio el expediente ({estado})")
for usuario, motivo in [("m.ortega", "no es paleógrafa"), ("p.otro", "es de otra institución")]:
    estado, _ = validar(activo, usuario)
    print(f"✓ {usuario} no puede firmar: {motivo} (403)" if estado == 403 else f"✗ {usuario} firmó o respondió {estado}")
estado, r = validar(activo, "paleografa-test")
if estado != 200 or r.get("validadoPor") != "paleografa-test":
    raise SystemExit(f"✗ La paleógrafa no pudo firmar ({estado}): {r}")
fin = esperar("El proceso termina", lambda: expedientes(activo), lambda v: v and v[0].get("estado") == "completado", 30)
print(f"✓ Escena 5 · firma de {fin[0]['validadoPor']}, tomada de su token; proceso completado")
print("Parte 8 completada: escenas 1, 2 y 5 con identidad real (tramos 1–2 y 13).")
