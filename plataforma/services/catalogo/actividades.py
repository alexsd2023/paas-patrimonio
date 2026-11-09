"""Actividades del flujo: lo que toca el mundo (servicios, catastro, bus). Se ejecutan en el worker."""
import json
import logging
from typing import Any, Dict

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sdk.registro import urn_transcripcion
from sdk.servicios import DocumentoInvalido, validar_documento
from services.catalogo.catalogo import CuotaAgotada, FalloDelServicio, SinPermiso

log = logging.getLogger("catalogo.flujos")


def _v(e, k, defecto=None):
    if not e or k not in e:
        return defecto
    a = e[k]
    return a.get("value", a.get("object", defecto)) if isinstance(a, dict) else a


def urn_resultado(tenant: str, fid: str) -> str:
    return f"urn:ngsi-ld:ResultadoFlujo:{tenant}:{fid}"


class Actividades:
    def __init__(self, catalogo, registro, publicador=None):
        self.catalogo, self.registro, self.publicador = catalogo, registro, publicador

    def todas(self):
        return [self.leer_entrada, self.ejecutar_servicio, self.publicar_resultado]

    @activity.defn(name="leer_entrada")
    def leer_entrada(self, a: Dict[str, Any]) -> dict:
        """El documento de partida: el que trae la petición o la transcripción de un legajo del catastro."""
        entrada, tenant, tipo = a["entrada"], a["tenant"], a["tipo"]
        if "documento" in entrada:
            doc = entrada["documento"]
        else:
            activo = entrada.get("activo", "")
            if activo.split(":")[3:4] != [tenant]:
                raise ApplicationError("el legajo no es de tu institución", type="NoReintentable")
            copia = self.registro.leer(tenant, urn_transcripcion(activo))
            if not copia or not _v(copia, "texto"):
                raise ApplicationError(f"{activo} aún no tiene transcripción en el catastro", type="NoReintentable")
            doc = {"texto": _v(copia, "texto"), "activo": activo}
        try:
            return validar_documento(tipo, doc)
        except DocumentoInvalido as e:
            raise ApplicationError(f"el documento de entrada no es un {tipo}: {e}", type="NoReintentable")

    @activity.defn(name="ejecutar_servicio")
    def ejecutar_servicio(self, a: Dict[str, Any]) -> dict:
        try:
            return self.catalogo.ejecutar(a["servicio"], a["documento"], a["parametros"], tenant=a["tenant"],
                                          roles=a["roles"], al_avanzar=lambda _e: activity.heartbeat())
        except (SinPermiso, CuotaAgotada, DocumentoInvalido, KeyError) as e:
            raise ApplicationError(str(e), type="NoReintentable")
        except FalloDelServicio as e:
            raise ApplicationError(str(e))  # se reintenta: el servicio puede estar despertando

    @activity.defn(name="publicar_resultado")
    def publicar_resultado(self, a: Dict[str, Any]) -> str:
        """El resultado queda en el catastro (ResultadoFlujo) y sale la carta flujo.completado."""
        tenant, fid, doc = a["tenant"], a["id"], a["documento"]
        urn = urn_resultado(tenant, fid)
        P = lambda v: {"type": "Property", "value": v}  # noqa: E731
        # documento y procedencia como texto JSON: así vuelven del catastro exactamente iguales
        entidad = {"id": urn, "type": "ResultadoFlujo", "nombre": P(a["nombre"]), "tipoDocumento": P(a["tipo"]),
                   "documento": P(json.dumps(doc, ensure_ascii=False)),
                   "procedencia": P(json.dumps(a["procedencia"], ensure_ascii=False)), "lanzadoPor": P(a["usuario"])}
        if doc.get("activo"):
            entidad["deActivo"] = {"type": "Relationship", "object": doc["activo"]}
        estado = self.registro.crear(tenant, entidad)
        if estado not in (201, 409):
            raise ApplicationError(f"el catastro respondió {estado} al inscribir {urn}")
        if self.publicador is not None:
            from sdk.eventos import nuevo_evento
            datos = {"flujo": fid, "nombre": a["nombre"], "tipo": a["tipo"], **a["procedencia"]}
            if doc.get("activo"):
                datos["activo"] = doc["activo"]
            self.publicador.publicar(nuevo_evento("flujo.completado", tenant=tenant, subject=urn,
                                                  source=f"/tenants/{tenant}/servicios/catalogo", data=datos,
                                                  id=f"flujo-completado-{fid}"))
        log.info("flujo %s publicado como %s", fid, urn)
        return urn
