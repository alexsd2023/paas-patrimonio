"""Capacidad evaluacion-en15757: el microclima objetivo de una zona (EN 15757:2010).

Recibe una ``serie-ambiental`` (temperatura y humedad de una zona, idealmente un año por horas) y devuelve una
``evaluacion-climatica``: la banda objetivo, cuánto tiempo se sale de ella ahora y el nivel de riesgo.
No guarda nada ni toca el catastro: el gemelo patrimonial la usa cada hora, y cualquier institución puede
usarla por API con sus propias series (por ejemplo, las de sus dataloggers).
"""
from pathlib import Path

from capacidades.evaluacion_en15757.motor import evaluar
from sdk.servicios import cargar, crear_servicio

MANIFIESTO = cargar(Path(__file__).parent)


def procesar(entrada: dict, parametros: dict) -> dict:
    return evaluar(entrada, parametros)


app = crear_servicio(MANIFIESTO, procesar)
