"""Sala de lectura · adaptador IIIF (tramos 2–4 del caso). Primer módulo hecho con el SDK.

Cumple las cuatro reglas del contrato:
  ID   valida el token de Keycloak (sdk.identidad): solo una archivera sube legajos, y a su institución
  API  detrás de APISIX: POST /api/v1/ingestas (con token) y /iiif/* (lectura pública)
  DAT  inscribe el ActivoPatrimonial en el catastro (sdk.registro) con la URL de su manifiesto
  EV   no publica cartas él mismo: el catastro avisa al puente, que envía legajo.ingestado

    POST /ingestas   multipart: signatura + imagenes[] (+ caja)  → 202 {activo, manifiesto, visor}
    GET  /iiif/3/{tenant}/{signatura}/manifest                   manifiesto IIIF Presentation 3
    GET  /iiif/3/{tenant}/{signatura}/{n}/info.json              IIIF Image API 3, nivel 0
    GET  /iiif/3/{tenant}/{signatura}/{n}/full/{size}/0/default.jpg
    GET  /iiif/visor/{tenant}/{signatura}                        visor Mirador
    GET  /salud

Las imágenes se guardan en disco por institución; en producción irán a S3/MinIO.
La lectura es pública por ahora: las políticas de uso (embargo, solo consulta…) llegan con el Data Space.
"""
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from PIL import Image

from sdk.identidad import Identidad, NoAutorizado, Verificador, token_de
from sdk.registro import Registro, entidad_activo, urn_activo
from sdk.trazas import configurar, marcar, traceparent
from services.iiif.iiif import info_json, manifiesto, tamanos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("iiif")

SIGNATURA = re.compile(r"^[A-Za-z0-9-]{1,64}$")
TENANT = re.compile(r"^[a-z0-9-]{1,64}$")
MAX_IMAGENES, MAX_BYTES = 200, 50 * 1024 * 1024
CORS = {"Access-Control-Allow-Origin": "*"}  # costumbre IIIF: cualquier visor puede leer


