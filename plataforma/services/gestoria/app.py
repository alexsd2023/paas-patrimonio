"""Gestoría · arranque del expediente (tramo 7 del caso).

Cuando llega «ha llegado un legajo», abre el expediente de transcripción de ese legajo.

Hoy el expediente es una fila en SQLite; en el paso 4 del plan, `abrir()` pasa a
arrancar el workflow TranscripcionEstandar en Temporal con el MISMO id
(transcripcion:<urn del activo>), que es lo que lo hace idempotente allí también.

    GET /expedientes?activo=<urn>
    GET /salud
"""
import logging
import os
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Query

from sdk.servicio import lanzar_consumidor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("gestoria")


class Expedientes:
    def __init__(self, ruta: str):
        self.ruta = ruta
        with self._con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS expedientes (
                id TEXT PRIMARY KEY, activo TEXT NOT NULL, tenant TEXT NOT NULL,
                proceso TEXT NOT NULL, estado TEXT NOT NULL,
                abierto_en TEXT NOT NULL, evento TEXT NOT NULL)""")

    def _con(self):
        return sqlite3.connect(self.ruta)

    def abrir(self, ev: dict) -> bool:
        """Abre el expediente si no existía. Devuelve False si ya estaba abierto."""
        if ev["type"] != "legajo.ingestado":
            return False
        exp_id = f"transcripcion:{ev['subject']}"
        with self._con() as c:
            cur = c.execute("INSERT OR IGNORE INTO expedientes VALUES (?,?,?,?,?,?,?)",
                            (exp_id, ev["subject"], ev["tenant"], "TranscripcionEstandar",
                             "abierto", ev["time"], ev["id"]))
        if cur.rowcount:
            log.info("expediente abierto %s", exp_id)
        return bool(cur.rowcount)

    def listar(self, activo: str) -> List[dict]:
        with self._con() as c:
            c.row_factory = sqlite3.Row
            return [dict(f) for f in c.execute(
                "SELECT * FROM expedientes WHERE activo = ? ORDER BY abierto_en", (activo,))]


def crear_app(expedientes: Expedientes, bootstrap: Optional[str] = None) -> FastAPI:
    estado: dict = {}

    @asynccontextmanager
    async def ciclo(app):
        if bootstrap:
            lanzar_consumidor(bootstrap=bootstrap, grupo="gestoria", topics=["activos"],
                              tipos=["legajo.ingestado"], manejar=expedientes.abrir, estado=estado)
        yield

    app = FastAPI(title="Gestoría (expedientes)", version="0.1.0", lifespan=ciclo)

    @app.get("/salud")
    def salud():
        return {"ok": True, "consumidor": estado}

    @app.get("/expedientes")
    def listar(activo: str = Query(...)):
        return expedientes.listar(activo)

    return app


app = crear_app(Expedientes(os.environ.get("GESTORIA_RUTA") or os.path.join(tempfile.gettempdir(), "gestoria.db")), os.environ.get("KAFKA_BOOTSTRAP"))
