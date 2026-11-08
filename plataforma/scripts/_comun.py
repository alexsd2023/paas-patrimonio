"""Utilidades comunes de los scripts de comprobación: .env, HTTP y la puerta con token."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

CLAVES = {"m.ortega": "archivera", "paleografa-test": "paleografa", "p.otro": "paleografa"}


def env(k: str) -> str:
    return (os.environ.get(k) or sys.exit(f"Falta {k} en plataforma/.env")).rstrip("/")


def http(url, cuerpo=None, token=None, metodo=None):
    cab = {"Content-Type": "application/json"}
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                 method=metodo or ("POST" if cuerpo is not None else "GET"), headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            texto = r.read().decode()
            return r.status, json.loads(texto) if texto else None
    except urllib.error.HTTPError as e:
        texto = e.read().decode()
        try:
            return e.code, json.loads(texto)
        except ValueError:
            return e.code, texto
    except urllib.error.URLError as e:
        sys.exit(f"✗ No hay nada escuchando en {url}: {e.reason}.\n"
                 f"  Pista (servidor): docker compose ps keycloak apisix gestoria")


_tokens = {}


def token(usuario: str) -> str:
    if usuario not in _tokens:
        from sdk.identidad import pedir_token
        try:
            _tokens[usuario] = pedir_token(env("KEYCLOAK_URL"), usuario, CLAVES[usuario])
        except OSError as e:
            sys.exit(f"✗ No se pudo obtener el token de {usuario} en {env('KEYCLOAK_URL')}: {e}")
    return _tokens[usuario]


def expedientes(activo: str, usuario: str = "m.ortega"):
    """Consulta el expediente a través de la puerta (APISIX), con el token del usuario."""
    q = urllib.parse.quote(activo, safe="")
    estado, cuerpo = http(f"{env('API_URL')}/api/v1/expedientes?activo={q}", token=token(usuario))
    if estado != 200:
        raise OSError(f"la puerta respondió {estado}: {cuerpo}")
    return cuerpo


def validar(activo: str, usuario: str):
    return http(f"{env('API_URL')}/api/v1/expedientes/validar", {"activo": activo}, token=token(usuario))


def esperar(desc, leer, cumple, segundos=60, pista="docker compose logs --tail 40 gestoria procesos htr"):
    fin, valor = time.time() + segundos, None
    while time.time() < fin:
        try:
            valor = leer()
            if cumple(valor):
                return valor
        except OSError as e:
            valor = str(e)
        time.sleep(1)
    sys.exit(f"✗ {desc}: no ocurrió en {segundos} s (último valor: {valor}).\n  Pista: {pista}")
