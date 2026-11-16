"""Series de temperatura y humedad de las zonas del gemelo patrimonial.

Dos orígenes, que se eligen con SERIES_ORIGEN:

    local    (por defecto) · el servicio guarda cada lectura que llega por el bus (zona.medicion) en SQLite.
    scorpio  · las lecturas reales se leen del historial del catastro (API temporal NGSI-LD de Scorpio).
               Actívalo cuando scripts/scorpio_temporal_check.py pase en tu servidor.

El histórico sintético (para calibrar el microclima objetivo sin un año real) siempre se guarda aquí, marcado como
«sintetico», y se combina con las lecturas reales: una evaluación sabe siempre sobre qué datos se calculó.

Para no crecer sin límite, las lecturas de más de 48 h se resumen en una por hora y zona (compactar).
"""
import json
import sqlite3
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

ESQUEMA = """
CREATE TABLE IF NOT EXISTS lecturas (
    tenant TEXT NOT NULL, zona TEXT NOT NULL, sensor TEXT NOT NULL, t TEXT NOT NULL,
    temperatura REAL NOT NULL, humedad REAL NOT NULL, origen TEXT NOT NULL,
    PRIMARY KEY (tenant, zona, sensor, t));
CREATE INDEX IF NOT EXISTS lecturas_zona ON lecturas (tenant, zona, t);
CREATE TABLE IF NOT EXISTS tenants (tenant TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS evaluaciones (tenant TEXT, zona TEXT, cuando TEXT, json TEXT, PRIMARY KEY (tenant, zona));
"""


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fecha(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class SeriesLocal:
    origen = "local"

    def __init__(self, ruta: str = ":memory:"):
        self._c = sqlite3.connect(ruta, check_same_thread=False)
        self._c.executescript(ESQUEMA)
        self._lock = threading.Lock()

    def guardar(self, tenant: str, zona: str, sensor: str, t: str, temperatura: float, humedad: float,
                origen: str = "real") -> None:
        with self._lock, self._c:
            self._c.execute("INSERT OR REPLACE INTO lecturas VALUES (?,?,?,?,?,?,?)",
                            (tenant, zona, sensor, iso(fecha(t)), temperatura, humedad, origen))

    def guardar_muchas(self, tenant: str, zona: str, puntos: Iterable[dict], origen: str = "sintetico",
                       sensor: str = "*") -> int:
        filas = [(tenant, zona, sensor, iso(fecha(p["t"])), p["temperatura"], p["humedad"], origen) for p in puntos]
        with self._lock, self._c:
            self._c.executemany("INSERT OR REPLACE INTO lecturas VALUES (?,?,?,?,?,?,?)", filas)
        return len(filas)

    def borrar(self, tenant: str, zona: str, desde: Optional[datetime] = None) -> None:
        with self._lock, self._c:
            if desde:
                self._c.execute("DELETE FROM lecturas WHERE tenant=? AND zona=? AND t>=?", (tenant, zona, iso(desde)))
            else:
                self._c.execute("DELETE FROM lecturas WHERE tenant=? AND zona=?", (tenant, zona))

    def tiene_sintetico(self, tenant: str, zona: str) -> bool:
        with self._lock:
            return self._c.execute("SELECT 1 FROM lecturas WHERE tenant=? AND zona=? AND origen='sintetico' LIMIT 1",
                                   (tenant, zona)).fetchone() is not None

    # ---------- instituciones con gemelo y última evaluación de cada zona ----------
    def anadir_tenant(self, tenant: str) -> None:
        with self._lock, self._c:
            self._c.execute("INSERT OR IGNORE INTO tenants VALUES (?)", (tenant,))

    def tenants(self) -> List[str]:
        with self._lock:
            return [t for (t,) in self._c.execute("SELECT tenant FROM tenants ORDER BY 1")]

    def guardar_evaluacion(self, tenant: str, zona: str, evaluacion: dict) -> None:
        with self._lock, self._c:
            self._c.execute("INSERT OR REPLACE INTO evaluaciones VALUES (?,?,?,?)",
                            (tenant, zona, iso(datetime.now(timezone.utc)), json.dumps(evaluacion)))

    def evaluacion(self, tenant: str, zona: str) -> Optional[dict]:
        with self._lock:
            f = self._c.execute("SELECT cuando, json FROM evaluaciones WHERE tenant=? AND zona=?", (tenant, zona)).fetchone()
        return {**json.loads(f[1]), "calculadaEn": f[0]} if f else None

    def zonas(self) -> List[tuple]:
        with self._lock:
            return self._c.execute("SELECT DISTINCT tenant, zona FROM lecturas").fetchall()

    def horaria(self, tenant: str, zona: str, desde: datetime, hasta: Optional[datetime] = None,
                solo: Optional[str] = None) -> List[dict]:
        """Un punto por hora (media de todos los sensores de la zona), con los orígenes que lo forman."""
        hasta = hasta or datetime.now(timezone.utc) + timedelta(hours=1)
        q = ("SELECT substr(t,1,13), avg(temperatura), avg(humedad), group_concat(DISTINCT origen) FROM lecturas "
             "WHERE tenant=? AND zona=? AND t>=? AND t<?" + (" AND origen=?" if solo else "") +
             " GROUP BY substr(t,1,13) ORDER BY 1")
        args = [tenant, zona, iso(desde), iso(hasta)] + ([solo] if solo else [])
        with self._lock:
            filas = self._c.execute(q, args).fetchall()
        return [{"t": f"{h}:00:00Z", "temperatura": round(t, 2), "humedad": round(hr, 2), "origen": o}
                for h, t, hr, o in filas]

    def ultimas(self, tenant: str, zona: str, n: int = 1) -> List[dict]:
        with self._lock:
            filas = self._c.execute("SELECT sensor, t, temperatura, humedad, origen FROM lecturas WHERE tenant=? "
                                    "AND zona=? AND origen='real' AND sensor!='*' ORDER BY t DESC LIMIT ?",
                                    (tenant, zona, n)).fetchall()
        return [{"sensor": s, "t": t, "temperatura": te, "humedad": h, "origen": o} for s, t, te, h, o in filas]

    def compactar(self, antes_de: Optional[datetime] = None) -> int:
        """Las lecturas reales de más de 48 h pasan a una por hora y zona (sensor «*»)."""
        corte = iso(antes_de or datetime.now(timezone.utc) - timedelta(hours=48))
        with self._lock, self._c:
            n = self._c.execute("SELECT count(*) FROM lecturas WHERE origen='real' AND sensor!='*' AND t<?",
                                (corte,)).fetchone()[0]
            if not n:
                return 0
            self._c.execute(
                "INSERT OR REPLACE INTO lecturas SELECT tenant, zona, '*', substr(t,1,13)||':00:00Z', avg(temperatura), "
                "avg(humedad), 'real' FROM lecturas WHERE origen='real' AND sensor!='*' AND t<? "
                "GROUP BY tenant, zona, substr(t,1,13)", (corte,))
            self._c.execute("DELETE FROM lecturas WHERE origen='real' AND sensor!='*' AND t<?", (corte,))
        return n


class SeriesScorpio(SeriesLocal):
    """Las lecturas reales salen del historial del catastro; lo sintético, de SQLite."""

    origen = "scorpio"

    def __init__(self, registro, ruta: str = ":memory:"):
        super().__init__(ruta)
        self.reg = registro

    def guardar(self, tenant, zona, sensor, t, temperatura, humedad, origen="real"):
        if origen != "real":
            super().guardar(tenant, zona, sensor, t, temperatura, humedad, origen)
        # las reales ya las guarda Scorpio en su historial

    def temporal(self, tenant: str, zona: str, desde: datetime, hasta: datetime) -> List[dict]:
        q = urllib.parse.urlencode({
            "type": "IndoorEnvironmentObserved", "q": f'refZone=="{zona}"', "attrs": "temperature,relativeHumidity",
            "timerel": "between", "timeAt": iso(desde), "endTimeAt": iso(hasta), "lastN": 20000})
        estado, cuerpo = self.reg._req("GET", f"/ngsi-ld/v1/temporal/entities?{q}", tenant)
        if estado != 200:
            raise RuntimeError(f"la API temporal del catastro respondió {estado}: {str(cuerpo)[:200]}")
        out = []
        for e in cuerpo if isinstance(cuerpo, list) else []:
            ts = {x.get("observedAt"): x.get("value") for x in _instancias(e.get("temperature"))}
            for x in _instancias(e.get("relativeHumidity")):
                cuando = x.get("observedAt")
                if cuando in ts and ts[cuando] is not None and x.get("value") is not None:
                    out.append({"sensor": e.get("id"), "t": cuando, "temperatura": float(ts[cuando]),
                                "humedad": float(x["value"])})
        return out

    def horaria(self, tenant, zona, desde, hasta=None, solo=None):
        hasta = hasta or datetime.now(timezone.utc) + timedelta(hours=1)
        sinteticas = [] if solo == "real" else super().horaria(tenant, zona, desde, hasta, solo="sintetico")
        if solo == "sintetico":
            return sinteticas
        cubos: Dict[str, List[tuple]] = {}
        for p in self.temporal(tenant, zona, desde, hasta):
            cubos.setdefault(iso(fecha(p["t"]))[:13], []).append((p["temperatura"], p["humedad"]))
        reales = {h: {"t": f"{h}:00:00Z", "temperatura": round(sum(a for a, _ in vs) / len(vs), 2),
                      "humedad": round(sum(b for _, b in vs) / len(vs), 2), "origen": "real"} for h, vs in cubos.items()}
        for p in sinteticas:
            h = p["t"][:13]
            if h in reales:
                r = reales[h]
                r.update(temperatura=round((r["temperatura"] + p["temperatura"]) / 2, 2),
                         humedad=round((r["humedad"] + p["humedad"]) / 2, 2), origen="real,sintetico")
            else:
                reales[h] = p
        return [reales[h] for h in sorted(reales)]


def _instancias(attr) -> List[dict]:
    """La API temporal devuelve una lista de instancias (o una sola si solo hay una)."""
    if isinstance(attr, list):
        return [x for x in attr if isinstance(x, dict)]
    return [attr] if isinstance(attr, dict) else []


def crear(origen: str, registro, ruta: str):
    if origen == "scorpio":
        return SeriesScorpio(registro, ruta)
    if origen != "local":
        raise ValueError(f"SERIES_ORIGEN: local | scorpio (no {origen!r})")
    return SeriesLocal(ruta)


def resumen_origen(puntos: List[dict]) -> str:
    """historico | sintetico | mixto, para la evaluación."""
    tipos = set()
    for p in puntos:
        tipos.update((p.get("origen") or "real").split(","))
    if tipos <= {"real"}:
        return "historico"
    return "sintetico" if tipos <= {"sintetico"} else "mixto"


