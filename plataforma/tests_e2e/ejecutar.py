"""Parte 13 · prueba de punta a punta: la plataforma entera, recorrida desde dentro de la red de docker.

1. Espera a que estén listas todas las piezas (núcleo, productos, capacidades).
2. Sirve un repositorio OAI-PMH de prueba (para el conector) y entrena + pone en producción un modelo HTR.
3. Ejecuta, en orden, las comprobaciones de cada parte (scripts/*_check.py), las mismas que se lanzan a mano.
4. Resume qué ha pasado y sale con código 0 solo si todo pasa.

Variables: las de platform/ci.override.yml (servicio «e2e»).
"""
import http.server
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ESPERA_MAX = int(os.environ.get("E2E_ESPERA_S", "600"))

# (nombre, cómo se comprueba, dónde)
PIEZAS = [
    ("Identidad · Keycloak", "http", "http://keycloak:8080/realms/paas"),
    ("Correos · Kafka", "tcp", "kafka:29092"),
    ("Puente", "http", "http://puente:8080/salud"),
    ("Catastro · Scorpio", "http", "http://scorpio:9090/ngsi-ld/v1/types"),
    ("Procesos · Temporal", "tcp", "temporal:7233"),
    ("Notario", "http", "http://procedencia:8080/salud"),
    ("Libro del notario · Fuseki", "tcp", "fuseki:3030"),
    ("Trazas · Jaeger", "tcp", "jaeger:16686"),
    ("Modelos · MLflow", "http", "http://mlflow:5000/health"),
    ("Catálogo", "http", "http://catalogo:8080/salud"),
    ("Instituciones", "http", "http://instituciones:8080/salud"),
    ("Consola", "http", "http://panel:8080/panel"),
    ("Puerta · APISIX", "http", "http://apisix:9080/panel"),
    ("Gestoría (legajo)", "http", "http://gestoria:8080/salud"),
    ("Taller HTR (legajo)", "http", "http://htr:8080/salud"),
    ("Sala de lectura IIIF (legajo)", "tcp", "iiif:8080"),
    ("Conservación (gemelo)", "http", "http://conservacion:8080/salud"),
    ("Modernizador (capacidad)", "http", "http://srv-modernizador-demo:8080/salud"),
]

PASOS = [  # (parte, script, argumentos)
    ("1 · Kafka", "scripts/kafka_check.py", []),
    ("2 · Contratos", "scripts/validar_contratos.py", []),
    ("3 · Librería de eventos", "scripts/eventos_check.py", []),
    ("4 · Puente", "scripts/puente_check.py", []),
    ("5 · Consumidores", "scripts/consumidores_check.py", []),
    ("6 · Catastro", "scripts/registro_check.py", []),
    ("7 · Procesos", "scripts/proceso_check.py", []),
    ("8 · Puerta", "scripts/puerta_check.py", []),
    ("9 · Sala de lectura", "scripts/ingesta_check.py", []),
    ("Gemelo digital", "scripts/gemelo_check.py", []),
    ("10 · Notario", "scripts/fuseki_check.py", []),
    ("11 · Trazas", "scripts/traza_check.py", []),
    ("Capacidades, flujos y conectores", "scripts/catalogo_check.py", []),
    ("Una institución nueva, sola", "scripts/institucion_check.py", []),
    ("12 · Modelo en producción", "modelos/htr/entrenar.py", ["--produccion", "--datos", "tests_e2e/gt"]),
    ("12 · Copia con linaje", "scripts/modelo_check.py", []),
]


def lista(tipo: str, destino: str) -> bool:
    try:
        if tipo == "http":
            with urllib.request.urlopen(destino, timeout=4) as r:
                return r.status < 500
        host, puerto = destino.rsplit(":", 1)
        with socket.create_connection((host, int(puerto)), timeout=4):
            return True
    except Exception:  # noqa: BLE001
        return False


def esperar_piezas() -> bool:
    fin, pendientes = time.time() + ESPERA_MAX, list(PIEZAS)
    print(f"Esperando a {len(pendientes)} piezas (máx. {ESPERA_MAX} s)…", flush=True)
    while pendientes and time.time() < fin:
        for p in list(pendientes):
            if lista(p[1], p[2]):
                print(f"  ✓ {p[0]}", flush=True)
                pendientes.remove(p)
        if pendientes:
            time.sleep(5)
    for p in pendientes:
        print(f"  ✗ {p[0]} no respondió ({p[2]})", flush=True)
    return not pendientes


def servir_oai():
    """Repositorio OAI-PMH de prueba en http://e2e:8000/oai.xml (ignora los parámetros: una sola página)."""
    carpeta = str(RAIZ / "tests_e2e" / "oai")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=carpeta, **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("0.0.0.0", 8000), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main() -> int:
    t0 = time.time()
    if not esperar_piezas():
        return 2
    servir_oai()
    print("\nLas piezas responden; doy 20 s a que terminen de arrancar (suscripciones, workers)…", flush=True)
    time.sleep(20)
    resultados = []
    for parte, script, args in PASOS:
        print(f"\n{'=' * 70}\n▶ {parte} · {script}\n{'=' * 70}", flush=True)
        ini = time.time()
        r = subprocess.run([sys.executable, script, *args], cwd=RAIZ, env=os.environ.copy(), timeout=600)
        resultados.append((parte, r.returncode == 0, time.time() - ini))
        if r.returncode != 0:
            print(f"✗ {parte} falló (código {r.returncode})", flush=True)
    print(f"\n{'=' * 70}\nRESUMEN · {time.time() - t0:.0f} s\n{'=' * 70}")
    for parte, ok, s in resultados:
        print(f"  {'✓' if ok else '✗'} {parte:<36} {s:6.1f} s")
    fallos = [p for p, ok, _ in resultados if not ok]
    print(f"\n{'Todo pasa: el walking skeleton funciona de punta a punta.' if not fallos else f'Fallan {len(fallos)}: ' + ', '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
