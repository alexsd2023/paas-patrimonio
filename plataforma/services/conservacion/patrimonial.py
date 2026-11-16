"""Conservación del gemelo patrimonial: series → capacidad EN 15757 → evaluación y alertas con firma.

El reparto (ver la especificación v1.1, capítulo 5):
  · la capacidad ``evaluacion-en15757`` calcula (pura, por el catálogo: cuenta en el consumo de la institución);
  · este servicio lee las series, escribe ClimateAssessment y ConservationAlert en el catastro, envía
    conservacion.evaluada y conservacion.riesgo, y deja las firmas (reconocer, cerrar) en Temporal.

Una alerta:  abierta → (agravada) → (reconocida) → (propuesta-cierre) → cerrada
  · la abre o la agrava la evaluación (medio / alto);
  · la propone cerrar la evaluación cuando la zona lleva RECUPERACION_DIAS seguidos en nivel bajo;
  · la reconoce y la cierra una persona (conservación), siempre con la causa: eso queda en el notario.
"""
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from productos.gemelo import clima as C
from productos.gemelo import modelo as M
from services.conservacion.series import fecha, iso, resumen_origen

log = logging.getLogger("conservacion.patrimonial")
ESPACIO_IDS = uuid.UUID("5b0f4c1e-7a2d-4e8b-9c3f-0d1a2b3c4d5e")
CALIBRACION_DIAS = 395
ABIERTAS = ("activa", "reconocida")
SEVERIDAD = {"medio": "warning", "alto": "critical"}


class Conflicto(Exception):
    """La alerta no está en un estado que permita lo que se pide."""


def decidir(alerta: Optional[dict], nivel: str, ahora: datetime, recuperacion_dias: float) -> List[tuple]:
    """Qué hacer con la alerta de una zona tras una evaluación. Pura.
    `alerta` = {"nivel", "bajoDesde", "propuesta"} de la alerta abierta, o None."""
    if nivel in ("medio", "alto"):
        if alerta is None:
            return [("abrir", nivel)]
        acciones = []
        if nivel == "alto" and alerta["nivel"] == "medio":
            acciones.append(("agravar", nivel))
        if alerta.get("bajoDesde"):
            acciones.append(("sigue-en-riesgo", None))
        return acciones
    if alerta is None:
        return []
    if not alerta.get("bajoDesde"):
        return [("bajo-desde", iso(ahora))]
    if not alerta.get("propuesta") and ahora - fecha(alerta["bajoDesde"]) >= timedelta(days=recuperacion_dias):
        return [("proponer-cierre", None)]
    return []


