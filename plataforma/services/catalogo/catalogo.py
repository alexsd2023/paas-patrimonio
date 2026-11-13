"""El catálogo: qué servicios hay, quién puede usarlos, cuánto los usa y cómo se ejecutan.

Es núcleo del PaaS. No sabe qué hace cada servicio: solo lee su ``servicio.yaml`` y
lo ejecuta por la interfaz estándar (integrada o alojada: su contenedor) o por su adaptador (externa).
"""
import importlib
import inspect
import logging
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from sdk.servicios import (DocumentoInvalido, Manifiesto, ManifiestoInvalido, RAIZ, cargar,
                           validar_documento)

log = logging.getLogger("catalogo")
CARPETA = Path(os.environ.get("CAPACIDADES_DIR", RAIZ / "capacidades"))


class SinPermiso(PermissionError):
    pass


class CuotaAgotada(RuntimeError):
    pass


class FalloDelServicio(RuntimeError):
    pass


def descubrir(carpeta: Path = CARPETA) -> Dict[str, Manifiesto]:
    out: Dict[str, Manifiesto] = {}
    for yml in sorted(Path(carpeta).glob("*/servicio.yaml")):
        if yml.parent.name.startswith("_"):
            continue  # _plantilla
        try:
            m = cargar(yml)
            out[m.id] = m
        except (ManifiestoInvalido, OSError, ValueError) as e:
            log.error("Servicio no cargado (%s): %s", yml.parent.name, e)
    return out


class Contador:
    """Uso por institución, servicio y día. En memoria: basta para cuotas del walking skeleton."""

    def __init__(self):
        self._n: Dict[tuple, int] = {}
        self._lock = threading.Lock()

    def usar(self, tenant: str, m: Manifiesto) -> int:
        clave = (tenant, m.id, date.today().isoformat())
        with self._lock:
            n = self._n.get(clave, 0)
            limite = m.cuota.get("trabajos_dia")
            if limite is not None and n >= limite:
                raise CuotaAgotada(f"{tenant} ha usado {n} de {limite} trabajos de hoy en {m.id}")
            self._n[clave] = n + 1
            return n + 1

    def uso(self, tenant: str) -> Dict[str, int]:
        hoy = date.today().isoformat()
        return {sid: n for (t, sid, d), n in self._n.items() if t == tenant and d == hoy}


class Catalogo:
    def __init__(self, servicios: Dict[str, Manifiesto], http: Optional[httpx.Client] = None,
                 espera: float = 600, sondeo: float = 0.5, secretos=None):
        self.servicios = servicios
        self.secretos = secretos   # services.catalogo.secretos.Secretos (opcional)
        self.http = http or httpx.Client(timeout=30, follow_redirects=True)
        self.contador = Contador()
        self.espera, self.sondeo = espera, sondeo

    def visibles(self, roles: List[str], tenant: str) -> List[Manifiesto]:
        return [m for m in self.servicios.values() if m.permite(roles, tenant)]

    def get(self, sid: str) -> Manifiesto:
        if sid not in self.servicios:
            raise KeyError(sid)
        return self.servicios[sid]

    def comprobar(self, sid: str, roles: List[str], tenant: str) -> Manifiesto:
        m = self.get(sid)
        if not m.permite(roles, tenant):
            raise SinPermiso(f"tu institución o tu rol no tienen acceso a {sid}")
        return m

    def ejecutar(self, sid: str, entrada: dict, parametros: Optional[dict], *, tenant: str, roles: List[str],
                 al_avanzar: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """Ejecuta un trabajo y espera el resultado. Devuelve {salida, servicio, version, ms}."""
        m = self.comprobar(sid, roles, tenant)
        validar_documento(m.entrada, entrada)
        params = m.parametros_con_defecto(parametros)
        self.contador.usar(tenant, m)
        t0 = time.monotonic()
        if m.modo == "externa":
            adaptador = importlib.import_module(f"capacidades.{m.carpeta.name}.adaptador")
            try:
                kw = {}
                if "secretos" in inspect.signature(adaptador.ejecutar).parameters:
                    kw["secretos"] = self.secretos.valores(m, tenant) if self.secretos else {}
                salida = adaptador.ejecutar(m, entrada, params, self.http, **kw)
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as e:
                raise FalloDelServicio(f"{m.id}: {e}")
        else:
            salida = self._interno(m, entrada, params, al_avanzar)
        try:
            validar_documento(m.salida, salida)
        except DocumentoInvalido as e:
            raise FalloDelServicio(f"{m.id} devolvió un {m.salida} que no cumple su tipo: {e}")
        return {"salida": salida, "servicio": m.id, "version": m.version, "ms": round((time.monotonic() - t0) * 1000)}

    def _interno(self, m: Manifiesto, entrada: dict, params: dict, al_avanzar) -> dict:
        try:
            r = self.http.post(f"{m.url}/trabajos", json={"entrada": entrada, "parametros": params})
            if r.status_code >= 400:
                raise FalloDelServicio(f"{m.id} rechazó el trabajo ({r.status_code}): {r.text[:300]}")
            tid = r.json()["id"]
            fin = time.monotonic() + self.espera
            while time.monotonic() < fin:
                t = self.http.get(f"{m.url}/trabajos/{tid}").json()
                if al_avanzar:
                    al_avanzar(t.get("estado", "?"))
                if t.get("estado") == "terminado":
                    return t["salida"]
                if t.get("estado") == "error":
                    raise FalloDelServicio(f"{m.id}: {t.get('error')}")
                time.sleep(self.sondeo)
        except httpx.HTTPError as e:
            raise FalloDelServicio(f"{m.id} no responde: {e}")
        raise FalloDelServicio(f"{m.id} no terminó en {self.espera:.0f} s")


class Trabajos:
    """Trabajos sueltos lanzados desde el catálogo (consola o API). Se ejecutan en hilos."""

    def __init__(self, catalogo: Catalogo, maximo: int = 500):
        self.catalogo = catalogo
        self._t: Dict[str, Dict[str, Any]] = {}
        self._maximo = maximo

    def lanzar(self, sid: str, entrada: dict, parametros: Optional[dict], *, tenant: str, usuario: str,
               roles: List[str]) -> Dict[str, Any]:
        m = self.catalogo.comprobar(sid, roles, tenant)
        validar_documento(m.entrada, entrada)
        m.parametros_con_defecto(parametros)
        import uuid
        tid = uuid.uuid4().hex[:16]
        t = {"id": tid, "servicio": sid, "version": m.version, "tenant": tenant, "usuario": usuario,
             "estado": "en-cola", "creado": time.time()}
        self._t[tid] = t
        if len(self._t) > self._maximo:
            for viejo in sorted(self._t, key=lambda k: self._t[k]["creado"])[: len(self._t) - self._maximo]:
                self._t.pop(viejo, None)

        def correr():
            t["estado"] = "en-curso"
            try:
                r = self.catalogo.ejecutar(sid, entrada, parametros, tenant=tenant, roles=roles)
                t.update(estado="terminado", salida=r["salida"], ms=r["ms"])
            except Exception as e:  # noqa: BLE001
                t.update(estado="error", error=str(e))
        threading.Thread(target=correr, daemon=True).start()
        return {"id": tid, "estado": "en-cola"}

    def ver(self, tid: str, tenant: str) -> Optional[Dict[str, Any]]:
        t = self._t.get(tid)
        return t if t and t["tenant"] == tenant else None
