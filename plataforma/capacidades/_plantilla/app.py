"""Servicio INTERNO: escribe `procesar` y la plantilla pone la interfaz estándar."""
from pathlib import Path

from sdk.servicios import cargar, crear_servicio

MANIFIESTO = cargar(Path(__file__).parent)


def procesar(entrada: dict, parametros: dict) -> dict:
    # entrada cumple el tipo «entrada» del manifiesto; devuelve un documento del tipo «salida»
    return {"texto": entrada["texto"]}


app = crear_servicio(MANIFIESTO, procesar)
