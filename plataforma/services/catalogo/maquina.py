"""Estado de un flujo en marcha, paso a paso. Pura y determinista: la usa el workflow de Temporal
y se prueba sin Temporal. Las horas las pone quien llama (en el workflow, ``workflow.now()``)."""
from typing import Any, Dict, List, Optional


class FirmaNoValida(ValueError):
    pass


class Maquina:
    def __init__(self, flujo: Dict[str, Any]):
        plan = flujo["plan"]
        self.e: Dict[str, Any] = {
            "id": flujo["id"], "nombre": plan["nombre"], "tenant": flujo["tenant"], "lanzadoPor": flujo["usuario"],
            "estado": "en-curso", "paso": 0, "documento": None, "tipo": plan["entrada"], "resultado": None,
            "error": None, "publicar": plan["publicar"],
            "pasos": [{**p, "estado": "pendiente"} for p in plan["pasos"]],
        }

    # --- consultas ---
    @property
    def pasos(self) -> List[Dict[str, Any]]:
        return self.e["pasos"]

    def actual(self) -> Optional[Dict[str, Any]]:
        i = self.e["paso"]
        return self.pasos[i] if i < len(self.pasos) else None

    # --- transiciones ---
    def con_documento(self, doc: dict) -> None:
        self.e["documento"] = doc

    def empieza(self, ahora: str) -> Dict[str, Any]:
        p = self.actual()
        p["estado"], p["inicio"] = ("en-curso" if p["clase"] == "servicio" else "esperando-firma"), ahora
        if p["clase"] == "firma":
            self.e["estado"] = "esperando-firma"
        return p

    def servicio_hecho(self, resultado: Dict[str, Any], ahora: str) -> None:
        p = self.actual()
        p.update(estado="hecho", fin=ahora, ms=resultado.get("ms"), version=resultado.get("version", p.get("version")))
        self.e["documento"] = resultado["salida"]
        self.e["tipo"] = p["entrega"]
        self.e["paso"] += 1

    def puede_firmar(self, usuario: str, roles: List[str]) -> Optional[str]:
        """None si puede; si no, el motivo."""
        p = self.actual()
        if self.e["estado"] != "esperando-firma" or not p or p["clase"] != "firma":
            return "el flujo no está esperando una firma"
        if p["rol"] not in roles:
            return f"esta firma es de una persona con rol {p['rol']}"
        return None

    def firma(self, usuario: str, roles: List[str], decision: str, comentario: str, ahora: str) -> None:
        motivo = self.puede_firmar(usuario, roles)
        if motivo:
            raise FirmaNoValida(motivo)
        if decision not in ("aprueba", "rechaza"):
            raise FirmaNoValida("decision: aprueba | rechaza")
        p = self.actual()
        p.update(estado="aprobado" if decision == "aprueba" else "rechazado", fin=ahora, firmadoPor=usuario,
                 comentario=comentario)
        if decision == "rechaza":
            self.e["estado"] = "rechazado"
            return
        self.e["estado"] = "en-curso"
        self.e["paso"] += 1

    def falla(self, motivo: str, ahora: str) -> None:
        p = self.actual()
        if p:
            p.update(estado="error", fin=ahora, error=motivo)
        self.e.update(estado="error", error=motivo)

    def termina(self, resultado: Optional[str], ahora: str) -> None:
        self.e.update(estado="terminado", resultado=resultado, fin=ahora)

    def procedencia(self) -> Dict[str, Any]:
        """Lo que se publica y lo que levanta acta: qué versiones procesaron y quién firmó."""
        return {"servicios": [{"servicio": p["servicio"], "version": p["version"]} for p in self.pasos
                              if p["clase"] == "servicio"],
                "firmas": [{"rol": p["rol"], "usuario": p.get("firmadoPor")} for p in self.pasos
                           if p["clase"] == "firma"]}
