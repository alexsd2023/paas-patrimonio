"""Producto · el legajo de la archivera.

Vistas (dentro de la consola, en /panel/productos/legajo):
    ""          Legajos   lista de mi institución y el recorrido de uno
    /entregar   Entregar  la archivera entrega un legajo (→ sala de lectura IIIF)
    /validar    Validar   copias del taller esperando la firma de una paleógrafa (→ gestoría)
    /tramos     Tramos    el recorrido del producto y qué pieza del núcleo aporta cada tramo

API: /api/legajos · /api/legajo · /api/cajas · /api/pendientes · POST /api/ingesta · POST /api/validar

Solo habla con el PaaS a través de ``nucleo`` (ver services/panel/nucleo.py).
"""
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from sdk.registro import urn_transcripcion
from productos.legajo import vistas as V
from productos.legajo.datos import pasos, resumen, v


def _cuerpo(r) -> Any:
    try:
        return r.json()
    except ValueError:
        return {"detail": r.text}


def _url_modelo(mlflow: Optional[str], modelo: Optional[str], run: Optional[str]) -> Optional[str]:
    """La versión del modelo en la interfaz de MLflow (solo si salió del registro: tiene run)."""
    if not (mlflow and modelo and run and "@" in modelo):
        return None
    nombre, version = modelo.split("@", 1)
    return f"{mlflow}/#/models/{quote(nombre)}/versions/{quote(version)}"


