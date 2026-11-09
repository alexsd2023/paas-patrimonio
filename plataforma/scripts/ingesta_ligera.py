"""Entregar un legajo de prueba por la puerta, como la archivera (lo usan otras comprobaciones).

    from ingesta_ligera import entregar
    activo = entregar()      # urn del legajo nuevo (3 folios sintéticos, signatura TEST-xxxxxx)
"""
import io
import json
import urllib.error
import urllib.request
import uuid

from _comun import env, token


def folio(n: int) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1200, 1650), (236, 226, 201))
    d = ImageDraw.Draw(im)
    for i in range(28):
        y = 160 + i * 48
        d.line([(140, y), (1060 - (i * 37) % 260, y)], fill=(70, 55, 40), width=3)
    d.text((1040, 70), f"f. {n}r", fill=(70, 55, 40))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return b.getvalue()


def entregar(usuario: str = "m.ortega", folios: int = 3) -> str:
    limite, sig = uuid.uuid4().hex, f"TEST-{uuid.uuid4().hex[:6].upper()}"
    partes = [f'--{limite}\r\nContent-Disposition: form-data; name="signatura"\r\n\r\n{sig}\r\n'.encode()]
    for n in range(1, folios + 1):
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="imagenes"; filename="f{n}.jpg"\r\n'
                      f'Content-Type: image/jpeg\r\n\r\n'.encode() + folio(n) + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    req = urllib.request.Request(f"{env('API_URL')}/api/v1/ingestas", data=b"".join(partes), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={limite}",
                                          "Authorization": f"Bearer {token(usuario)}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["activo"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"✗ La entrega del legajo falló ({e.code}): {e.read().decode()[:300]}")
