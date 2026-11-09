"""Conectores en el catálogo: su configuración por institución y sus ejecuciones.

Es núcleo: no sabe qué hace cada conector, solo lee su ``conector.yaml``, guarda la configuración
que cada institución rellena en la consola y ejecuta ``conector.py`` con un Contexto acotado a esa
institución. Cada ejecución queda guardada y, al terminar, sale la carta ``conector.ejecutado``.
"""
import importlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from sdk.conectores import Conector, ConectorInvalido, ConfiguracionInvalida, Contexto, cargar
from sdk.servicios import RAIZ

log = logging.getLogger("catalogo.conectores")
CARPETA = Path(os.environ.get("CONECTORES_DIR", RAIZ / "conectores"))


def descubrir(carpeta: Path = CARPETA) -> Dict[str, Conector]:
    out: Dict[str, Conector] = {}
    for yml in sorted(Path(carpeta).glob("*/conector.yaml")):
        if yml.parent.name.startswith("_"):
            continue
        try:
            c = cargar(yml)
            out[c.id] = c
        except (ConectorInvalido, OSError, ValueError) as e:
            log.error("Conector no cargado (%s): %s", yml.parent.name, e)
    return out


class Conectores:
    def __init__(self, conectores: Dict[str, Conector], registro, ruta_db: Optional[str] = None,
                 http: Optional[httpx.Client] = None, publicador=None):
        self.conectores, self.registro, self.publicador = conectores, registro, publicador
        self.http = http or httpx.Client(timeout=60, follow_redirects=True,
                                         headers={"User-Agent": "PaaS-Patrimonio/0.1 (conector)"})
        self.ruta = ruta_db or os.path.join(tempfile.gettempdir(), "catalogo-conectores.db")
        self._lock = threading.Lock()
        self._parar: Dict[str, bool] = {}
        with self._con() as c:
            c.execute("create table if not exists configuracion (tenant text, conector text, valores text,"
                      " por text, cuando real, primary key (tenant, conector))")
            c.execute("create table if not exists ejecuciones (id text primary key, conector text, tenant text,"
                      " usuario text, inicio real, fin real, estado text, avance text, resumen text, error text)")
            # una ejecución que estaba en marcha cuando se reinició el servicio ya no lo está
            c.execute("update ejecuciones set estado='interrumpida', fin=? where estado='en-curso'", (time.time(),))

    def _con(self):
        return sqlite3.connect(self.ruta)

    # ---------- acceso ----------
    def visibles(self, roles: List[str], tenant: str) -> List[Conector]:
        return [c for c in self.conectores.values() if c.permite(roles, tenant)]

    def comprobar(self, cid: str, roles: List[str], tenant: str) -> Conector:
        if cid not in self.conectores:
            raise KeyError(cid)
        c = self.conectores[cid]
        if not c.permite(roles, tenant):
            raise PermissionError(f"tu rol o tu institución no tienen acceso al conector {cid}")
        return c

    # ---------- configuración por institución ----------
    def configuracion(self, cid: str, tenant: str) -> Optional[Dict[str, Any]]:
        with self._con() as c:
            f = c.execute("select valores, por, cuando from configuracion where tenant=? and conector=?",
                          (tenant, cid)).fetchone()
        return {"valores": json.loads(f[0]), "por": f[1], "cuando": f[2]} if f else None

    def configurar(self, cid: str, tenant: str, usuario: str, valores: Dict[str, Any]) -> Dict[str, Any]:
        limpios = self.conectores[cid].validar_configuracion(valores)
        with self._lock, self._con() as c:
            c.execute("insert or replace into configuracion values (?,?,?,?,?)",
                      (tenant, cid, json.dumps(limpios), usuario, time.time()))
        return limpios

    # ---------- ejecuciones ----------
    def ejecuciones(self, cid: str, tenant: str, limite: int = 20) -> List[Dict[str, Any]]:
        with self._con() as c:
            filas = c.execute("select id, usuario, inicio, fin, estado, avance, resumen, error from ejecuciones"
                              " where conector=? and tenant=? order by inicio desc limit ?", (cid, tenant, limite)).fetchall()
        return [{"id": f[0], "usuario": f[1], "inicio": f[2], "fin": f[3], "estado": f[4], "avance": f[5],
                 "resumen": json.loads(f[6]) if f[6] else None, "error": f[7]} for f in filas]

    def ejecucion(self, eid: str, tenant: str) -> Optional[Dict[str, Any]]:
        with self._con() as c:
            f = c.execute("select conector from ejecuciones where id=? and tenant=?", (eid, tenant)).fetchone()
        return next((x for x in self.ejecuciones(f[0], tenant, 200) if x["id"] == eid), None) if f else None

    def _apuntar(self, eid: str, **campos):
        sets = ", ".join(f"{k}=?" for k in campos)
        with self._lock, self._con() as c:
            c.execute(f"update ejecuciones set {sets} where id=?", (*campos.values(), eid))

    def lanzar(self, cid: str, tenant: str, usuario: str, *, en_hilo: bool = True) -> Dict[str, Any]:
        conector = self.conectores[cid]
        conf = self.configuracion(cid, tenant)
        if not conf:
            raise ConfiguracionInvalida("configura el conector antes de ejecutarlo")
        valores = conector.validar_configuracion(conf["valores"])
        with self._con() as c:
            if c.execute("select 1 from ejecuciones where conector=? and tenant=? and estado='en-curso'",
                         (cid, tenant)).fetchone():
                raise ConfiguracionInvalida("ya hay una ejecución en curso de este conector")
        eid = uuid.uuid4().hex[:12]
        with self._lock, self._con() as c:
            c.execute("insert into ejecuciones values (?,?,?,?,?,?,?,?,?,?)",
                      (eid, cid, tenant, usuario, time.time(), None, "en-curso", "empezando", None, None))
        modulo = importlib.import_module(f"conectores.{conector.carpeta.name}.conector")
        ctx = Contexto(tenant=tenant, registro=self.registro, http=self.http,
                       avance=lambda m: self._apuntar(eid, avance=m[:300]), detener=lambda: self._parar.get(eid, False))

        def correr():
            try:
                resumen = modulo.ejecutar(valores, ctx)
                self._apuntar(eid, estado="terminada", fin=time.time(), resumen=json.dumps(resumen, ensure_ascii=False))
                self._carta(conector, tenant, usuario, eid, resumen)
            except Exception as e:  # noqa: BLE001  el error queda en la ejecución
                log.warning("conector %s (%s) falló: %s", cid, tenant, e)
                self._apuntar(eid, estado="error", fin=time.time(), error=str(e)[:1000])

        if en_hilo:
            threading.Thread(target=correr, daemon=True, name=f"conector-{cid}").start()
        else:
            correr()
        return {"id": eid, "estado": "en-curso"}

    def parar(self, eid: str):
        self._parar[eid] = True

    def _carta(self, conector: Conector, tenant: str, usuario: str, eid: str, resumen: Dict[str, Any]):
        if self.publicador is None:
            return
        from sdk.eventos import nuevo_evento
        cifras = {k: resumen[k] for k in ("nuevos", "actualizados", "borrados") if isinstance(resumen.get(k), int)}
        try:
            self.publicador.publicar(nuevo_evento(
                "conector.ejecutado", tenant=tenant, subject=f"urn:ngsi-ld:EjecucionConector:{tenant}:{eid}",
                source=f"/tenants/{tenant}/servicios/catalogo", id=f"conector-ejecutado-{eid}",
                data={"conector": conector.id, "version": conector.version, "sentido": conector.sentido,
                      "escribe": conector.escribe, "usuario": usuario, **cifras}))
        except Exception as e:  # noqa: BLE001  la ejecución ya está hecha; la carta se avisa en el registro
            log.warning("no se pudo enviar la carta de la ejecución %s: %s", eid, e)
