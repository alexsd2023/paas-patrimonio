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

── Gemelo patrimonial ──
Cada SIM_INTERVALO_S segundos (30) escribe la lectura de cada EnvironmentalSensor de las instituciones con gemelo
en su IndoorEnvironmentObserved (el catastro guarda el historial). Lee los sensores del propio catastro: lo que se
da de alta en Configuración se simula sin tocar código. Perfiles por zona (productos/gemelo/clima.py):
estable · desviacion · fluctuacion, que se cambian en caliente.

    POST /gemelo/semilla  {"tenant"}                  inscribe el inmueble de ejemplo (si no lo tiene)
    POST /gemelo/tenants  {"tenant"}                  simula los sensores que ya tenga en el catastro
    GET  /gemelo/perfiles?tenant=
    POST /gemelo/perfil   {"tenant", "zona", "perfil"}

Solo se usa dentro de la red de la plataforma (el panel lo llama); no se publica fuera.
"""
import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


class SimuladorPatrimonial:
    """Los sensores de las zonas del gemelo patrimonial de cada institución."""

    def __init__(self, registro, ruta: Optional[str] = None, semillas=()):
        from productos.gemelo import clima as C, modelo as M
        self.C, self.M = C, M
        self.reg, self.ruta = registro, Path(ruta) if ruta else None
        self.tenants = set(semillas)
        if self.ruta and self.ruta.exists():
            self.tenants |= set(json.loads(self.ruta.read_text()))
        self.semillas = tuple(semillas)
        self.perfil_inicial = os.environ.get("SIM_PERFIL", "estable")
        self.sensores: Dict[tuple, dict] = {}          # (tenant, sensor) → {zona, clima, ruido, obs}
        self.perfiles: Dict[tuple, tuple] = {}         # (tenant, zona) → (perfil, desde)
        self._lock = threading.Lock()

    def _guardar(self):
        if self.ruta:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps(sorted(self.tenants)))

    def anadir(self, tenant: str) -> None:
        with self._lock:
            self.tenants.add(tenant)
            self._guardar()
        self.refrescar(tenant)

    def sembrar(self, tenant: str) -> int:
        """Inscribe el inmueble de ejemplo (si la institución no lo tiene) y empieza a simular sus sensores."""
        M = self.M
        creadas = 0
        if not self.reg.leer(tenant, M.urn("HeritageBuilding", tenant, "B01")):
            deps = {d: urn_deposito(tenant, d) for d in ("D1", "D2") if self.reg.leer(tenant, urn_deposito(tenant, d))}
            for e in M.inmueble_ejemplo(tenant, deps):
                creadas += self.reg.crear(tenant, e) == 201
            log.info("inmueble de ejemplo inscrito en %s: %d entidades", tenant, creadas)
        self.anadir(tenant)
        return creadas

    def refrescar(self, tenant: Optional[str] = None) -> None:
        """Vuelve a leer del catastro las zonas y los sensores (los nuevos de Configuración entran solos)."""
        M = self.M
        for t in [tenant] if tenant else sorted(self.tenants):
            zonas = {z["id"]: z for z in self.reg.listar(t, "HeritageZone")}
            vistos = set()
            for s in self.reg.listar(t, "EnvironmentalSensor"):
                z = zonas.get(M.v(s, "refZone"))
                if not z:
                    continue
                clave = (t, s["id"])
                vistos.add(clave)
                clima = {**self.C.CLIMA_POR_DEFECTO, **(M.v(z, "climateReference") or {})}
                with self._lock:
                    previo = self.sensores.get(clave)
                    self.sensores[clave] = {"zona": z["id"], "clima": clima,
                                            "ruido": previo["ruido"] if previo else self.C.Ruido(s["id"]),
                                            "obs": M.urn("IndoorEnvironmentObserved", t, M.codigo(s["id"])),
                                            "estado": previo["estado"] if previo else None}
            with self._lock:
                for clave in [k for k in self.sensores if k[0] == t and k not in vistos]:
                    del self.sensores[clave]

    def perfil(self, tenant: str, zona_cod: str, perfil: str) -> dict:
        if perfil not in self.C.PERFILES:
            raise ValueError(f"perfil: {', '.join(self.C.PERFILES)}")
        zona = self.M.urn("HeritageZone", tenant, zona_cod)
        with self._lock:
            if not any(v["zona"] == zona for k, v in self.sensores.items() if k[0] == tenant):
                raise KeyError(zona)
            self.perfiles[(tenant, zona)] = (perfil, datetime.now(timezone.utc))
        log.info("perfil %s en %s", perfil, zona)
        return {"tenant": tenant, "zona": zona_cod, "perfil": perfil}

    def perfiles_de(self, tenant: str) -> List[dict]:
        with self._lock:
            zonas = sorted({v["zona"] for k, v in self.sensores.items() if k[0] == tenant})
            return [{"zona": self.M.codigo(z), "perfil": self.perfiles.get((tenant, z), (self.perfil_inicial,))[0]}
                    for z in zonas]

    def leer_y_escribir(self) -> int:
        ahora = datetime.now(timezone.utc)
        cuando = ahora.isoformat(timespec="seconds").replace("+00:00", "Z")
        with self._lock:
            trabajo = [(k, dict(v)) for k, v in self.sensores.items()]
        n = 0
        for (t, sid), s in trabajo:
            perfil, desde = self.perfiles.get((t, s["zona"]), (self.perfil_inicial, ahora))
            temp, hr = self.C.lectura(s["clima"], ahora, perfil, s["ruido"], (ahora - desde).total_seconds() / 3600)
            if self.reg.anadir_atributos(t, s["obs"], self.M.lectura_attrs(temp, hr, cuando)) in (204, 207):
                n += 1
                if s["estado"] != "OK":
                    self.reg.anadir_atributos(t, sid, {"operStatus": self.M.prop("OK")})
                    with self._lock:
                        if (t, sid) in self.sensores:
                            self.sensores[(t, sid)]["estado"] = "OK"
        return n


def crear_app(sim: Simulador, intervalo: float = 0, patrimonial: Optional[SimuladorPatrimonial] = None,
              intervalo_patrimonial: float = 30) -> FastAPI:
    app = FastAPI(title="Sensores simulados", version="0.2.0")

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

        if patrimonial is not None:
            def bucle_patrimonial():
                while not sim.reg.disponible():
                    time.sleep(3)
                time.sleep(2)   # que el inventario del archivo (depósitos) esté antes, para enlazar las zonas
                for t in patrimonial.semillas:
                    try:
                        patrimonial.sembrar(t)
                    except Exception as e:  # noqa: BLE001
                        log.warning("no se pudo inscribir el inmueble de %s: %s", t, e)
                vuelta = 0
                while True:
                    try:
                        if vuelta % 10 == 0:
                            patrimonial.refrescar()
                        patrimonial.leer_y_escribir()
                    except Exception as e:  # noqa: BLE001
                        log.warning("no se pudieron escribir las lecturas de las zonas: %s", e)
                    vuelta += 1
                    time.sleep(intervalo_patrimonial)
            threading.Thread(target=bucle_patrimonial, daemon=True, name="sensores-zonas").start()

    if patrimonial is not None:
        def tenant_de(p):
            t = str((p or {}).get("tenant") or "")
            if not t.replace("-", "").isalnum() or t != t.lower():
                raise HTTPException(422, "falta tenant")
            return t

        @app.post("/gemelo/semilla")
        def semilla(p: Dict[str, Any] = Body(...)):
            t = tenant_de(p)
            return {"tenant": t, "creadas": patrimonial.sembrar(t),
                    "sensores": sum(1 for k in patrimonial.sensores if k[0] == t)}

        @app.post("/gemelo/tenants")
        def tenants(p: Dict[str, Any] = Body(...)):
            t = tenant_de(p)
            patrimonial.anadir(t)
            return {"tenant": t, "sensores": sum(1 for k in patrimonial.sensores if k[0] == t)}

        @app.get("/gemelo/perfiles")
        def perfiles(tenant: str):
            return patrimonial.perfiles_de(tenant)

        @app.post("/gemelo/perfil")
        def cambiar_perfil(p: Dict[str, Any] = Body(...)):
            t = tenant_de(p)
            try:
                return patrimonial.perfil(t, str(p.get("zona", "")), str(p.get("perfil", "")))
            except KeyError:
                raise HTTPException(404, "zona sin sensores en el simulador")
            except ValueError as e:
                raise HTTPException(400, str(e))

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


_reg = Registro(os.environ.get("SCORPIO_URL", "http://scorpio:9090"))
app = crear_app(Simulador(_reg, json.loads(os.environ["INVENTARIO"]) if os.environ.get("INVENTARIO") else INVENTARIO_POR_DEFECTO),
                intervalo=float(os.environ.get("INTERVALO", "5")) if os.environ.get("SCORPIO_URL") else 0,
                patrimonial=SimuladorPatrimonial(
                    _reg, os.environ.get("GEMELO_TENANTS_RUTA"),
                    [t.strip() for t in os.environ.get("GEMELO_SEMILLA_TENANT", "").split(",") if t.strip()]),
                intervalo_patrimonial=float(os.environ.get("SIM_INTERVALO_S", "30")))
