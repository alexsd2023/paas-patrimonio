"""Conservación · vigila los depósitos (gemelo del archivo) y las zonas (gemelo patrimonial).

── Gemelo patrimonial (EN 15757) ── ver services/conservacion/patrimonial.py
Guarda las series de cada zona (zona.medicion), las evalúa cada hora con la capacidad evaluacion-en15757 por el
catálogo, escribe ClimateAssessment y ConservationAlert en el catastro y lleva las firmas a Temporal.

    POST /gemelo/preparar                     {tenant}  la institución entra en el gemelo (histórico sintético)
    GET  /gemelo/resumen?tenant=              cada zona: evaluación, lecturas de ahora y alerta abierta
    GET  /gemelo/zonas/{cod}?tenant=&dias=7   serie horaria, evaluación (con su banda) y lecturas de ahora
    POST /gemelo/zonas/{cod}/evaluar          {tenant}
    POST /gemelo/zonas/{cod}/simular          {tenant, perfil, dias}   para la demo
    POST /gemelo/alertas/reconocer            {tenant, alerta, por}
    POST /gemelo/alertas/cerrar               {tenant, alerta, por, causa}
    POST /gemelo/evaluar-todo                 lo mismo que hace la programación de cada hora

── Gemelo del archivo (umbrales fijos) ──

Lee las cartas deposito.medicion y compara cada lectura con los umbrales del depósito.
Cuando una variable se sale del rango:
  1. marca el depósito en el catastro (estadoAmbiental = alerta),
  2. busca en el catastro las cajas del depósito y los legajos de esas cajas,
  3. envía conservacion.alerta con esos legajos (el notario lo anota en el libro de cada uno).
Cuando vuelve al rango (con un margen, para no oscilar), envía conservacion.normalizada.

    GET /depositos?tenant=<tenant>   estado y últimas lecturas (lo usa el panel; no se publica fuera)
    GET /salud
"""
import logging
import os
import re
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, FastAPI, HTTPException, Query

from sdk.servicio import lanzar_consumidor
from sdk.trazas import configurar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("conservacion")

ESPACIO_IDS = uuid.UUID("5b0f4c1e-7a2d-4e8b-9c3f-0d1a2b3c4d5e")
MARGEN = {"temperatura": 0.5, "humedad": 2.0}   # histéresis para salir de la alerta
SERIE = 120                                      # lecturas que se guardan por depósito


def evaluar(variable: str, valor: float, umbrales: Dict[str, float], en_alerta: bool) -> Tuple[bool, Optional[str], Optional[float]]:
    """→ (en_alerta, sentido, límite). Pura: sin red."""
    lo, hi = umbrales.get(f"{variable}Min"), umbrales.get(f"{variable}Max")
    if not en_alerta:
        if hi is not None and valor > hi:
            return True, "alta", hi
        if lo is not None and valor < lo:
            return True, "baja", lo
        return False, None, None
    m = MARGEN[variable]
    dentro = (hi is None or valor <= hi - m) and (lo is None or valor >= lo + m)
    return (not dentro), None, None


def _v(e, k, defecto=None):
    a = (e or {}).get(k)
    return a.get("value", a.get("object", defecto)) if isinstance(a, dict) else (a if a is not None else defecto)


