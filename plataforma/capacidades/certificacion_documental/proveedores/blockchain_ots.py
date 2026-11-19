"""Blockchain abierta: Bitcoin a través de OpenTimestamps.

Los calendarios públicos de OpenTimestamps agrupan las huellas de muchos usuarios y anclan la raíz
en una transacción de Bitcoin que pagan ellos. Al anclar se recibe una prueba provisional (pendiente);
unas horas después, `actualizar` la completa con el bloque. La prueba completa (.ots) se verifica
contra Bitcoin sin depender ni de los calendarios ni de esta plataforma (p. ej. en opentimestamps.org).

Entorno:
  OTS_CALENDARIOS  calendarios separados por comas (por defecto los agregadores públicos del cliente ots)
  OTS_EXPLORADOR   API tipo Esplora para comprobar el bloque (por defecto https://blockstream.info/api);
                   vacío = no comprobar contra la cadena
  OTS_ESPERA_S     segundos de espera por calendario (por defecto 10)
"""
import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional

from opentimestamps.calendar import DEFAULT_AGGREGATORS, RemoteCalendar
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

from .base import Proveedor, ahora, b64, de_b64, iso


def serializar(dtf: DetachedTimestampFile) -> bytes:
    ctx = BytesSerializationContext()
    dtf.serialize(ctx)
    return ctx.getbytes()


def deserializar(datos: bytes) -> DetachedTimestampFile:
    return DetachedTimestampFile.deserialize(BytesDeserializationContext(datos))


def _nodos(t: Timestamp) -> Iterator[Timestamp]:
    yield t
    for sub in t.ops.values():
        yield from _nodos(sub)


def _bloque(t: Timestamp) -> Optional[tuple]:
    """(altura, msg) de la atestación de Bitcoin más antigua, si la hay."""
    mejores = [(att.height, msg) for msg, att in t.all_attestations() if isinstance(att, BitcoinBlockHeaderAttestation)]
    return min(mejores) if mejores else None


def _esplora(base: str, espera: float) -> Callable[[int], Dict[str, Any]]:
    def consultar(altura: int) -> Dict[str, Any]:
        with urllib.request.urlopen(f"{base}/block-height/{altura}", timeout=espera) as r:
            h = r.read().decode().strip()
        with urllib.request.urlopen(f"{base}/block/{h}", timeout=espera) as r:
            b = json.loads(r.read())
        return {"merkle_root": b["merkle_root"], "timestamp": b["timestamp"]}
    return consultar