class GemeloPatrimonial:
    def __init__(self, *, registro, series, publicador=None, capacidad: Callable[[str, dict, dict], dict],
                 parametros: Optional[Dict[str, Any]] = None, legajos_de: Optional[Callable[[str, str], List[str]]] = None,
                 recuperacion_dias: float = 7, reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.reg, self.series, self.pub = registro, series, publicador
        self.capacidad, self.parametros = capacidad, dict(parametros or {})
        self.legajos_de = legajos_de or (lambda t, d: [])
        self.recuperacion_dias, self.reloj = recuperacion_dias, reloj
        self.firmas = None                       # FirmasTemporal o FirmasDirectas (las pone quien arranca)
        self.ahora_sensores: Dict[tuple, dict] = {}
        self._lock = threading.Lock()

    # ---------- lecturas que llegan por el bus ----------
    def manejar(self, ev: dict) -> None:
        if ev["type"] != "zona.medicion":
            return
        t, zona, d = ev["tenant"], ev["subject"], ev["data"]
        self.series.anadir_tenant(t)
        self.series.guardar(t, zona, d["sensor"], d["observadoEn"], d["temperatura"], d["humedad"], "real")
        with self._lock:
            previo = self.ahora_sensores.get((t, zona, d["sensor"]))
            if not previo or previo["observadoEn"] <= d["observadoEn"]:
                self.ahora_sensores[(t, zona, d["sensor"])] = dict(d)

    def ahora(self, tenant: str, zona: str) -> List[dict]:
        with self._lock:
            return sorted((dict(v, sensor=k[2]) for k, v in self.ahora_sensores.items() if k[:2] == (tenant, zona)),
                          key=lambda x: x["sensor"])

    # ---------- catastro ----------
    def zonas(self, tenant: str) -> List[dict]:
        return sorted(self.reg.listar(tenant, "HeritageZone"), key=lambda z: z["id"])

    def zona(self, tenant: str, cod: str) -> dict:
        z = self.reg.leer(tenant, M.urn("HeritageZone", tenant, cod))
        if not z:
            raise KeyError(f"no hay ninguna zona {cod} en {tenant}")
        return z

    def _upsert(self, tenant: str, entidad: dict) -> None:
        estado = self.reg.crear(tenant, entidad)
        if estado == 409:
            estado = self.reg.anadir_atributos(tenant, entidad["id"], {k: x for k, x in entidad.items() if k not in ("id", "type")})
        if estado not in (201, 204, 207):
            raise RuntimeError(f"el catastro respondió {estado} al guardar {entidad['id']}")

    def alertas(self, tenant: str, zona: Optional[str] = None) -> List[dict]:
        xs = self.reg.listar(tenant, "ConservationAlert", limite=1000)
        if zona:
            xs = [a for a in xs if M.v(a, "refZone") == zona]
        return sorted(xs, key=lambda a: M.v(a, "detectedAt", ""), reverse=True)

    def alerta_abierta(self, tenant: str, zona: str) -> Optional[dict]:
        return next((a for a in self.alertas(tenant, zona) if M.v(a, "alertStatus") in ABIERTAS), None)

    def _publicar(self, tipo: str, tenant: str, subject: str, data: dict, clave: str) -> None:
        if not self.pub:
            return
        from sdk.eventos import nuevo_evento
        self.pub.publicar(nuevo_evento(tipo, id=str(uuid.uuid5(ESPACIO_IDS, f"{tipo}|{clave}")), tenant=tenant,
                                       subject=subject, source=f"/tenants/{tenant}/servicios/conservacion", data=data))

    def _legajos(self, tenant: str, zona: dict) -> List[str]:
        dep = M.v(zona, "refDeposito")
        try:
            return self.legajos_de(tenant, dep) if dep else []
        except Exception as e:  # noqa: BLE001  sin legajos no se pierde la alerta
            log.warning("no se pudieron buscar los legajos de %s: %s", dep, e)
            return []

    # ---------- histórico sintético y simulación ----------
    def preparar(self, tenant: str) -> List[str]:
        """Da de alta la institución en el gemelo y genera el histórico sintético de las zonas que no lo tienen."""
        self.series.anadir_tenant(tenant)
        hechas = []
        for z in self.zonas(tenant):
            if not self.series.tiene_sintetico(tenant, z["id"]):
                clima = {**C.CLIMA_POR_DEFECTO, **(M.v(z, "climateReference") or {})}
                n = self.series.guardar_muchas(tenant, z["id"], C.historico(clima, z["id"], self.reloj(), CALIBRACION_DIAS))
                log.info("histórico sintético de %s: %d horas", z["id"], n)
                hechas.append(z["id"])
        return hechas

    def simular(self, tenant: str, cod: str, perfil: str, dias: float) -> dict:
        """Reescribe los últimos `dias` días de la zona con un perfil (datos sintéticos) y la evalúa.
        Para la demo: lo que en la realidad tardaría días en verse, en un momento."""
        if perfil not in C.PERFILES:
            raise ValueError(f"perfil: {', '.join(C.PERFILES)}")
        if not 0 < dias <= 30:
            raise ValueError("dias: entre 0 y 30")
        z = self.zona(tenant, cod)
        if not self.series.tiene_sintetico(tenant, z["id"]):
            self.preparar(tenant)
        ahora = self.reloj()
        self.series.borrar(tenant, z["id"], desde=ahora - timedelta(days=dias))
        clima = {**C.CLIMA_POR_DEFECTO, **(M.v(z, "climateReference") or {})}
        semilla = f"{z['id']}|{perfil}|{iso(ahora)}"
        puntos = C.historico(clima, semilla, ahora, max(1, int(round(dias))), perfil, max(1, int(round(dias))))
        desde = ahora - timedelta(days=dias)
        self.series.guardar_muchas(tenant, z["id"], (p for p in puntos if fecha(p["t"]) >= desde))
        return self.evaluar_zona(tenant, z)

    # ---------- evaluación ----------
    def serie(self, tenant: str, zona: dict) -> dict:
        ahora = self.reloj()
        puntos = self.series.horaria(tenant, zona["id"], ahora - timedelta(days=CALIBRACION_DIAS), ahora + timedelta(hours=1))
        if len(puntos) < 2:
            raise RuntimeError(f"la zona {zona['id']} aún no tiene serie (¿falta preparar su histórico?)")
        return {"zona": zona["id"], "nombre": M.v(zona, "name", M.codigo(zona["id"])), "metodo": resumen_origen(puntos),
                "desde": puntos[0]["t"], "hasta": puntos[-1]["t"],
                "puntos": [{"t": p["t"], "temperatura": p["temperatura"], "humedad": p["humedad"]} for p in puntos]}

    def evaluar_zona(self, tenant: str, zona: dict) -> dict:
        ev = self.capacidad(tenant, self.serie(tenant, zona), self.parametros)
        ahora, cod = self.reloj(), M.codigo(zona["id"])
        ca = M.urn("ClimateAssessment", tenant, cod)
        self._upsert(tenant, {
            "id": ca, "type": "ClimateAssessment", "refZone": M.rel(zona["id"]), "riskLevel": M.prop(ev["nivel"]),
            "method": M.prop(ev["metodo"]), "dataOrigin": M.prop(ev.get("origenDatos", "historico")),
            "tmdTemp": M.prop(ev["temperatura"]["media"]), "tmdHumidity": M.prop(ev["humedad"]["media"]),
            "targetTemperature": M.prop(ev["temperatura"]["objetivo"]), "targetHumidity": M.prop(ev["humedad"]["objetivo"]),
            "deviationLast30d": M.prop(ev["desviacion30d"]), "fluctuationMaxRH2h": M.prop(ev["fluctuacionMaxHR2h"]),
            "cause": M.prop(ev["causa"]), "computedAt": M.prop({"@type": "DateTime", "@value": iso(ahora)})})
        self.series.guardar_evaluacion(tenant, zona["id"], ev)
        self._publicar("conservacion.evaluada", tenant, zona["id"], {
            "evaluacion": ca, "nombre": M.v(zona, "name", cod), "nivel": ev["nivel"], "metodo": ev["metodo"],
            "origenDatos": ev.get("origenDatos", "historico"), "desviacion30d": ev["desviacion30d"],
            "objetivoHumedad": ev["humedad"]["objetivo"], "objetivoTemperatura": ev["temperatura"]["objetivo"],
            "causa": ev["causa"]}, clave=f"{ca}|{iso(ahora)}")
        acciones = self._aplicar_alertas(tenant, zona, ev, ca, ahora)
        log.info("evaluada %s: %s (%s) %s", zona["id"], ev["nivel"], ev["causa"], acciones)
        return {"evaluacion": ev, "acciones": acciones}

    def _aplicar_alertas(self, tenant: str, zona: dict, ev: dict, ca: str, ahora: datetime) -> List[str]:
        abierta = self.alerta_abierta(tenant, zona["id"])
        estado = None if abierta is None else {"nivel": M.v(abierta, "riskLevel"), "bajoDesde": M.v(abierta, "lowSince"),
                                               "propuesta": M.v(abierta, "closureProposed", False)}
        hecho = []
        nombre = M.v(zona, "name", M.codigo(zona["id"]))
        for accion, valor in decidir(estado, ev["nivel"], ahora, self.recuperacion_dias):
            if accion == "abrir":
                previas = self.alertas(tenant, zona["id"])
                n = 1 + max([int(M.codigo(a["id"]).rsplit("-", 1)[-1]) for a in previas
                             if M.codigo(a["id"]).rsplit("-", 1)[-1].isdigit()] or [0])
                aid = M.urn("ConservationAlert", tenant, f"{M.codigo(zona['id'])}-{n}")
                self._upsert(tenant, {
                    "id": aid, "type": "ConservationAlert", "refZone": M.rel(zona["id"]), "refAssessment": M.rel(ca),
                    "severity": M.prop(SEVERIDAD[valor]), "riskLevel": M.prop(valor), "cause": M.prop(ev["causa"]),
                    "detectedAt": M.prop(iso(ahora)), "alertStatus": M.prop("activa"), "closureProposed": M.prop(False)})
                self._riesgo(tenant, zona, aid, "abierta", valor, ev["causa"], ca)
                if self.firmas:
                    self.firmas.abrir(tenant, aid)
                hecho.append(f"abierta {M.codigo(aid)}")
            elif accion == "agravar":
                self.reg.anadir_atributos(tenant, abierta["id"], {"severity": M.prop(SEVERIDAD[valor]),
                                                                   "riskLevel": M.prop(valor), "cause": M.prop(ev["causa"]),
                                                                   "refAssessment": M.rel(ca)})
                self._riesgo(tenant, zona, abierta["id"], "agravada", valor, ev["causa"], ca, clave=iso(ahora))
                hecho.append(f"agravada {M.codigo(abierta['id'])}")
            elif accion == "bajo-desde":
                self.reg.anadir_atributos(tenant, abierta["id"], {"lowSince": M.prop(valor)})
            elif accion == "sigue-en-riesgo":
                self.reg.anadir_atributos(tenant, abierta["id"], {"lowSince": M.prop(""), "closureProposed": M.prop(False)})
            elif accion == "proponer-cierre":
                self.reg.anadir_atributos(tenant, abierta["id"], {"closureProposed": M.prop(True)})
                self._riesgo(tenant, zona, abierta["id"], "propuesta-cierre", estado["nivel"],
                             f"{nombre} lleva {self.recuperacion_dias:g} días dentro de su microclima objetivo", ca)
                hecho.append(f"propuesto cerrar {M.codigo(abierta['id'])}")
        return hecho

    def _riesgo(self, tenant, zona, alerta, estado, nivel, causa, ca, por=None, cierre=None, clave=""):
        data = {"alerta": alerta, "estado": estado, "nivel": nivel, "causa": causa, "evaluacion": ca,
                "nombre": M.v(zona, "name", M.codigo(zona["id"]))}
        if por:
            data["por"] = por
        if cierre:
            data["cierre"] = cierre
        legajos = self._legajos(tenant, zona)
        if legajos:
            data["legajos"] = legajos
        self._publicar("conservacion.riesgo", tenant, zona["id"], data, clave=f"{alerta}|{estado}|{clave}")

    def evaluar_todo(self) -> Dict[str, Any]:
        """Lo que hace el proceso programado cada hora: todas las zonas de todas las instituciones con gemelo."""
        hechas, errores = 0, []
        for t in self.series.tenants():
            try:
                self.preparar(t)
                zonas = self.zonas(t)
            except Exception as e:  # noqa: BLE001
                errores.append(f"{t}: {e}")
                continue
            for z in zonas:
                try:
                    self.evaluar_zona(t, z)
                    hechas += 1
                except Exception as e:  # noqa: BLE001  una zona rota no para a las demás
                    errores.append(f"{z['id']}: {e}")
                    log.warning("no se pudo evaluar %s: %s", z["id"], e)
        compactadas = self.series.compactar()
        return {"zonas": hechas, "errores": errores, "compactadas": compactadas}

    # ---------- firmas de las personas (las llama el proceso de Temporal de cada alerta) ----------
    def _alerta(self, tenant: str, aid: str) -> tuple:
        a = self.reg.leer(tenant, aid)
        if not a:
            raise KeyError(f"no hay ninguna alerta {aid}")
        z = self.reg.leer(tenant, M.v(a, "refZone")) or {"id": M.v(a, "refZone")}
        return a, z

    def comprobar(self, tenant: str, aid: str, accion: str) -> None:
        a, _ = self._alerta(tenant, aid)
        estado = M.v(a, "alertStatus")
        if estado == "cerrada":
            raise Conflicto("la alerta ya está cerrada")
        if accion == "reconocer" and estado != "activa":
            raise Conflicto("la alerta ya está reconocida")

    def registrar_reconocimiento(self, tenant: str, aid: str, por: str) -> None:
        a, z = self._alerta(tenant, aid)
        if M.v(a, "alertStatus") != "activa":
            return  # repetido (Temporal reintenta): idempotente
        self.reg.anadir_atributos(tenant, aid, {"alertStatus": M.prop("reconocida"), "acknowledgedBy": M.prop(por),
                                                "acknowledgedAt": M.prop(iso(self.reloj()))})
        self._riesgo(tenant, z, aid, "reconocida", M.v(a, "riskLevel"), M.v(a, "cause"), M.v(a, "refAssessment"), por=por)

    def registrar_cierre(self, tenant: str, aid: str, por: str, causa: str) -> None:
        a, z = self._alerta(tenant, aid)
        if M.v(a, "alertStatus") == "cerrada":
            return
        self.reg.anadir_atributos(tenant, aid, {"alertStatus": M.prop("cerrada"), "closedBy": M.prop(por),
                                                "closureCause": M.prop(causa), "closedAt": M.prop(iso(self.reloj()))})
        self._riesgo(tenant, z, aid, "cerrada", M.v(a, "riskLevel"), M.v(a, "cause"), M.v(a, "refAssessment"),
                     por=por, cierre=causa)

    # ---------- lo que pinta la consola ----------
    def estado_zona(self, tenant: str, cod: str, dias: int = 7) -> dict:
        z = self.zona(tenant, cod)
        ahora = self.reloj()
        return {"zona": z["id"], "ahora": self.ahora(tenant, z["id"]),
                "serie": self.series.horaria(tenant, z["id"], ahora - timedelta(days=dias), ahora + timedelta(hours=1)),
                "evaluacion": self.series.evaluacion(tenant, z["id"]), "origenSeries": self.series.origen}


class FirmasDirectas:
    """Sin Temporal (tests, o Temporal caído al arrancar): la firma se registra en el momento."""

    def __init__(self, gemelo: GemeloPatrimonial):
        self.g = gemelo

    def abrir(self, tenant: str, aid: str) -> None:
        pass

    def reconocer(self, tenant: str, aid: str, por: str) -> None:
        self.g.comprobar(tenant, aid, "reconocer")
        self.g.registrar_reconocimiento(tenant, aid, por)

    def cerrar(self, tenant: str, aid: str, por: str, causa: str) -> None:
        self.g.comprobar(tenant, aid, "cerrar")
        self.g.registrar_cierre(tenant, aid, por, causa)