def crear_app(*, datos: str, publico: str, registro=None, verificador=None) -> FastAPI:
    app = FastAPI(title="Sala de lectura (IIIF)", version="0.1.0")
    raiz_datos = Path(datos)
    base_iiif = publico.rstrip("/") + "/iiif/3"
    estado = {"reg": registro}

    def reg() -> Registro:
        if estado["reg"] is None:
            estado["reg"] = Registro(os.environ["SCORPIO_URL"])
        return estado["reg"]

    def quien(authorization: Optional[str] = Header(None), x_access_token: Optional[str] = Header(None)) -> Identidad:
        if verificador is None:
            raise HTTPException(503, "identidad no configurada")
        try:
            return verificador.verificar(token_de(authorization, x_access_token))
        except NoAutorizado as e:
            raise HTTPException(e.codigo, e.motivo)

    def carpeta(tenant: str, signatura: str) -> Path:
        if not TENANT.match(tenant) or not SIGNATURA.match(signatura):
            raise HTTPException(404, "no existe")
        return raiz_datos / tenant / signatura

    @app.get("/salud")
    def salud():
        return {"ok": True}

    # ---------- ingesta (tramos 2–4) ----------
    @app.post("/ingestas", status_code=202)
    def ingestar(signatura: str = Form(...), imagenes: List[UploadFile] = File(...),
                 caja: Optional[str] = Form(None), yo: Identidad = Depends(quien)):
        if not yo.tiene("archivera"):
            raise HTTPException(403, "solo una archivera puede ingresar legajos")
        if not SIGNATURA.match(signatura):
            raise HTTPException(400, "signatura no válida (letras, números y guiones)")
        if caja is not None and not SIGNATURA.match(caja or "x"):
            raise HTTPException(400, "caja no válida")
        caja = caja or None
        if not 1 <= len(imagenes) <= MAX_IMAGENES:
            raise HTTPException(400, f"entre 1 y {MAX_IMAGENES} imágenes")
        destino = raiz_datos / yo.tenant / signatura
        if (destino / "manifest.json").exists() or reg().leer(yo.tenant, urn_activo(yo.tenant, signatura)):
            raise HTTPException(409, f"el legajo {signatura} ya está ingresado")

        # 1 · Guardar las imágenes (como JPEG, comprobando que son imágenes)
        dims = []
        destino.mkdir(parents=True, exist_ok=True)
        for n, f in enumerate(imagenes, start=1):
            contenido = f.file.read(MAX_BYTES + 1)
            if len(contenido) > MAX_BYTES:
                raise HTTPException(413, f"{f.filename}: más de 50 MB")
            try:
                im = Image.open(io.BytesIO(contenido))
                im.load()
            except Exception:
                raise HTTPException(400, f"{f.filename}: no es una imagen")
            im = im.convert("RGB")
            im.save(destino / f"{n}.jpg", "JPEG", quality=92)
            for t in tamanos(*im.size)[:-1]:
                im.resize((t["width"], t["height"])).save(destino / f"{n}_{t['width']}.jpg", "JPEG", quality=85)
            dims.append(im.size)

        # 2 · Manifiesto IIIF
        man = manifiesto(base_iiif, yo.tenant, signatura, dims, yo.usuario)
        (destino / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")

        # 3 · Inscribir la ficha en el catastro (el catastro avisará al puente)
        ficha = entidad_activo(yo.tenant, signatura=signatura, ark=f"ark:/99999/{yo.tenant}-{signatura.lower()}",
                               manifiesto=man["id"], imagenes=len(dims), ingestado_por=yo.usuario, caja=caja,
                               traza=traceparent())
        marcar(paas__legajo=ficha["id"], paas__tenant=yo.tenant, enduser__id=yo.usuario)
        codigo = reg().crear(yo.tenant, ficha)
        if codigo != 201:
            raise HTTPException(502, f"el catastro respondió {codigo} al inscribir el legajo")
        log.info("legajo %s de %s ingresado por %s (%d imágenes)", signatura, yo.tenant, yo.usuario, len(dims))
        return {"activo": ficha["id"], "manifiesto": man["id"], "imagenes": len(dims),
                "visor": f"{publico.rstrip('/')}/iiif/visor/{yo.tenant}/{signatura}"}

    # ---------- lectura IIIF (pública) ----------
    @app.get("/iiif/3/{tenant}/{signatura}/manifest")
    def leer_manifiesto(tenant: str, signatura: str):
        p = carpeta(tenant, signatura) / "manifest.json"
        if not p.exists():
            raise HTTPException(404, "no existe")
        return JSONResponse(json.loads(p.read_text(encoding="utf-8")), headers=CORS,
                            media_type="application/ld+json;profile=\"http://iiif.io/api/presentation/3/context.json\"")

    def ruta_imagen(tenant: str, signatura: str, n: int) -> Path:
        p = carpeta(tenant, signatura) / f"{n}.jpg"
        if not p.exists():
            raise HTTPException(404, "no existe")
        return p

    @app.get("/iiif/3/{tenant}/{signatura}/{n}/info.json")
    def info(tenant: str, signatura: str, n: int):
        with Image.open(ruta_imagen(tenant, signatura, n)) as im:
            w, h = im.size
        return JSONResponse(info_json(f"{base_iiif}/{tenant}/{signatura}/{n}", w, h), headers=CORS,
                            media_type="application/ld+json;profile=\"http://iiif.io/api/image/3/context.json\"")

    @app.get("/iiif/3/{tenant}/{signatura}/{n}/{region}/{size}/{rotation}/{calidad}")
    def imagen(tenant: str, signatura: str, n: int, region: str, size: str, rotation: str, calidad: str):
        p = ruta_imagen(tenant, signatura, n)
        if region != "full" or rotation != "0" or calidad != "default.jpg":
            raise HTTPException(501, "nivel 0: solo full/…/0/default.jpg")
        with Image.open(p) as im:
            w, h = im.size
        ofrecidos = {f"{t['width']},{t['height']}": t["width"] for t in tamanos(w, h)}
        ofrecidos.update({f"{t['width']},": t["width"] for t in tamanos(w, h)})
        if size == "max" or ofrecidos.get(size) == w:
            fichero = p
        elif size in ofrecidos:
            fichero = p.with_name(f"{n}_{ofrecidos[size]}.jpg")
        else:
            raise HTTPException(501, f"nivel 0: tamaños disponibles {', '.join(['max', *ofrecidos])}")
        return Response(fichero.read_bytes(), media_type="image/jpeg", headers=CORS)

    @app.get("/iiif/visor/{tenant}/{signatura}", response_class=HTMLResponse)
    def visor(tenant: str, signatura: str):
        carpeta(tenant, signatura)
        man = f"{base_iiif}/{tenant}/{signatura}/manifest"
        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Legajo {signatura} · {tenant}</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{{margin:0;height:100%}}#v{{position:absolute;inset:0}}</style></head>
<body><div id="v"></div>
<script src="https://unpkg.com/mirador@3.4.3/dist/mirador.min.js"></script>
<script>Mirador.viewer({{id:"v",windows:[{{manifestId:"{man}"}}],
window:{{allowClose:false,defaultSideBarPanel:"info",sideBarOpenByDefault:true}},
workspaceControlPanel:{{enabled:false}}}});</script></body></html>"""

    return app


def _verificador() -> Optional[Verificador]:
    jwks, emisor = os.environ.get("KEYCLOAK_JWKS"), os.environ.get("KEYCLOAK_ISSUER")
    return Verificador(jwks, emisor) if jwks and emisor else None


app = crear_app(datos=os.environ.get("IIIF_DATOS", "/data"),
                publico=os.environ.get("IIIF_PUBLICO", "http://localhost:9080"),
                verificador=_verificador())
configurar("iiif", app)