class Vigilante:
    def __init__(self, registro, publicador):
        self.reg, self.pub = registro, publicador
        self._lock = threading.Lock()
        self.series: Dict[Tuple[str, str], deque] = {}
        self.alertas: Dict[Tuple[str, str, str], bool] = {}
        self.nombres: Dict[Tuple[str, str], str] = {}

    def legajos_en(self, tenant: str, deposito: str) -> List[str]:
        cajas = {c["id"] for c in self.reg.listar(tenant, "Caja") if _v(c, "enDeposito") == deposito}
        return sorted(a["id"] for a in self.reg.listar(tenant, "ActivoPatrimonial") if _v(a, "enCaja") in cajas)

    def manejar(self, ev: dict) -> None:
        if ev["type"] != "deposito.medicion":
            return
        t, dep, d = ev["tenant"], ev["subject"], ev["data"]
        with self._lock:
            serie = self.series.setdefault((t, dep), deque(maxlen=SERIE))
            if serie and serie[-1]["observadoEn"] >= d["observadoEn"]:
                return  # lectura repetida o antigua
            serie.append({"observadoEn": d["observadoEn"], "temperatura": d["temperatura"], "humedad": d["humedad"]})
            self.nombres[(t, dep)] = d.get("nombre", dep.split(":")[-1])
        for var in ("temperatura", "humedad"):
            antes = self.alertas.get((t, dep, var), False)
            ahora, sentido, limite = evaluar(var, d[var], d["umbrales"], antes)
            if ahora == antes:
                continue
            self.alertas[(t, dep, var)] = ahora
            legajos = self.legajos_en(t, dep)
            algun = any(self.alertas.get((t, dep, x)) for x in ("temperatura", "humedad"))
            self.reg.anadir_atributos(t, dep, {"estadoAmbiental": {"type": "Property", "value": "alerta" if algun else "ok"}})
            from sdk.eventos import nuevo_evento
            tipo = "conservacion.alerta" if ahora else "conservacion.normalizada"
            data = {"variable": var, "valor": d[var], "legajos": legajos, "observadoEn": d["observadoEn"],
                    "nombre": self.nombres[(t, dep)]}
            if ahora:
                data.update(limite=limite, sentido=sentido)
            self.pub.publicar(nuevo_evento(tipo, id=str(uuid.uuid5(ESPACIO_IDS, f"{tipo}|{dep}|{var}|{d['observadoEn']}")),
                                           tenant=t, subject=dep, source=f"/tenants/{t}/servicios/conservacion", data=data))
            log.info("%s %s %s=%s (%d legajos)", tipo, dep, var, d[var], len(legajos))

    def depositos(self, tenant: str) -> List[Dict[str, Any]]:
        with self._lock:
            out = []
            for (t, dep), serie in self.series.items():
                if t != tenant:
                    continue
                out.append({"deposito": dep, "codigo": dep.split(":")[-1], "nombre": self.nombres.get((t, dep)),
                            "alertas": [v for v in ("temperatura", "humedad") if self.alertas.get((t, dep, v))],
                            "ultima": serie[-1] if serie else None, "serie": list(serie)[-60:]})
            return sorted(out, key=lambda x: x["codigo"])


class CapacidadPorCatalogo:
    """La evaluación EN 15757 por el catálogo (uso interno): cuenta en el consumo de cada institución."""

    def __init__(self, url: str, clave: Optional[str], http=None):
        import httpx
        self.url, self.clave = url.rstrip("/"), clave
        self.http = http or httpx.Client(timeout=120)

    def __call__(self, tenant: str, serie: dict, parametros: dict) -> dict:
        if not self.clave:
            raise RuntimeError("falta CATALOGO_INTERNO_CLAVE: conservación no puede usar la capacidad")
        r = self.http.post(f"{self.url}/interno/servicios/evaluacion-en15757/ejecutar",
                           json={"tenant": tenant, "entrada": serie, "parametros": parametros},
                           headers={"X-Clave-Interna": self.clave, "X-Producto": "gemelo"})
        if r.status_code != 200:
            raise RuntimeError(f"el catálogo respondió {r.status_code}: {r.text[:300]}")
        return r.json()["salida"]


TENANT = r"^[a-z0-9-]+$"


def crear_app(vigilante: Vigilante, bootstrap: Optional[str] = None, gemelo=None, firmas=None,
              semillas: tuple = ()) -> FastAPI:
    estado: dict = {}
    estado_g: dict = {}

    @asynccontextmanager
    async def ciclo(app):
        if bootstrap:
            lanzar_consumidor(bootstrap=bootstrap, grupo="conservacion", topics=["sensores"],
                              tipos=["deposito.medicion"], manejar=vigilante.manejar, estado=estado)
            if gemelo is not None:
                lanzar_consumidor(bootstrap=bootstrap, grupo="conservacion-zonas", topics=["sensores"],
                                  tipos=["zona.medicion"], manejar=gemelo.manejar, estado=estado_g)
        if gemelo is not None and semillas:
            threading.Thread(target=_preparar_semillas, args=(gemelo, semillas), daemon=True).start()
        yield

    app = FastAPI(title="Conservación", version="0.1.0", lifespan=ciclo)

    @app.get("/salud")
    def salud():
        out = {"ok": True, "consumidor": estado}
        if gemelo is not None:
            out["gemelo"] = {"consumidor": estado_g, "series": gemelo.series.origen,
                             "temporal": bool(getattr(firmas, "listo", False)), "instituciones": gemelo.series.tenants()}
        return out

    if gemelo is not None:
        _rutas_gemelo(app, gemelo, firmas)

    @app.get("/depositos")
    def depositos(tenant: str = Query(..., pattern=r"^[a-z0-9-]+$")):
        return vigilante.depositos(tenant)

    return app


