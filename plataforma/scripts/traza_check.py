"""Parte 11 · el recorrido de un legajo como una sola traza en Jaeger.

La archivera entrega un legajo, la paleógrafa lo firma, y se busca en Jaeger la traza
del legajo: debe pasar por la sala de lectura, el puente, la gestoría, el proceso,
el taller y el notario.
Uso (desde plataforma/, con el venv activo):  python scripts/traza_check.py
"""
import io
import json
import time
import urllib.parse
import urllib.request
import uuid

from PIL import Image

from _comun import env, esperar, expedientes, token, validar  # noqa: I100

API, JAEGER = env("API_URL"), env("JAEGER_URL")
SIG = f"TRAZA-{uuid.uuid4().hex[:6].upper()}"


def folio():
    b = io.BytesIO()
    Image.new("RGB", (900, 1200), (236, 226, 201)).save(b, "JPEG")
    return b.getvalue()


lim = uuid.uuid4().hex
cuerpo = (f'--{lim}\r\nContent-Disposition: form-data; name="signatura"\r\n\r\n{SIG}\r\n'
          f'--{lim}\r\nContent-Disposition: form-data; name="imagenes"; filename="f1.jpg"\r\n'
          f'Content-Type: image/jpeg\r\n\r\n').encode() + folio() + f"\r\n--{lim}--\r\n".encode()
req = urllib.request.Request(f"{API}/api/v1/ingestas", data=cuerpo, method="POST",
                             headers={"Content-Type": f"multipart/form-data; boundary={lim}",
                                      "Authorization": f"Bearer {token('m.ortega')}"})
with urllib.request.urlopen(req, timeout=60) as r:
    activo = json.loads(r.read())["activo"]
print(f"✓ m.ortega entrega {SIG}")
esperar("Copia pendiente", lambda: expedientes(activo), lambda v: v and v[0].get("estado") == "pendiente-validacion")
validar(activo, "paleografa-test")
esperar("Proceso completado", lambda: expedientes(activo), lambda v: v and v[0].get("estado") == "completado", 30)
print("✓ La paleógrafa firma; proceso completado")
time.sleep(6)   # los servicios envían sus tramos en lotes


def buscar():
    q = urllib.parse.urlencode({"service": "iiif", "tags": json.dumps({"paas.legajo": activo}), "limit": 5,
                                "lookback": "1h"})
    with urllib.request.urlopen(f"{JAEGER}/api/traces?{q}", timeout=15) as r:
        return json.loads(r.read()).get("data") or []


trazas = esperar("La traza del legajo aparece en Jaeger", buscar, lambda v: len(v) >= 1, 30,
                 "docker compose logs --tail 20 jaeger iiif puente")
t = max(trazas, key=lambda x: len(x["spans"]))
servicios = sorted({p["serviceName"] for p in t["processes"].values()})
print(f"✓ Una traza de {len(t['spans'])} tramos por: {', '.join(servicios)}")
faltan = {"iiif", "puente", "gestoria", "procesos", "htr", "procedencia"} - set(servicios)
if faltan:
    print(f"! No aparecen en la misma traza: {', '.join(sorted(faltan))} (revisa sus logs)")
else:
    print("Parte 11 completada: el recorrido del legajo es una sola traza.")
print(f"\nVerla: {JAEGER}/trace/{t['traceID']}")
