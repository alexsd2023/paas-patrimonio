"""Capacidad certificacion-documental: prueba que un texto existía en una fecha y no se ha alterado.

Recibe un ``texto`` y devuelve una ``evidencia``: la huella (SHA-256 del texto normalizado) y sus anclajes
fuera de la plataforma, los que pida el parámetro ``anclajes``:

* ``blockchain`` · Bitcoin vía OpenTimestamps (real, gratuito, verificable por cualquiera)
* ``eidas``      · sello de tiempo RFC 3161 (demo: FreeTSA, no cualificado; producción: prestador cualificado)
* ``nom151``     · constancia de conservación (demo: SIMULADA; producción: PSC acreditado)

``operacion: actualizar`` completa los anclajes pendientes (el de blockchain tarda unas horas): la entrada
lleva el texto y su ``evidencia``. No guarda nada ni toca el catastro: eso lo hace el producto que la usa.

Además de la interfaz estándar, publica ``POST /verificar`` (texto + evidencia → veredicto). Verificar no
gasta cuota ni necesita cuenta: cualquiera debe poder comprobar una evidencia.
"""
from pathlib import Path
from typing import Any, Dict

from capacidades.certificacion_documental import motor, proveedores
from sdk.servicios import DocumentoInvalido, cargar, crear_servicio, validar_documento

MANIFIESTO = cargar(Path(__file__).parent)


def procesar(entrada: dict, parametros: dict) -> dict:
    if parametros.get("operacion") == "actualizar":
        if "evidencia" not in entrada:
            raise ValueError("actualizar necesita entrada.evidencia")
        return motor.actualizar(entrada["texto"], validar_documento("evidencia", entrada["evidencia"]))
    return motor.certificar(entrada["texto"], parametros.get("anclajes") or ["blockchain"])


app = crear_servicio(MANIFIESTO, procesar)


@app.get("/anclajes")
def anclajes():
    """Qué anclajes ofrece esta instalación y con qué valor (real, demo o simulado)."""
    return [proveedores.obtener(n).describir() for n in proveedores.disponibles()]


@app.post("/verificar")
def verificar(peticion: Dict[str, Any]):
    from fastapi import HTTPException
    texto, evidencia = peticion.get("texto"), peticion.get("evidencia")
    if not isinstance(texto, str):
        raise HTTPException(422, "falta «texto»")
    try:
        validar_documento("evidencia", evidencia)
    except DocumentoInvalido as ex:
        raise HTTPException(422, f"evidencia: {ex}")
    return motor.verificar(texto, evidencia)
