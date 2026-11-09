"""Secretos de las capacidades (tokens de APIs externas, claves…), editables desde la consola.

Cada capacidad declara en su servicio.yaml qué secretos necesita:

    secretos:
      - nombre: NER_TOKEN
        descripcion: Token del Space de Hugging Face
        ambito: ambos          # plataforma | institucion | ambos

* plataforma: lo pone el equipo del PaaS (rol admin-paas) y vale para todas las instituciones.
* institucion: cada institución pone el suyo (rol admin-institucion), p. ej. su propia cuenta en la API.
* ambos: si la institución tiene el suyo se usa ese; si no, el de la plataforma.

Al ejecutar se resuelve: institución → plataforma → variable de entorno (lo que había en platform/.env).
Los valores se guardan cifrados (Fernet) y nunca salen por la API: solo se dice si están puestos.
"""
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken

PLATAFORMA = ""   # tenant con el que se guardan los secretos de la plataforma


def _clave(ruta_db: str) -> bytes:
    """CATALOGO_CLAVE si está definida; si no, una clave generada junto a la base de datos (volumen)."""
    if os.environ.get("CATALOGO_CLAVE"):
        return os.environ["CATALOGO_CLAVE"].encode()
    f = Path(ruta_db).with_name("secretos.clave")
    if not f.exists():
        f.write_bytes(Fernet.generate_key())
        os.chmod(f, 0o600)
    return f.read_bytes().strip()


class Secretos:
    def __init__(self, ruta: Optional[str] = None, clave: Optional[bytes] = None):
        self.ruta = ruta or os.path.join(tempfile.gettempdir(), "catalogo-secretos.db")
        self._f = Fernet(clave or _clave(self.ruta))
        self._lock = threading.Lock()
        with self._con() as c:
            c.execute("create table if not exists secretos (servicio text, tenant text, nombre text, valor blob,"
                      " por text, cuando real, primary key (servicio, tenant, nombre))")

    def _con(self):
        return sqlite3.connect(self.ruta)

    def poner(self, servicio: str, tenant: str, nombre: str, valor: str, por: str) -> None:
        with self._lock, self._con() as c:
            c.execute("insert or replace into secretos values (?,?,?,?,?,?)",
                      (servicio, tenant, nombre, self._f.encrypt(valor.encode()), por, time.time()))

    def quitar(self, servicio: str, tenant: str, nombre: str) -> bool:
        with self._lock, self._con() as c:
            return c.execute("delete from secretos where servicio=? and tenant=? and nombre=?",
                             (servicio, tenant, nombre)).rowcount > 0

    def _leer(self, servicio: str, tenant: str, nombre: str) -> Optional[str]:
        with self._con() as c:
            f = c.execute("select valor from secretos where servicio=? and tenant=? and nombre=?",
                          (servicio, tenant, nombre)).fetchone()
        if not f:
            return None
        try:
            return self._f.decrypt(f[0]).decode()
        except InvalidToken:
            return None  # se cambió CATALOGO_CLAVE: como si no estuviera

    def _meta(self, servicio: str, tenant: str, nombre: str) -> Optional[Dict]:
        with self._con() as c:
            f = c.execute("select por, cuando from secretos where servicio=? and tenant=? and nombre=?",
                          (servicio, tenant, nombre)).fetchone()
        return {"por": f[0], "cuando": f[1]} if f else None

    def valores(self, manifiesto, tenant: str) -> Dict[str, str]:
        """Lo que recibe el adaptador al ejecutar para esta institución."""
        out = {}
        for d in manifiesto.secretos:
            v = None
            if d["ambito"] in ("institucion", "ambos"):
                v = self._leer(manifiesto.id, tenant, d["nombre"])
            if v is None and d["ambito"] in ("plataforma", "ambos"):
                v = self._leer(manifiesto.id, PLATAFORMA, d["nombre"]) or os.environ.get(d["nombre"]) or None
            if v:
                out[d["nombre"]] = v
        return out

    def estado(self, manifiesto, tenant: str) -> List[Dict]:
        """Qué secretos pide la capacidad y cuáles están puestos (sin valores)."""
        out = []
        for d in manifiesto.secretos:
            inst = self._meta(manifiesto.id, tenant, d["nombre"]) if d["ambito"] != "plataforma" else None
            plat = self._meta(manifiesto.id, PLATAFORMA, d["nombre"]) if d["ambito"] != "institucion" else None
            entorno = d["ambito"] != "institucion" and bool(os.environ.get(d["nombre"]))
            out.append({**d, "institucion": inst, "plataforma": plat, "entorno": entorno,
                        "listo": bool(inst or plat or entorno)})
        return out
