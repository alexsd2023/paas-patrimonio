"""Clima simulado de una zona patrimonial: lo usan el simulador de sensores (en vivo) y el histórico sintético.

Un clima de interior razonable: ciclo estacional (más húmedo y fresco en invierno), ciclo diario suave y un
ruido que se arrastra (no salta de una lectura a otra). Tres perfiles para la demo:

    estable      · el clima de siempre de la zona
    desviacion   · una desviación sostenida (fuga, avería de la climatización): +18 puntos de humedad
    fluctuacion  · oscilaciones rápidas de humedad (puerta abierta, deshumidificador que entra y sale)
"""
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, Tuple

PERFILES = ("estable", "desviacion", "fluctuacion")
CLIMA_POR_DEFECTO = {"temperatura": 18.0, "humedad": 55.0, "amplitudTemperatura": 3.0, "amplitudHumedad": 7.0}


def _base(clima: Dict[str, float], cuando: datetime) -> Tuple[float, float]:
    dia = cuando.timetuple().tm_yday
    # invierno (enero) fresco y húmedo; verano seco y templado
    estacion = math.cos(2 * math.pi * (dia - 15) / 365)
    hora = math.sin(2 * math.pi * (cuando.hour + cuando.minute / 60 - 9) / 24)
    t = clima["temperatura"] - clima.get("amplitudTemperatura", 3.0) * estacion + 0.4 * hora
    h = clima["humedad"] + clima.get("amplitudHumedad", 7.0) * estacion - 1.0 * hora
    return t, h


class Ruido:
    """Ruido que se arrastra (proceso AR(1)), reproducible con su semilla."""

    def __init__(self, semilla: str):
        self.rnd = random.Random(semilla)
        self.t = self.h = 0.0

    def paso(self) -> Tuple[float, float]:
        self.t = 0.92 * self.t + self.rnd.gauss(0, 0.12)
        self.h = 0.92 * self.h + self.rnd.gauss(0, 0.6)
        return self.t, self.h


def lectura(clima: Dict[str, float], cuando: datetime, perfil: str, ruido: Ruido,
            desde_perfil: float = 1e9) -> Tuple[float, float]:
    """(temperatura, humedad) en `cuando`. `desde_perfil` son las horas que lleva activo el perfil."""
    t, h = _base(clima, cuando)
    rt, rh = ruido.paso()
    t, h = t + rt, h + rh
    if perfil == "desviacion":
        rampa = min(1.0, max(0.0, desde_perfil) / 12)   # entra en unas doce horas (no es un salto brusco)
        t, h = t + 0.5 * rampa, h + 18 * rampa
    elif perfil == "fluctuacion":
        h += 9 * math.sin(2 * math.pi * (cuando.timestamp() / 3600) / 3)   # ±9 puntos cada 3 horas
    return round(t, 2), round(max(0.0, min(100.0, h)), 2)


def historico(clima: Dict[str, float], semilla: str, hasta: datetime, dias: int = 395,
              perfil_final: str = "estable", dias_perfil: int = 0) -> Iterator[dict]:
    """Un punto por hora durante `dias` días hasta `hasta`. Los últimos `dias_perfil` días, con `perfil_final`."""
    ruido = Ruido(semilla)
    inicio = hasta.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=dias)
    corte = inicio + timedelta(days=dias - dias_perfil)
    for i in range(dias * 24):
        cuando = inicio + timedelta(hours=i)
        perfil = perfil_final if cuando >= corte else "estable"
        t, h = lectura(clima, cuando, perfil, ruido, (cuando - corte).total_seconds() / 3600)
        yield {"t": cuando.isoformat(timespec="seconds").replace("+00:00", "Z"), "temperatura": t, "humedad": h}
