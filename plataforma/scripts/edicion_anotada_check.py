"""Demo de Scriptorium en el PaaS: la receta «Edición anotada» contra la API REAL de Ameyalli.

    python scripts/edicion_anotada_check.py [--motor agent|mt5|latamgpt|rag]

1. Las tres capacidades de Ameyalli están en el catálogo (corrector, modernizador, entidades en el original).
2. Lanza la receta sobre unas líneas de HTR de un protocolo sevillano: corrige → moderniza → localiza entidades.
3. La paleógrafa firma la edición; el resultado queda en el catastro con la procedencia de cada paso.
4. Enseña las entidades marcadas sobre la grafía original (Johan Peres ↔ Juan Pérez).

Necesita salida a internet desde el servidor. Si el despliegue de Ameyalli exige clave, ponla antes en la
consola: Mi institución → Secretos → SCRIPTORIUM_API_KEY (o como admin.paas, para toda la plataforma).
Los Spaces de Hugging Face tardan en despertar: la primera ejecución puede llevar varios minutos.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

from _comun import env, esperar, http, token

API = env("API_URL")
HTR = ("En la cibdad de Sevylla a treze dias del mes de março año del señor de mill e quinientos e diez años\n"
       "ante mi Johan Peres escrivano publico de Sevylla e de los testigos de yuso escriptos parescio presente\n"
       "Diego Ferrandez vezino desta dicha cibdad en la collacion de santa maria")

a = argparse.ArgumentParser()
a.add_argument("--motor", default="agent", choices=["agent", "mt5", "latamgpt", "rag"])
motor = a.parse_args().motor

est, servicios = http(f"{API}/api/v1/servicios", token=token("m.ortega"))
ids = {s["id"] for s in servicios or []}
faltan = {"corrector-htr", "modernizador-paleografico", "entidades-en-el-original"} - ids
if est != 200 or faltan:
    sys.exit(f"✗ Faltan capacidades en el catálogo: {sorted(faltan)} (¿reconstruiste el catálogo?)")
print("✓ Las tres herramientas de Ameyalli están en el catálogo")

receta = yaml.safe_load((Path(__file__).resolve().parents[1] / "flujos" / "edicion-anotada.yaml").read_text(encoding="utf-8"))
receta["pasos"][0]["parametros"] = {"motor": motor}
est, r = http(f"{API}/api/v1/flujos", {"receta": receta, "entrada": {"documento": {"texto": HTR}}}, token=token("m.ortega"))
if est != 202:
    sys.exit(f"✗ No se pudo lanzar la receta ({est}): {r}")
fid = r["id"]
print(f"✓ Receta lanzada ({fid}): {' → '.join(p.get('servicio') or 'firma ' + p['rol'] for p in r['plan']['pasos'])}"
      f" · motor de corrección: {motor}")


def estado(usuario="m.ortega"):
    return http(f"{API}/api/v1/flujos/{fid}", token=token(usuario))[1]


e = esperar("los tres pasos de Ameyalli (los Spaces pueden tardar en despertar)", estado,
            lambda x: isinstance(x, dict) and x.get("estado") in ("esperando-firma", "error", "terminado"), 900,
            pista="docker compose logs --tail 40 catalogo")
if e["estado"] == "error":
    sys.exit(f"✗ La receta falló: {e.get('error')}\n  Si es la clave: Mi institución → Secretos → SCRIPTORIUM_API_KEY")
est, r = http(f"{API}/api/v1/flujos/{fid}/firmar", {"decision": "aprueba", "comentario": "edición revisada"},
              token=token("paleografa-test"))
if est != 200:
    sys.exit(f"✗ La paleógrafa no pudo firmar ({est}): {r}")
print(f"✓ Firmada por {r['firmadoPor']}")
final = esperar("receta terminada", estado, lambda x: isinstance(x, dict) and x.get("estado") in ("terminado", "error"),
                120, pista="docker compose logs --tail 40 catalogo")
if final["estado"] != "terminado":
    sys.exit(f"✗ Terminó con error: {final.get('error')}")

from sdk.registro import Registro  # noqa: E402
ent = Registro(env("SCORPIO_URL")).leer("archivo-villanueva", final["resultado"])
if not ent:
    sys.exit(f"✗ {final['resultado']} no está en el catastro")
doc = json.loads(ent["documento"]["value"]) if "documento" in ent else {}
proc = json.loads(ent["procedencia"]["value"])
print(f"✓ En el catastro: {final['resultado']}")
print("  Procedencia: " + " → ".join(f"{x['servicio']} {x['version']}" for x in proc["servicios"])
      + " · firma: " + ", ".join(x["usuario"] for x in proc["firmas"]))
if doc:
    print(f"\n  Modernizado:\n    {doc['modernizado']['texto'][:200]}…")
    print(f"\n  Entidades sobre el ORIGINAL ({len(doc['entidades'])}, {len(doc.get('sin_localizar', []))} sin localizar):")
    for x in doc["entidades"][:15]:
        print(f"    {x['tipo']:<12} «{x['texto']}»  ← {x.get('moderno', '')}  ({x.get('confianza', '–')})")
print("\nTodo bien: la edición anotada de Scriptorium funciona como receta del PaaS.")
