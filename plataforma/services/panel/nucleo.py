"""Lo que el núcleo pone a disposición de cada producto dentro de la consola.

Un producto recibe un ``Nucleo`` en ``montar(nucleo, producto)`` y solo habla con el PaaS a través de él:

    nucleo.yo(req)              quién está en la consola (Identidad verificada por Keycloak)
    nucleo.token(req)           su token, para llamar a la API con su nombre
    nucleo.registro             el catastro (NGSI-LD, aislado por institución)
    nucleo.expedientes          los procesos de Temporal
    nucleo.actas(activo)        el libro del notario de un activo
    nucleo.servicio("htr")      URL interna de un servicio (http://htr:8080 o HTR_INTERNO)
    nucleo.api_publico          la puerta pública (APISIX)
    nucleo.enlaces              las consolas del núcleo (Temporal, Kafka UI, Jaeger…)
    nucleo.pagina(...)          pinta una vista del producto dentro de la consola común
"""
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from sdk.identidad import Identidad, NoAutorizado

COOKIE = "panel_token"


class Nucleo:
    def __init__(self, *, registro, verificador, expedientes, procedencia: str, api_publico: str,
                 enlaces: Dict[str, str], servicios: Optional[Dict[str, str]] = None,
                 pintar: Optional[Callable[..., str]] = None):
        self.registro = registro
        self.verificador = verificador
        self.expedientes = expedientes
        self.procedencia = procedencia
        self.api_publico = api_publico
        self.enlaces = enlaces
        self._servicios = servicios or {}
        self._pintar = pintar  # lo pone la consola: la plantilla con la barra lateral y la cabecera del producto

    # ---------- identidad ----------
    def yo(self, req: Request) -> Identidad:
        t = req.cookies.get(COOKIE)
        if not t:
            raise HTTPException(401, "inicia sesión")
        try:
            return self.verificador.verificar(t)
        except NoAutorizado as e:
            raise HTTPException(401, e.motivo)

    def token(self, req: Request) -> str:
        return req.cookies.get(COOKIE, "")

    @staticmethod
    def de_mi_institucion(urn: str, quien: Identidad) -> None:
        """Las URN del catastro llevan la institución en la cuarta posición."""
        if urn.split(":")[3:4] != [quien.tenant]:
            raise HTTPException(403, "no es de tu institución")

    # ---------- servicios ----------
    def servicio(self, nombre: str) -> str:
        if nombre in self._servicios:
            return self._servicios[nombre]
        return os.environ.get(f"{nombre.upper()}_INTERNO", f"http://{nombre}:8080").rstrip("/")

    def actas(self, activo: str) -> List[Dict[str, Any]]:
        url = f"{self.procedencia}/actas?activo={urllib.parse.quote(activo, safe='')}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())

    # ---------- consola ----------
    def pagina(self, req: Request, producto: str, vista: str, cuerpo: str, script: str = "", estilo: str = "",
               datos: Optional[Dict[str, Any]] = None) -> HTMLResponse:
        """Una vista del producto dentro de la consola. Sin sesión, la consola pide entrar."""
        return HTMLResponse(self._pintar(req, producto=producto, vista=vista, cuerpo=cuerpo, script=script,
                                         estilo=estilo, datos=datos or {}))
