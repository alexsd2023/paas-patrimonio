"""Conservación · vigila los depósitos (gemelo digital).

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
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Query

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


def crear_app(vigilante: Vigilante, bootstrap: Optional[str] = None) -> FastAPI:
    estado: dict = {}

    @asynccontextmanager
    async def ciclo(app):
        if bootstrap:
            lanzar_consumidor(bootstrap=bootstrap, grupo="conservacion", topics=["sensores"],
                              tipos=["deposito.medicion"], manejar=vigilante.manejar, estado=estado)
        yield

    app = FastAPI(title="Conservación", version="0.1.0", lifespan=ciclo)

    @app.get("/salud")
    def salud():
        return {"ok": True, "consumidor": estado}

    @app.get("/depositos")
    def depositos(tenant: str = Query(..., pattern=r"^[a-z0-9-]+$")):
        return vigilante.depositos(tenant)

    return app


def _crear() -> FastAPI:
    from sdk.eventos import Publicador
    from sdk.registro import Registro
    kafka = os.environ.get("KAFKA_BOOTSTRAP")
    pub = Publicador(kafka, client_id="conservacion") if kafka else None
    return crear_app(Vigilante(Registro(os.environ.get("SCORPIO_URL", "http://scorpio:9090")), pub), kafka)


app = _crear()
configurar("conservacion", app)
