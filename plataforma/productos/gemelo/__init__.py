"""Producto · el gemelo digital patrimonial (y, dentro, el gemelo del archivo de antes).

Vistas (dentro de la consola, en /panel/productos/gemelo):
    ""               Inicio          estado del inmueble: ¿qué zona me preocupa hoy y por qué?
    /zona?z=Z01      Zona            series de 7 días con la banda objetivo EN 15757, evaluación y sensores
    /mapa            Mapa            la planta con las zonas y los sensores
    /alertas         Alertas         reconocer y cerrar (con la causa) · el historial del notario
    /configuracion   Configuración   inmueble de ejemplo, zonas, sensores y simulación para la demo
    /depositos, /cajas  llevan a Inicio: una zona de tipo depósito ya enseña sus cajas y legajos

API (la misma, con token, en /api/v1/gemelo/… por la puerta): ver las rutas /api/… de montar().
Cada ruta comprueba el rol: la consola oculta lo no permitido, pero nunca es el único control.

Sus servicios propios (sensores, conservacion) se llaman por ``nucleo.servicio``.
"""
import json
import re
import urllib.request
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from productos.gemelo import modelo as M
from productos.gemelo import vistas_patrimonial as VP
from sdk.registro import urn_deposito

LEER = {"gestor", "conservador", "tecnico", "archivera", "admin-institucion"}
FIRMAR = {"conservador", "archivera", "admin-institucion"}
CONFIGURAR = {"admin-institucion", "archivera"}
CODIGO = re.compile(r"^[A-Za-z0-9-]{1,20}$")


def v(entidad, attr, defecto=None):
    return M.v(entidad, attr, defecto)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def exigir(quien, roles: set, que: str):
    if not set(quien.roles) & roles:
        raise HTTPException(403, f"tu rol no permite {que}")


