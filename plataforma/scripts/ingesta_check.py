"""Parte 9 · escenas 1 a 5 sin atajos: la archivera sube el legajo por la puerta y todo sigue solo.

Genera 3 folios sintéticos (ficticios), los sube con el token de m.ortega y recorre el caso
hasta la firma de la paleógrafa.
Uso (desde plataforma/, con el venv activo):  python scripts/ingesta_check.py
"""
import io
import json
import mimetypes  # noqa: F401
import urllib.request
import uuid

from PIL import Image, ImageDraw

from _comun import env, esperar, expedientes, http, token, validar  # noqa: I100

API = env("API_URL")
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"


def folio(n: int) -> bytes:
    im = Image.new("RGB", (1200, 1650), (236, 226, 201))
    d = ImageDraw.Draw(im)
    for i in range(28):
        y = 160 + i * 48
        d.line([(140, y), (1060 - (i * 37) % 260, y)], fill=(70, 55, 40), width=3)
    d.text((1040, 70), f"f. {n}r", fill=(70, 55, 40))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return b.getvalue()


def multipart(campos, ficheros):
    limite = uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for nombre, (fn, datos, tipo) in ficheros:
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{nombre}"; filename="{fn}"\r\n'
                      f'Content-Type: {tipo}\r\n\r\n'.encode() + datos + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def subir(tok):
    cuerpo, tipo = multipart({"signatura": SIG}, [("imagenes", (f"f{n}.jpg", folio(n), "image/jpeg")) for n in (1, 2, 3)])
    cab = {"Content-Type": tipo}
    if tok:
        cab["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(f"{API}/api/v1/ingestas", data=cuerpo, method="POST", headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# Escenas 1–2 · la archivera se identifica y entrega el legajo por la puerta
estado, _ = subir(None)
print("✓ Sin token no se puede entregar (401)" if estado == 401 else f"✗ Sin token devolvió {estado}")
estado, _ = subir(token("paleografa-test"))
print("✓ Una paleógrafa no ingresa legajos (403)" if estado == 403 else f"✗ La paleógrafa obtuvo {estado}")
estado, r = subir(token("m.ortega"))
if estado != 202:
    raise SystemExit(f"✗ La ingesta falló ({estado}): {r}")
activo = r["activo"]
print(f"✓ Escenas 1–2 · m.ortega entrega {SIG} (3 imágenes) por la puerta: 202")

# Tramos 3–4 · la sala de lectura sirve el legajo con IIIF y lo inscribe en el catastro
estado, man = http(r["manifiesto"])
if estado != 200 or len(man.get("items", [])) != 3:
    raise SystemExit(f"✗ El manifiesto no está bien ({estado}): {str(man)[:200]}")
img = man["items"][0]["items"][0]["items"][0]["body"]["service"][0]["id"]
estado, info = http(f"{img}/info.json")
print(f"✓ Escena 3 · manifiesto IIIF con 3 lienzos; imagen 1 de {info['width']}×{info['height']} px")
estado, _ = subir(token("m.ortega"))
print("✓ La misma signatura no se ingresa dos veces (409)" if estado == 409 else f"✗ Repetir devolvió {estado}")

# Escenas 3–5 · todo lo demás sigue solo
exp = esperar("La copia queda pendiente", lambda: expedientes(activo),
              lambda v: v and v[0].get("estado") == "pendiente-validacion")[0]
print(f"✓ Escena 4 · proceso {exp['proceso']}: copia de {exp['modelo']} pendiente de validar")
estado, f = validar(activo, "paleografa-test")
if estado != 200:
    raise SystemExit(f"✗ La paleógrafa no pudo firmar ({estado}): {f}")
esperar("El proceso termina", lambda: expedientes(activo), lambda v: v and v[0].get("estado") == "completado", 30)
print("✓ Escena 5 · la paleógrafa firma con su identidad; proceso completado")
print(f"\nVisor del legajo: {r['visor']}")
print("Parte 9 completada: escenas 1 a 5 sin atajos (tramos 1–13).")