class BlockchainOTS(Proveedor):
    nombre, modo, valor_legal = "blockchain", "real", "ninguno"
    emisor = "Bitcoin · OpenTimestamps"

    def __init__(self, calendarios: Optional[List[str]] = None, calendario: Optional[Callable[[str], Any]] = None,
                 explorador: Optional[Callable[[int], Dict[str, Any]]] = None, espera: Optional[float] = None):
        env = os.environ.get("OTS_CALENDARIOS", "")
        self.calendarios = calendarios or [u.strip() for u in env.split(",") if u.strip()] or list(DEFAULT_AGGREGATORS)
        self.espera = espera if espera is not None else float(os.environ.get("OTS_ESPERA_S", "10"))
        self._calendario = calendario or (lambda url: RemoteCalendar(url, user_agent="paas-patrimonio"))
        if explorador is not None:
            self._explorador = explorador
        else:
            base = os.environ.get("OTS_EXPLORADOR", "https://blockstream.info/api").rstrip("/")
            self._explorador = _esplora(base, self.espera) if base else None

    def anclar(self, digest: bytes) -> Dict[str, Any]:
        dtf = DetachedTimestampFile(OpSHA256(), Timestamp(digest))
        raiz = dtf.timestamp.ops.add(OpAppend(os.urandom(16))).ops.add(OpSHA256())  # el nonce oculta la huella
        aceptan, fallos = 0, []
        for url in self.calendarios:
            try:
                raiz.merge(self._calendario(url).submit(raiz.msg, timeout=self.espera))
                aceptan += 1
            except Exception as ex:  # noqa: BLE001  basta con que acepte uno
                fallos.append(f"{url}: {ex}")
        if not aceptan:
            raise RuntimeError("ningún calendario de OpenTimestamps aceptó la huella: " + "; ".join(fallos))
        return self._anclaje(estado="pendiente", fecha=ahora(), prueba=b64(serializar(dtf)),
                             detalle=f"Enviada a {aceptan} de {len(self.calendarios)} calendarios; "
                                     "pendiente de confirmar en un bloque de Bitcoin (unas horas)")

    def actualizar(self, anclaje: Dict[str, Any], digest: bytes) -> Dict[str, Any]:
        dtf = deserializar(de_b64(anclaje["prueba"]))
        if dtf.file_digest != digest:
            raise ValueError("la prueba .ots no corresponde a esta huella")
        for nodo in list(_nodos(dtf.timestamp)):
            for att in list(nodo.attestations):
                if isinstance(att, PendingAttestation):
                    try:
                        nodo.merge(self._calendario(att.uri).get_timestamp(nodo.msg, timeout=self.espera))
                    except Exception:  # noqa: BLE001  aún no está en un bloque: se reintentará
                        pass
        bloque = _bloque(dtf.timestamp)
        nuevo = dict(anclaje, prueba=b64(serializar(dtf)))
        if bloque:
            nuevo.update(estado="confirmado", bloque=bloque[0],
                         detalle=f"Anclada en el bloque {bloque[0]} de Bitcoin")
            try:
                nuevo["fecha"] = self._comprobar(bloque)["fecha"] or nuevo.get("fecha")
            except Exception:  # noqa: BLE001  la fecha del bloque es un extra
                pass
        return nuevo

    def _comprobar(self, bloque: tuple) -> Dict[str, Any]:
        """Compara el dato anclado con la raíz de Merkle del bloque (vía explorador)."""
        if not self._explorador:
            return {"comprobado": False, "fecha": None}
        altura, msg = bloque
        b = self._explorador(altura)
        if msg[::-1].hex() != b["merkle_root"]:  # Bitcoin muestra la raíz con los bytes invertidos
            raise ValueError(f"la prueba no coincide con la raíz de Merkle del bloque {altura}")
        return {"comprobado": True, "fecha": iso(datetime.fromtimestamp(b["timestamp"], tz=timezone.utc))}

    def verificar(self, anclaje: Dict[str, Any], digest: bytes) -> Dict[str, Any]:
        try:
            dtf = deserializar(de_b64(anclaje["prueba"]))
        except Exception as ex:  # noqa: BLE001
            return {"valido": False, "detalle": f"prueba .ots ilegible: {ex}"}
        if dtf.file_digest != digest:
            return {"valido": False, "detalle": "el texto no coincide con la huella anclada"}
        bloque = _bloque(dtf.timestamp)
        if not bloque:
            return {"valido": True, "detalle": "Huella correcta; pendiente de confirmar en Bitcoin"}
        try:
            r = self._comprobar(bloque)
        except ValueError as ex:
            return {"valido": False, "detalle": str(ex), "bloque": bloque[0]}
        except Exception as ex:  # noqa: BLE001  sin red: la prueba es correcta pero no se pudo cotejar
            return {"valido": True, "bloque": bloque[0],
                    "detalle": f"Huella anclada en el bloque {bloque[0]} (no cotejado con la cadena: {ex})"}
        out = {"valido": True, "bloque": bloque[0],
               "detalle": f"Huella anclada en el bloque {bloque[0]} de Bitcoin"
                          + ("" if r["comprobado"] else " (no cotejado con la cadena)")}
        if r.get("fecha"):
            out["fecha"] = r["fecha"]
        return out