def montar(nucleo, producto) -> APIRouter:
    r = APIRouter()
    conservacion, sensores = nucleo.servicio("conservacion"), nucleo.servicio("sensores")

    def servicio(metodo: str, url: str, cuerpo=None, params=None, timeout=60):
        """Llama a un servicio propio y traslada su error tal cual (con su código)."""
        try:
            resp = httpx.request(metodo, url, json=cuerpo, params=params, timeout=timeout)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"{url.split('/')[2].split(':')[0]} no responde: {e}")
        try:
            datos = resp.json()
        except ValueError:
            datos = {"detail": resp.text[:300]}
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, datos.get("detail") if isinstance(datos, dict) else datos)
        return datos

    def codigo_ok(cod: str) -> str:
        if not CODIGO.match(cod or ""):
            raise HTTPException(422, "código: letras, cifras y guiones (máx. 20)")
        return cod

    # ---------- vistas ----------
    def vista(id_, cuerpo, script):
        def pintar(req: Request):
            return nucleo.pagina(req, producto.id, id_, cuerpo, script, VP.ESTILO,
                                 datos={"puedeFirmar": bool(set(nucleo.yo(req).roles) & FIRMAR),
                                        "puedeConfigurar": bool(set(nucleo.yo(req).roles) & CONFIGURAR)})
        return pintar

    r.add_api_route("", vista("inicio", VP.INICIO, VP.SCRIPT_INICIO), methods=["GET"])
    r.add_api_route("/zona", vista("zona", VP.ZONA, VP.SCRIPT_ZONA), methods=["GET"])
    r.add_api_route("/mapa", vista("mapa", VP.MAPA, VP.SCRIPT_MAPA), methods=["GET"])
    r.add_api_route("/alertas", vista("alertas", VP.ALERTAS, VP.SCRIPT_ALERTAS), methods=["GET"])
    r.add_api_route("/configuracion", vista("configuracion", VP.CONFIGURACION, VP.SCRIPT_CONFIGURACION), methods=["GET"])

    # Las vistas del gemelo del archivo (Depósitos, Cajas y legajos) se unieron a la de cada zona de tipo depósito.
    # Sus direcciones llevan a Inicio para no romper enlaces guardados; su API (/api/depositos, /api/cajas,
    # /api/escenario) sigue igual.
    @r.get("/depositos")
    @r.get("/cajas")
    def antiguas_v(req: Request):
        return RedirectResponse(req.url.path.rsplit("/", 1)[0] or "/", status_code=301)

    # ---------- API del gemelo patrimonial ----------
    @r.get("/api/inmueble")
    def inmueble(req: Request):
        quien = nucleo.yo(req)
        exigir(quien, LEER, "ver el gemelo")
        reg, t = nucleo.registro, quien.tenant
        edificios = reg.listar(t, "HeritageBuilding")
        zonas = {z["id"]: z for z in reg.listar(t, "HeritageZone")}
        sens = reg.listar(t, "EnvironmentalSensor")
        try:
            resumen = {z["zona"]: z for z in servicio("GET", f"{conservacion}/gemelo/resumen", params={"tenant": t})}
            sin_conservacion = None
        except HTTPException as e:
            resumen, sin_conservacion = {}, e.detail
        alertas = [a for a in reg.listar(t, "ConservationAlert", limite=1000) if v(a, "alertStatus") in ("activa", "reconocida")]
        orden = {"alto": 0, "medio": 1, "bajo": 2, None: 3}
        filas = []
        for zid, z in zonas.items():
            s = resumen.get(zid, {})
            filas.append({"zona": zid, "codigo": M.codigo(zid), "nombre": v(z, "name"), "tipo": v(z, "zoneType"),
                          "materiales": v(z, "dominantMaterials", []), "plano": v(z, "planPosition"),
                          "deposito": v(z, "refDeposito"), **{k: s.get(k) for k in (
                              "nivel", "causa", "desviacion30d", "objetivoHumedad", "objetivoTemperatura", "metodo",
                              "origenDatos", "calculadaEn", "temperatura", "humedad", "alerta")}})
        if any(f["deposito"] for f in filas):
            cajas = {c["id"]: v(c, "enDeposito") for c in reg.listar(t, "Caja", limite=1000)}
            por_dep: Dict[str, int] = {}
            for a in reg.listar(t, "ActivoPatrimonial", limite=1000):
                dep = cajas.get(v(a, "enCaja"))
                if dep:
                    por_dep[dep] = por_dep.get(dep, 0) + 1
            for f in filas:
                f["legajos"] = por_dep.get(f["deposito"], 0) if f["deposito"] else None
        filas.sort(key=lambda f: (orden.get(f["nivel"], 3), f["codigo"]))
        enlazados = {f["deposito"]: f["codigo"] for f in filas if f["deposito"]}
        archivo = [{"id": d["id"], "codigo": M.codigo(d["id"]), "nombre": v(d, "nombre") or v(d, "name") or M.codigo(d["id"]),
                    "zona": enlazados.get(d["id"])} for d in reg.listar(t, "Deposito")]
        e0 = edificios[0] if edificios else None
        return {"edificio": e0 and {"id": e0["id"], "nombre": v(e0, "name"), "proteccion": v(e0, "protectionLevel"),
                                    "ano": v(e0, "yearOfConstruction"), "estilo": v(e0, "architecturalStyle")},
                "zonas": filas, "aviso": sin_conservacion, "depositosArchivo": archivo,
                "kpis": {"zonas": len(filas), "enRiesgo": sum(1 for f in filas if f["nivel"] in ("medio", "alto")),
                         "alertas": len(alertas), "criticas": sum(1 for a in alertas if v(a, "riskLevel") == "alto"),
                         "sensores": len(sens), "sensoresOK": sum(1 for s in sens if v(s, "operStatus") == "OK")}}

    def contenido_deposito(t: str, deposito: str):
        """Las cajas de un depósito del archivo con sus legajos, ordenadas."""
        reg = nucleo.registro
        cajas = {c["id"]: v(c, "nombre") for c in reg.listar(t, "Caja", limite=1000) if v(c, "enDeposito") == deposito}
        por_caja: Dict[str, List[str]] = {cid: [] for cid in cajas}
        for a in reg.listar(t, "ActivoPatrimonial", limite=1000):
            if v(a, "enCaja") in por_caja:
                por_caja[v(a, "enCaja")].append(v(a, "signatura"))
        d = reg.leer(t, deposito)
        return {"deposito": deposito, "nombre": v(d, "nombre", M.codigo(deposito)),
                "cajas": sorted(({"caja": cajas[cid], "legajos": sorted(x for x in ls if x)} for cid, ls in por_caja.items()),
                                key=lambda c: c["caja"] or ""),
                "legajos": sum(len(ls) for ls in por_caja.values())}

    @r.get("/api/zonas/{cod}")
    def zona(cod: str, req: Request, dias: int = 7):
        quien = nucleo.yo(req)
        exigir(quien, LEER, "ver el gemelo")
        reg, t = nucleo.registro, quien.tenant
        z = reg.leer(t, M.urn("HeritageZone", t, codigo_ok(cod)))
        if not z:
            raise HTTPException(404, f"no hay ninguna zona {cod}")
        estado = servicio("GET", f"{conservacion}/gemelo/zonas/{cod}", params={"tenant": t, "dias": max(1, min(dias, 60))})
        ahora = {x["sensor"]: x for x in estado.get("ahora", [])}
        return {"zona": z["id"], "codigo": cod, "nombre": v(z, "name"), "tipo": v(z, "zoneType"),
                "materiales": v(z, "dominantMaterials", []), "area": v(z, "areaSqm"), "deposito": v(z, "refDeposito"),
                "elementos": [{"nombre": v(e, "name"), "tipo": v(e, "elementType"), "material": v(e, "material"),
                               "estado": v(e, "conditionStatus"), "inspeccion": v(e, "lastInspection")}
                              for e in reg.listar(t, "HeritageElement") if v(e, "refZone") == z["id"]],
                "sensores": [{"codigo": M.codigo(s["id"]), "nombre": v(s, "name"), "estado": v(s, "operStatus"),
                              "ahora": ahora.get(s["id"])} for s in reg.listar(t, "EnvironmentalSensor") if v(s, "refZone") == z["id"]],
                "alertas": [_alerta(a) for a in reg.listar(t, "ConservationAlert", limite=1000) if v(a, "refZone") == z["id"]],
                "archivo": contenido_deposito(t, v(z, "refDeposito")) if v(z, "refDeposito") else None,
                "serie": estado.get("serie", []), "evaluacion": estado.get("evaluacion"), "origenSeries": estado.get("origenSeries")}

    def _alerta(a, nombres=None):
        return {"id": a["id"], "codigo": M.codigo(a["id"]), "zona": v(a, "refZone"), "zonaCodigo": M.codigo(v(a, "refZone", "")),
                "zonaNombre": (nombres or {}).get(v(a, "refZone")), "nivel": v(a, "riskLevel"), "estado": v(a, "alertStatus"),
                "causa": v(a, "cause"), "detectada": v(a, "detectedAt"), "evaluacion": v(a, "refAssessment"),
                "propuestaCierre": v(a, "closureProposed", False), "reconocidaPor": v(a, "acknowledgedBy"),
                "cerradaPor": v(a, "closedBy"), "causaCierre": v(a, "closureCause"), "cerrada": v(a, "closedAt")}

    @r.get("/api/alertas")
    def alertas(req: Request, estado: str = "abiertas"):
        quien = nucleo.yo(req)
        exigir(quien, LEER, "ver el gemelo")
        reg, t = nucleo.registro, quien.tenant
        nombres = {z["id"]: v(z, "name") for z in reg.listar(t, "HeritageZone")}
        xs = [_alerta(a, nombres) for a in reg.listar(t, "ConservationAlert", limite=1000)]
        if estado == "abiertas":
            xs = [a for a in xs if a["estado"] in ("activa", "reconocida")]
        return sorted(xs, key=lambda a: a["detectada"] or "", reverse=True)

    @r.get("/api/alertas/{cod}/actas")
    def actas_alerta(cod: str, req: Request):
        quien = nucleo.yo(req)
        exigir(quien, LEER, "ver el gemelo")
        try:
            return nucleo.actas(M.urn("ConservationAlert", quien.tenant, codigo_ok(cod)))
        except OSError as e:
            raise HTTPException(503, f"el notario no responde: {e}")

    def firmar(cod: str, req: Request, accion: str, causa: str = ""):
        quien = nucleo.yo(req)
        exigir(quien, FIRMAR, f"{accion} alertas")
        cuerpo = {"tenant": quien.tenant, "alerta": M.urn("ConservationAlert", quien.tenant, codigo_ok(cod)),
                  "por": quien.usuario}
        if accion == "cerrar":
            cuerpo["causa"] = causa
        return servicio("POST", f"{conservacion}/gemelo/alertas/{accion}", cuerpo)

    @r.post("/api/alertas/{cod}/reconocer")
    def reconocer(cod: str, req: Request):
        return firmar(cod, req, "reconocer")

    @r.post("/api/alertas/{cod}/cerrar")
    def cerrar(cod: str, req: Request, p: Dict[str, Any] = Body(...)):
        return firmar(cod, req, "cerrar", str(p.get("causa") or ""))

    @r.post("/api/zonas/{cod}/evaluacion")
    def recalcular(cod: str, req: Request):
        quien = nucleo.yo(req)
        exigir(quien, FIRMAR | CONFIGURAR, "recalcular la evaluación")
        return servicio("POST", f"{conservacion}/gemelo/zonas/{codigo_ok(cod)}/evaluar", {"tenant": quien.tenant}, timeout=120)

    @r.get("/api/sensores")
    def lista_sensores(req: Request):
        quien = nucleo.yo(req)
        exigir(quien, LEER, "ver el gemelo")
        reg, t = nucleo.registro, quien.tenant
        zonas = {z["id"]: z for z in reg.listar(t, "HeritageZone")}
        try:
            ahora = {x["sensor"]: x for z in servicio("GET", f"{conservacion}/gemelo/resumen", params={"tenant": t})
                     for x in z.get("lecturas", [])}
        except HTTPException:
            ahora = {}
        return sorted(({"id": s["id"], "codigo": M.codigo(s["id"]), "nombre": v(s, "name"), "estado": v(s, "operStatus"),
                        "zona": M.codigo(v(s, "refZone", "")), "zonaNombre": v(zonas.get(v(s, "refZone")), "name"),
                        "posicion": v(s, "planPosition"), "serie": v(s, "serialNumber"), "ahora": ahora.get(s["id"])}
                       for s in reg.listar(t, "EnvironmentalSensor")), key=lambda x: x["codigo"])

    # ---------- configuración y demo ----------
    @r.post("/api/semilla")
    def semilla(req: Request):
        quien = nucleo.yo(req)
        exigir(quien, CONFIGURAR, "configurar el inmueble")
        s = servicio("POST", f"{sensores}/gemelo/semilla", {"tenant": quien.tenant})
        p = servicio("POST", f"{conservacion}/gemelo/preparar", {"tenant": quien.tenant}, timeout=300)
        return {**s, **p}

    @r.post("/api/simular")
    def simular(req: Request, p: Dict[str, Any] = Body(...)):
        quien = nucleo.yo(req)
        exigir(quien, CONFIGURAR, "lanzar simulaciones")
        cod, perfil = codigo_ok(str(p.get("zona", ""))), str(p.get("perfil", ""))
        try:
            servicio("POST", f"{sensores}/gemelo/perfil", {"tenant": quien.tenant, "zona": cod, "perfil": perfil})
        except HTTPException as e:
            if e.status_code != 404:     # zona sin sensores simulados: se simula solo la serie
                raise
        return servicio("POST", f"{conservacion}/gemelo/zonas/{cod}/simular",
                        {"tenant": quien.tenant, "perfil": perfil, "dias": p.get("dias", 7)}, timeout=120)

    @r.get("/api/perfiles")
    def perfiles(req: Request):
        quien = nucleo.yo(req)
        exigir(quien, LEER, "ver el gemelo")
        try:
            return servicio("GET", f"{sensores}/gemelo/perfiles", params={"tenant": quien.tenant})
        except HTTPException:
            return []

    @r.post("/api/zonas")
    def nueva_zona(req: Request, p: Dict[str, Any] = Body(...)):
        quien = nucleo.yo(req)
        exigir(quien, CONFIGURAR, "configurar el inmueble")
        t, reg = quien.tenant, nucleo.registro
        edificios = reg.listar(t, "HeritageBuilding")
        if not edificios:
            raise HTTPException(409, "primero hace falta el inmueble (crea el de ejemplo o súbelo al catastro)")
        tipo = str(p.get("tipo", "sala"))
        deposito = deposito_de(t, p.get("deposito")) if tipo == "depósito" else None
        try:
            clima = {"temperatura": float(p.get("temperatura") or 18), "humedad": float(p.get("humedad") or 55)}
            e = M.zona(t, codigo_ok(str(p.get("codigo", ""))), edificio_cod=M.codigo(edificios[0]["id"]),
                       nombre=str(p.get("nombre") or "").strip() or str(p.get("codigo")), tipo=tipo,
                       materiales=[x.strip() for x in str(p.get("materiales", "")).split(",") if x.strip()],
                       area=float(p.get("area", 0) or 0), clima=clima,
                       plano=plano_de(t, p), deposito=deposito)
        except (TypeError, ValueError) as ex:
            raise HTTPException(422, str(ex))
        if reg.crear(t, e) != 201:
            raise HTTPException(409, "ya existe una zona con ese código")
        return {"zona": e["id"], "codigo": M.codigo(e["id"]), "plano": M.v(e, "planPosition"), "deposito": deposito}

    def plano_de(t: str, p: Dict[str, Any], salvo: str = None) -> Dict[str, float]:
        """La posición pedida (x, y, w, h) o, si no viene, el primer hueco libre de la planta."""
        if p.get("w") not in (None, "") and p.get("h") not in (None, ""):
            pl = {k: float(p.get(k) or 0) for k in ("x", "y", "w", "h")}
            if pl["w"] <= 0 or pl["h"] <= 0 or pl["x"] < 0 or pl["y"] < 0:
                raise HTTPException(422, "planta: x e y desde 0; ancho y alto mayores que 0")
            return pl
        otras = [v(z, "planPosition") for z in nucleo.registro.listar(t, "HeritageZone") if z["id"] != salvo]
        return M.hueco_libre(otras)

    def deposito_de(t: str, valor: Any):
        """Acepta el código (D1) o el URN del Deposito del archivo; vacío = sin enlazar."""
        valor = str(valor or "").strip()
        if not valor:
            return None
        did = valor if valor.startswith("urn:") else urn_deposito(t, codigo_ok(valor))
        if not did.startswith(f"urn:ngsi-ld:Deposito:{t}:") or not nucleo.registro.leer(t, did):
            raise HTTPException(404, f"no hay ningún depósito del archivo {valor}")
        return did

    @r.post("/api/zonas/{cod}/plano")
    def mover_zona(cod: str, req: Request, p: Dict[str, Any] = Body(default={})):
        """Recoloca una zona en la planta: con x, y, w, h, o sin nada para llevarla al primer hueco libre."""
        quien = nucleo.yo(req)
        exigir(quien, CONFIGURAR, "configurar el inmueble")
        t, reg = quien.tenant, nucleo.registro
        zid = M.urn("HeritageZone", t, codigo_ok(cod))
        if not reg.leer(t, zid):
            raise HTTPException(404, f"no hay ninguna zona {cod}")
        try:
            pl = plano_de(t, p, salvo=zid)
        except (TypeError, ValueError) as ex:
            raise HTTPException(422, str(ex))
        attrs = {"planPosition": M.prop(pl)}
        if "deposito" in p:
            dep = deposito_de(t, p.get("deposito"))
            if dep:
                attrs["refDeposito"] = M.rel(dep)
        reg.anadir_atributos(t, zid, attrs)
        return {"zona": zid, "plano": pl}

    @r.post("/api/sensores")
    def nuevo_sensor(req: Request, p: Dict[str, Any] = Body(...)):
        quien = nucleo.yo(req)
        exigir(quien, CONFIGURAR, "configurar el inmueble")
        t, reg = quien.tenant, nucleo.registro
        zc = codigo_ok(str(p.get("zona", "")))
        z = reg.leer(t, M.urn("HeritageZone", t, zc))
        if not z:
            raise HTTPException(404, f"no hay ninguna zona {zc}")
        try:
            pos = M.centro(v(z, "planPosition")) if v(z, "planPosition") else {"x": 50, "y": 30}
            if p.get("x") not in (None, "") and p.get("y") not in (None, ""):
                pos = {"x": float(p["x"]), "y": float(p["y"])}
            ents = M.sensor(t, codigo_ok(str(p.get("codigo", ""))), zona_cod=zc, nombre=str(p.get("nombre") or p.get("codigo")),
                            x=pos["x"], y=pos["y"])
        except (TypeError, ValueError) as ex:
            raise HTTPException(422, str(ex))
        for e in ents:
            if reg.crear(t, e) != 201:
                raise HTTPException(409, f"ya existe {e['id']}")
        try:   # que el simulador lo lea ya (si no, lo encontrará en su próxima vuelta)
            servicio("POST", f"{sensores}/gemelo/tenants", {"tenant": t}, timeout=10)
        except HTTPException:
            pass
        return {"sensor": ents[0]["id"], "observacion": ents[1]["id"]}

    @r.post("/api/ingesta/observacion")
    def ingesta(req: Request, p: Dict[str, Any] = Body(...)):
        """Ingesta alternativa a los sensores simulados: un sistema de la institución (con una credencial de API de
        «Mi institución») envía la lectura de uno de sus sensores."""
        quien = nucleo.yo(req)
        if not (set(quien.roles) & CONFIGURAR or quien.usuario.startswith("service-account-")):
            raise HTTPException(403, "hace falta una credencial de API de tu institución")
        t = quien.tenant
        cod = codigo_ok(str(p.get("sensor", "")))
        try:
            temp, hr, cuando = float(p["temperatura"]), float(p["humedad"]), str(p["observadoEn"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "sensor, temperatura, humedad y observadoEn (ISO 8601)")
        if not (-30 <= temp <= 60 and 0 <= hr <= 100):
            raise HTTPException(422, "lectura fuera de rango")
        estado = nucleo.registro.anadir_atributos(t, M.urn("IndoorEnvironmentObserved", t, cod), M.lectura_attrs(temp, hr, cuando))
        if estado == 404:
            raise HTTPException(404, f"no hay ningún sensor {cod}")
        return {"sensor": cod, "estado": estado}

    # ---------- API del gemelo del archivo (depósitos con umbrales fijos) ----------
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
