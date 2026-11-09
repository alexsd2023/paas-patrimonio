"""Modernizador de grafía de DEMOSTRACIÓN, escrito con la plantilla de servicio interno.

Son unas pocas reglas para enseñar cómo se encadenan servicios en un flujo. El modernizador
paleográfico real se publica igual: su ``servicio.yaml`` y una función ``procesar``.
"""
import re
from pathlib import Path

from sdk.servicios import cargar, crear_servicio

MANIFIESTO = cargar(Path(__file__).parent)

PALABRAS = {
    "e": "y", "mill": "mil", "escriuano": "escribano", "escrivano": "escribano", "paresçió": "pareció",
    "paresçio": "pareció", "escriptos": "escritos", "dixo": "dijo", "dixeron": "dijeron", "fizo": "hizo",
    "fazer": "hacer", "auia": "había", "avia": "había", "ansi": "así", "agora": "ahora", "vezino": "vecino",
    "vezinos": "vecinos", "rrey": "rey", "rreal": "real", "nueua": "nueva",
}
REGLAS = [(re.compile("ç"), "z"), (re.compile("ss"), "s"), (re.compile("ph"), "f"), (re.compile("^rr"), "r"),
          (re.compile(r"(?<=[aeiouáéíóú])u(?=[aeiouáéíóú])"), "v")]


def modernizar_palabra(p: str) -> str:
    base = p.lower()
    if base in PALABRAS:
        nueva = PALABRAS[base]
    else:
        nueva = base
        for patron, cambio in REGLAS:
            nueva = patron.sub(cambio, nueva)
    if p[:1].isupper():
        nueva = nueva[:1].upper() + nueva[1:]
    return nueva


def procesar(entrada: dict, parametros: dict) -> dict:
    texto = entrada["texto"]
    partes, cambios, pos = [], [], 0
    for m in re.finditer(r"[^\W\d_]+", texto):
        partes.append(texto[pos:m.start()])
        nueva = modernizar_palabra(m.group())
        if not parametros.get("conservar_mayusculas", True):
            nueva = nueva.lower()
        if nueva != m.group():
            cambios.append({"original": m.group(), "moderno": nueva, "inicio": m.start()})
        partes.append(nueva)
        pos = m.end()
    partes.append(texto[pos:])
    salida = {"texto": "".join(partes), "original": texto, "cambios": cambios}
    if entrada.get("activo"):
        salida["activo"] = entrada["activo"]
    return salida


app = crear_servicio(MANIFIESTO, procesar)