def _preparar_semillas(gemelo, tenants) -> None:
    """Al arrancar: las instituciones de GEMELO_SEMILLA_TENANT entran en el gemelo cuando su inmueble esté en el
    catastro (lo inscribe el servicio de sensores), y se evalúan por primera vez."""
    import time
    for _ in range(120):
        pendientes = []
        for t in tenants:
            try:
                if not gemelo.zonas(t):
                    pendientes.append(t)
                    continue
                if gemelo.preparar(t) or not any(gemelo.series.evaluacion(t, z["id"]) for z in gemelo.zonas(t)):
                    for z in gemelo.zonas(t):
                        gemelo.evaluar_zona(t, z)
            except Exception as e:  # noqa: BLE001  catastro o catálogo aún arrancando
                log.info("gemelo de %s aún no listo: %s", t, e)
                pendientes.append(t)
        if not pendientes:
            return
        tenants = pendientes
        time.sleep(10)


def _rutas_gemelo(app: FastAPI, gemelo, firmas) -> None:
    from productos.gemelo import modelo as M
    from services.conservacion.patrimonial import Conflicto

    def zona_o_404(tenant, cod):
        try:
            return gemelo.zona(tenant, cod)
        except KeyError as e:
            raise HTTPException(404, str(e))

    def tenant_de(p):
        t = str((p or {}).get("tenant") or "")
        if not re.match(TENANT, t):
            raise HTTPException(422, "falta tenant")
        return t

    @app.post("/gemelo/preparar")
    def preparar(p: Dict[str, Any] = Body(...)):
        t = tenant_de(p)
        hechas = gemelo.preparar(t)
        evaluadas = []
        for z in gemelo.zonas(t):
            if z["id"] in hechas or not gemelo.series.evaluacion(t, z["id"]):
                try:
                    gemelo.evaluar_zona(t, z)
                    evaluadas.append(z["id"])
                except RuntimeError as e:
                    raise HTTPException(502, str(e))
        return {"historico": hechas, "evaluadas": evaluadas}

    @app.get("/gemelo/resumen")
    def resumen(tenant: str = Query(..., pattern=TENANT)):
        alertas = gemelo.alertas(tenant)
        out = []
        for z in gemelo.zonas(tenant):
            ev = gemelo.series.evaluacion(tenant, z["id"]) or {}
            ahora = gemelo.ahora(tenant, z["id"])
            abierta = next((a for a in alertas if M.v(a, "refZone") == z["id"] and M.v(a, "alertStatus") in ("activa", "reconocida")), None)
            out.append({"zona": z["id"], "codigo": M.codigo(z["id"]), "nombre": M.v(z, "name"),
                        "nivel": ev.get("nivel"), "causa": ev.get("causa"), "desviacion30d": ev.get("desviacion30d"),
                        "objetivoHumedad": (ev.get("humedad") or {}).get("objetivo"),
                        "objetivoTemperatura": (ev.get("temperatura") or {}).get("objetivo"),
                        "metodo": ev.get("metodo"), "origenDatos": ev.get("origenDatos"), "calculadaEn": ev.get("calculadaEn"),
                        "temperatura": round(sum(x["temperatura"] for x in ahora) / len(ahora), 1) if ahora else None,
                        "humedad": round(sum(x["humedad"] for x in ahora) / len(ahora), 1) if ahora else None,
                        "lecturas": ahora, "alerta": abierta and {"id": abierta["id"], "codigo": M.codigo(abierta["id"]),
                                                                  "nivel": M.v(abierta, "riskLevel"), "estado": M.v(abierta, "alertStatus")}})
        return out

    @app.get("/gemelo/zonas/{cod}")
    def zona(cod: str, tenant: str = Query(..., pattern=TENANT), dias: int = Query(7, ge=1, le=60)):
        zona_o_404(tenant, cod)
        return gemelo.estado_zona(tenant, cod, dias)

    @app.post("/gemelo/zonas/{cod}/evaluar")
    def evaluar(cod: str, p: Dict[str, Any] = Body(...)):
        t = tenant_de(p)
        z = zona_o_404(t, cod)
        try:
            if not gemelo.series.tiene_sintetico(t, z["id"]):
                gemelo.preparar(t)
            return gemelo.evaluar_zona(t, z)
        except RuntimeError as e:
            raise HTTPException(502, str(e))

    @app.post("/gemelo/zonas/{cod}/simular")
    def simular(cod: str, p: Dict[str, Any] = Body(...)):
        t = tenant_de(p)
        zona_o_404(t, cod)
        try:
            return gemelo.simular(t, cod, str(p.get("perfil", "")), float(p.get("dias", 7)))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except RuntimeError as e:
            raise HTTPException(502, str(e))

    def firma(p, accion):
        t = tenant_de(p)
        aid, por = str(p.get("alerta") or ""), str(p.get("por") or "")
        if not aid.startswith(f"urn:ngsi-ld:ConservationAlert:{t}:") or not por:
            raise HTTPException(422, "alerta (de tu institución) y por")
        try:
            if accion == "cerrar":
                causa = str(p.get("causa") or "").strip()
                if len(causa) < 3:
                    raise HTTPException(422, "para cerrar una alerta hay que escribir la causa")
                firmas.cerrar(t, aid, por, causa)
            else:
                firmas.reconocer(t, aid, por)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Conflicto as e:
            raise HTTPException(409, str(e))
        return {"alerta": aid, "accion": accion, "por": por, "proceso": f"alerta:{aid}" if getattr(firmas, "listo", False) else None}

    @app.post("/gemelo/alertas/reconocer")
    def reconocer(p: Dict[str, Any] = Body(...)):
        return firma(p, "reconocer")

    @app.post("/gemelo/alertas/cerrar")
    def cerrar(p: Dict[str, Any] = Body(...)):
        return firma(p, "cerrar")

    @app.post("/gemelo/evaluar-todo")
    def evaluar_todo():
        return gemelo.evaluar_todo()


