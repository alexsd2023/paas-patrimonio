"""Arranca un consumidor de eventos en segundo plano dentro de un servicio.

Si el manejador falla, el mensaje NO se confirma: el consumidor se reinicia a los 5 s
y lo vuelve a recibir (entrega «al menos una vez»). Por eso los manejadores deben ser
idempotentes: procesar dos veces el mismo evento no debe duplicar nada.
"""
import logging
import threading
import time
from typing import Callable, List, Optional

from .eventos import Consumidor

log = logging.getLogger("consumidor")


def lanzar_consumidor(*, bootstrap: str, grupo: str, topics: List[str],
                      manejar: Callable[[dict], None], estado: dict,
                      tipos: Optional[List[str]] = None) -> threading.Thread:
    estado.update(grupo=grupo, topics=topics, conectado=False, procesados=0, ultimo=None, error=None)

    def bucle():
        while True:
            try:
                estado.update(conectado=True, error=None)
                for ev in Consumidor(bootstrap, grupo=grupo, topics=topics, tipos=tipos,
                                     desde_el_principio=True):
                    manejar(ev)
                    estado["procesados"] += 1
                    estado["ultimo"] = ev["id"]
            except Exception as e:  # Kafka caído o manejador fallido: reintentar
                estado.update(conectado=False, error=str(e))
                log.error("consumidor %s detenido: %s · reintento en 5 s", grupo, e)
                time.sleep(5)

    hilo = threading.Thread(target=bucle, daemon=True, name=f"consumidor-{grupo}")
    hilo.start()
    return hilo