def montar(nucleo, producto) -> APIRouter:
    r = APIRouter()
    iiif, gestoria = nucleo.servicio("iiif"), nucleo.servicio("gestoria")

    # ---------- vistas ----------
    @r.get("")
    def legajos_v(req: Request):
        return nucleo.pagina(req, producto.id, "legajos", V.LEGAJOS, V.SCRIPT + V.SCRIPT_LEGAJOS, V.ESTILO)

    @r.get("/entregar")
    def entregar_v(req: Request):
        quien = nucleo.yo(req)
        cuerpo = V.ENTREGAR if quien.tiene("archivera") else V.SOLO_ARCHIVERA
        return nucleo.pagina(req, producto.id, "entregar", cuerpo, V.SCRIPT + V.SCRIPT_ENTREGAR, V.ESTILO)

    @r.get("/validar")
    def validar_v(req: Request):
        return nucleo.pagina(req, producto.id, "validar", V.VALIDAR, V.SCRIPT + V.SCRIPT_VALIDAR, V.ESTILO)

    @r.get("/tramos")
    def tramos_v(req: Request):
        return nucleo.pagina(req, producto.id, "tramos", V.tramos_html(producto.tramos), V.SCRIPT, V.ESTILO)

    # ---------- consultar ----------
    @r.get("/api/legajos")
    def legajos(req: Request):
        quien = nucleo.yo(req)
        copias = {v(c, "deActivo"): c for c in nucleo.registro.listar(quien.tenant, "Transcripcion")}
        filas = [resumen(a, copias.get(a["id"])) for a in nucleo.registro.listar(quien.tenant, "ActivoPatrimonial")]
        return sorted(filas, key=lambda f: f.get("creado") or "", reverse=True)

    @r.get("/api/pendientes")
    def pendientes(req: Request):
        """Copias del taller que esperan la firma de una paleógrafa de mi institución."""
        quien = nucleo.yo(req)
        activos = {a["id"]: a for a in nucleo.registro.listar(quien.tenant, "ActivoPatrimonial")}
        out = []
        for c in nucleo.registro.listar(quien.tenant, "Transcripcion"):
            if v(c, "estado") != "pendiente-validacion":
                continue
            a = activos.get(v(c, "deActivo"))
            out.append({"activo": v(c, "deActivo"), "signatura": v(a, "signatura"), "modelo": v(c, "modelo"),
                        "lineas": v(c, "lineas"), "confianza": v(c, "confianza"), "texto": v(c, "texto"),
                        "creado": c.get("createdAt")})
        return sorted(out, key=lambda x: x.get("creado") or "")

    @r.get("/api/cajas")
    def cajas(req: Request):
        """Dónde puede guardarse un legajo: cajas del catastro agrupadas por depósito."""
        quien = nucleo.yo(req)
        deps = {d["id"]: v(d, "nombre") for d in nucleo.registro.listar(quien.tenant, "Deposito")}
        grupos: Dict[str, List[str]] = {}
        for c in nucleo.registro.listar(quien.tenant, "Caja"):
            grupos.setdefault(deps.get(v(c, "enDeposito"), "Sin depósito"), []).append(v(c, "nombre"))
        return [{"deposito": k, "cajas": sorted(x for x in val if x)} for k, val in sorted(grupos.items())]

    @r.get("/api/legajo")
    def legajo(req: Request, activo: str):
        quien = nucleo.yo(req)
        nucleo.de_mi_institucion(activo, quien)
        reg = nucleo.registro
        ficha = reg.leer(quien.tenant, activo)
        if not ficha:
            raise HTTPException(404, "no existe")
        copia = reg.leer(quien.tenant, urn_transcripcion(activo))
        avisos: List[str] = []
        try:
            procs = nucleo.expedientes.listar(activo)
            proceso: Optional[dict] = procs[0] if procs else None
        except Exception as e:  # noqa: BLE001  Temporal no disponible
            proceso, _ = None, avisos.append(f"Procesos (Temporal) no responde: {e}")
        try:
            actas = nucleo.actas(activo)
        except OSError as e:
            actas, _ = [], avisos.append(f"El notario no responde: {e}")
        ubicacion = None
        caja = reg.leer(quien.tenant, v(ficha, "enCaja")) if v(ficha, "enCaja") else None
        if caja:
            dep = reg.leer(quien.tenant, v(caja, "enDeposito")) or {}
            ubicacion = {"caja": v(caja, "nombre"), "deposito": v(dep, "nombre"), "estado": v(dep, "estadoAmbiental"),
                         "temperatura": v(dep, "temperatura"), "humedad": v(dep, "humedad")}
        pub = nucleo.api_publico
        man = v(ficha, "manifiesto") or ""
        miniaturas = []
        if man.startswith(pub) and man.endswith("/manifest"):
            base = man[: -len("/manifest")]
            miniaturas = [f"{base}/{n}/full/400,/0/default.jpg" for n in range(1, min(v(ficha, "imagenes", 0), 12) + 1)]
        tui = nucleo.enlaces.get("temporal")
        return {
            "resumen": resumen(ficha, copia),
            "ubicacion": ubicacion,
            "ark": v(ficha, "ark"),
            "pasos": pasos(ficha, copia, proceso, actas),
            "proceso": proceso,
            "copia": {"modelo": v(copia, "modelo"), "estado": v(copia, "estado"), "lineas": v(copia, "lineas"),
                      "confianza": v(copia, "confianza"), "validadoPor": v(copia, "validadoPor"),
                      "texto": v(copia, "texto"), "modeloRun": v(copia, "modeloRun"),
                      "datosVersion": v(copia, "datosVersion"), "cerModelo": v(copia, "cerModelo"),
                      "modeloUrl": _url_modelo(nucleo.enlaces.get("mlflow"), v(copia, "modelo"), v(copia, "modeloRun"))}
            if copia else None,
            "actas": actas,
            "manifiesto": man if man.startswith(pub) else None,
            "miniaturas": miniaturas,
            "visor": f"{pub}/iiif/visor/{quien.tenant}/{v(ficha, 'signatura')}" if miniaturas else None,
            "temporal": (f"{tui}/namespaces/default/workflows/{quote(proceso['id'], safe='')}"
                         if proceso and tui else None),
            "avisos": avisos,
        }

    # ---------- actuar (siempre con el token de quien está en la consola) ----------
    @r.post("/api/ingesta")
    def ingesta(req: Request, signatura: str = Form(...), imagenes: List[UploadFile] = File(...),
                caja: Optional[str] = Form(None)):
        quien = nucleo.yo(req)
        if not quien.tiene("archivera"):
            raise HTTPException(403, "solo la archivera entrega legajos")
        ficheros = [("imagenes", (f.filename or f"imagen{n}.jpg", f.file.read(), f.content_type or "image/jpeg"))
                    for n, f in enumerate(imagenes, start=1)]
        try:
            resp = httpx.post(f"{iiif}/ingestas", data={"signatura": signatura, **({"caja": caja} if caja else {})},
                              files=ficheros, timeout=120, headers={"Authorization": f"Bearer {nucleo.token(req)}"})
        except httpx.HTTPError as e:
            raise HTTPException(503, f"La sala de lectura no responde: {e}")
        return JSONResponse(_cuerpo(resp), status_code=resp.status_code)

    @r.post("/api/validar")
    def validar(req: Request, peticion: Dict[str, Any] = Body(...)):
        nucleo.yo(req)
        try:
            resp = httpx.post(f"{gestoria}/expedientes/validar", json={"activo": peticion.get("activo")}, timeout=30,
                              headers={"Authorization": f"Bearer {nucleo.token(req)}"})
        except httpx.HTTPError as e:
            raise HTTPException(503, f"La gestoría no responde: {e}")
        return JSONResponse(_cuerpo(resp), status_code=resp.status_code)

    return r
