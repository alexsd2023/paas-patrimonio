"""Producto · el gemelo digital del archivo.

Vistas (dentro de la consola, en /panel/productos/gemelo):
    ""        Depósitos        lecturas, umbrales y estado de cada depósito; simular una fuga o una avería
    /cajas    Cajas y legajos  qué legajos hay en cada caja y en qué condiciones están

API: /api/depositos · /api/cajas · POST /api/escenario

Sus servicios propios (sensores, conservacion) se llaman por ``nucleo.servicio``.
"""
import json
import urllib.request
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from productos.gemelo import vistas as V


def v(entidad, attr, defecto=None):
    if not entidad or attr not in entidad:
        return defecto
    a = entidad[attr]
    return a.get("value", a.get("object", defecto)) if isinstance(a, dict) else a


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def montar(nucleo, producto) -> APIRouter:
    r = APIRouter()
    conservacion, sensores = nucleo.servicio("conservacion"), nucleo.servicio("sensores")

    @r.get("")
    def depositos_v(req: Request):
        return nucleo.pagina(req, producto.id, "depositos", V.DEPOSITOS, V.SCRIPT_DEPOSITOS, V.ESTILO)

    @r.get("/cajas")
    def cajas_v(req: Request):
        return nucleo.pagina(req, producto.id, "cajas", V.CAJAS, V.SCRIPT_CAJAS, V.ESTILO)

    @r.get("/api/depositos")
    def depositos(req: Request):
        quien = nucleo.yo(req)
        try:
            vivos = {d["deposito"]: d for d in _get(f"{conservacion}/depositos?tenant={quien.tenant}")}
        except OSError:
            vivos = {}
        try:
            esc = {d["deposito"]: d["escenario"] for d in _get(f"{sensores}/escenarios") if d["tenant"] == quien.tenant}
        except OSError:
            esc = {}
        reg = nucleo.registro
        cajas = reg.listar(quien.tenant, "Caja")
        legajos = reg.listar(quien.tenant, "ActivoPatrimonial")
        out = []
        for d in reg.listar(quien.tenant, "Deposito"):
            mis_cajas = {c["id"]: v(c, "nombre") for c in cajas if v(c, "enDeposito") == d["id"]}
            codigo = d["id"].split(":")[-1]
            vivo = vivos.get(d["id"], {})
            out.append({
                "deposito": d["id"], "codigo": codigo, "nombre": v(d, "nombre"),
                "estado": v(d, "estadoAmbiental", "ok"), "alertas": vivo.get("alertas", []),
                "temperatura": v(d, "temperatura"), "humedad": v(d, "humedad"),
                "umbrales": {k: v(d, k) for k in ("temperaturaMin", "temperaturaMax", "humedadMin", "humedadMax")},
                "cajas": sorted(x for x in mis_cajas.values() if x),
                "legajos": sum(1 for a in legajos if v(a, "enCaja") in mis_cajas),
                "serie": vivo.get("serie", []), "escenario": esc.get(codigo, "normal"),
            })
        return sorted(out, key=lambda x: x["codigo"])

    @r.get("/api/cajas")
    def cajas(req: Request):
        quien = nucleo.yo(req)
        reg = nucleo.registro
        deps = {d["id"]: d for d in reg.listar(quien.tenant, "Deposito")}
        legajos = reg.listar(quien.tenant, "ActivoPatrimonial")
        out: List[Dict[str, Any]] = []
        for c in reg.listar(quien.tenant, "Caja"):
            d = deps.get(v(c, "enDeposito"), {})
            out.append({"caja": v(c, "nombre"), "deposito": v(d, "nombre"), "estado": v(d, "estadoAmbiental", "ok"),
                        "temperatura": v(d, "temperatura"), "humedad": v(d, "humedad"),
                        "legajos": sorted(v(a, "signatura") for a in legajos if v(a, "enCaja") == c["id"])})
        return sorted(out, key=lambda x: (x["deposito"] or "", x["caja"] or ""))

    @r.post("/api/escenario")
    def escenario(req: Request, peticion: Dict[str, Any] = Body(...)):
        quien = nucleo.yo(req)
        if not quien.tiene("archivera"):
            raise HTTPException(403, "solo la archivera puede lanzar simulaciones")
        try:
            resp = httpx.post(f"{sensores}/escenario", timeout=10,
                              json={"tenant": quien.tenant, "deposito": peticion.get("deposito"),
                                    "escenario": peticion.get("escenario")})
        except httpx.HTTPError as e:
            raise HTTPException(503, f"Los sensores no responden: {e}")
        try:
            cuerpo = resp.json()
        except ValueError:
            cuerpo = {"detail": resp.text}
        return JSONResponse(cuerpo, status_code=resp.status_code)

    return r