def _crear() -> FastAPI:
    import json
    from sdk.eventos import Publicador
    from sdk.registro import Registro
    from services.conservacion import series as S
    from services.conservacion.firmas import FirmasTemporal
    from services.conservacion.patrimonial import FirmasDirectas, GemeloPatrimonial
    kafka = os.environ.get("KAFKA_BOOTSTRAP")
    pub = Publicador(kafka, client_id="conservacion") if kafka else None
    registro = Registro(os.environ.get("SCORPIO_URL", "http://scorpio:9090"))
    vigilante = Vigilante(registro, pub)
    parametros = {"metodo": os.environ.get("EVALUACION_METODO", "en15757")}
    umbrales = json.loads(os.environ.get("ALERT_THRESHOLDS") or "{}")
    for k, destino in (("medio", "umbral_medio"), ("alto", "umbral_alto"), ("fluctuacion", "fluctuacion_hr_2h")):
        if k in umbrales:
            parametros[destino] = umbrales[k]
    gemelo = GemeloPatrimonial(
        registro=registro, publicador=pub, parametros=parametros, legajos_de=vigilante.legajos_en,
        series=S.crear(os.environ.get("SERIES_ORIGEN", "local"), registro, os.environ.get("SERIES_DB", ":memory:")),
        capacidad=CapacidadPorCatalogo(os.environ.get("CATALOGO_INTERNO", "http://catalogo:8080"),
                                       os.environ.get("CATALOGO_INTERNO_CLAVE")),
        recuperacion_dias=float(os.environ.get("RECUPERACION_DIAS", "7")))
    if os.environ.get("TEMPORAL"):
        firmas = FirmasTemporal(gemelo, os.environ["TEMPORAL"], os.environ.get("EVALUACION_CRON", "0 * * * *"))
        firmas.arrancar()
    else:
        firmas = FirmasDirectas(gemelo)
    gemelo.firmas = firmas
    semillas = tuple(t.strip() for t in os.environ.get("GEMELO_SEMILLA_TENANT", "").split(",") if t.strip())
    return crear_app(vigilante, kafka, gemelo=gemelo, firmas=firmas, semillas=semillas)


app = _crear()
configurar("conservacion", app)
