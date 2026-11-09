"""Sensores simulados de los depósitos (gemelo digital).

Hace el papel de un IoT Agent de FIWARE: cada INTERVALO segundos escribe en el catastro
la temperatura y la humedad de cada depósito, con su hora de observación (observedAt).
Al arrancar, inscribe el inventario si falta: depósitos y cajas de cada institución.

Para la demo tiene un mando de escenarios por depósito:
    normal  · lecturas estables alrededor de 17 °C y 45 %
    fuga    · la humedad sube (una fuga de agua)
    calor   · la temperatura sube (avería de la climatización)

    GET  /salud
    GET  /escenarios
    POST /escenario {"tenant", "deposito", "escenario"}

Solo se usa dentro de la red de la plataforma (el panel lo llama); no se publica fuera.
"""
import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException

from sdk.registro import Registro, entidad_caja, entidad_deposito, urn_deposito

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sensores")

UMBRALES = {"temperaturaMin": 14.0, "temperaturaMax": 20.0, "humedadMin": 35.0, "humedadMax": 55.0}
INVENTARIO_POR_DEFECTO = {
    "archivo-villanueva": {
        "D1": {"nombre": "Depósito 1 · sótano", "cajas": ["C-001", "C-002", "C-003"]},
        "D2": {"nombre": "Depósito 2 · planta primera", "cajas": ["C-004", "C-005", "C-006"]},
    },
    "otro-archivo": {"D1": {"nombre": "Depósito único", "cajas": ["C-001"]}},
}
ESCENARIOS = ("normal", "fuga", "calor")


class Simulador:
    def __init__(self, registro, inventario: Dict[str, Any], semilla: int = 7):
        self.reg, self.inv = registro, inventario
        self.rnd = random.Random(semilla)
        self.estado = {(t, d): {"escenario": "normal", "t": 17.0, "h": 45.0}
                       for t, deps in inventario.items() for d in deps}

    def inscribir_inventario(self) -> None:
        for t, deps in self.inv.items():
            for d, info in deps.items():
                self.reg.crear(t, entidad_deposito(t, d, nombre=info["nombre"], umbrales=UMBRALES))  # 409 si ya está
                for c in info["cajas"]:
                    self.reg.crear(t, entidad_caja(t, c, d))
        log.info("inventario inscrito: %s", {t: list(d) for t, d in self.inv.items()})

    def paso(self, t: str, d: str) -> Dict[str, float]:
        """Siguiente lectura según el escenario (deriva suave hacia el objetivo, con ruido)."""
        e = self.estado[(t, d)]
        objetivo_t, objetivo_h, vel = {"normal": (17.0, 45.0, 0.35), "fuga": (17.5, 72.0, 0.45),
                                       "calor": (26.0, 42.0, 0.4)}[e["escenario"]]
        e["t"] += (objetivo_t - e["t"]) * vel + self.rnd.uniform(-0.15, 0.15)
        e["h"] += (objetivo_h - e["h"]) * vel + self.rnd.uniform(-0.6, 0.6)
        return {"temperatura": round(e["t"], 1), "humedad": round(e["h"], 1)}

    def leer_y_escribir(self) -> None:
        ahora = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        for (t, d) in self.estado:
            v = self.paso(t, d)
            attrs = {"temperatura": {"type": "Property", "value": v["temperatura"], "unitCode": "CEL", "observedAt": ahora},
                     "humedad": {"type": "Property", "value": v["humedad"], "unitCode": "P1", "observedAt": ahora}}
            self.reg.anadir_atributos(t, urn_deposito(t, d), attrs)


def crear_app(sim: Simulador, intervalo: float = 0) -> FastAPI:
    app = FastAPI(title="Sensores simulados", version="0.1.0")

    if intervalo:
        def bucle():
            while not sim.reg.disponible():
                time.sleep(3)
            sim.inscribir_inventario()
            while True:
                try:
                    sim.leer_y_escribir()
                except Exception as e:  # catastro caído: seguir intentándolo
                    log.warning("no se pudieron escribir las lecturas: %s", e)
                time.sleep(intervalo)
        threading.Thread(target=bucle, daemon=True, name="sensores").start()

    @app.get("/salud")
    def salud():
        return {"ok": True}

    @app.get("/escenarios")
    def escenarios():
        return [{"tenant": t, "deposito": d, "escenario": e["escenario"]} for (t, d), e in sim.estado.items()]

    @app.post("/escenario")
    def escenario(p: Dict[str, Any] = Body(...)):
        clave = (p.get("tenant"), p.get("deposito"))
        if clave not in sim.estado:
            raise HTTPException(404, "depósito desconocido")
        if p.get("escenario") not in ESCENARIOS:
            raise HTTPException(400, f"escenario: {', '.join(ESCENARIOS)}")
        sim.estado[clave]["escenario"] = p["escenario"]
        log.info("escenario %s en %s/%s", p["escenario"], *clave)
        return {"tenant": clave[0], "deposito": clave[1], "escenario": p["escenario"]}

    return app


app = crear_app(Simulador(Registro(os.environ.get("SCORPIO_URL", "http://scorpio:9090")),
                          json.loads(os.environ["INVENTARIO"]) if os.environ.get("INVENTARIO") else INVENTARIO_POR_DEFECTO),
                intervalo=float(os.environ.get("INTERVALO", "5")) if os.environ.get("SCORPIO_URL") else 0)
