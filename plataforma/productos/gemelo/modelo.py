"""Modelo del gemelo patrimonial en el catastro (NGSI-LD), con el vocabulario de contracts/contextos/gdp-v1.jsonld.

    HeritageBuilding ◄─refBuilding─ HeritageZone ◄─refZone─ HeritageElement
                                         ▲  ▲
                              refZone ───┘  └─── refZone  EnvironmentalSensor ◄─refDevice─ IndoorEnvironmentObserved
    ClimateAssessment ─refZone─► zona          ConservationAlert ─refZone / refAssessment─►

Todas las URN siguen la regla de la plataforma: urn:ngsi-ld:<Tipo>:<institución>:<código>.
Una zona de tipo «depósito» puede enlazar con el Deposito del gemelo del archivo (refDeposito): así hereda sus
cajas y legajos, y una alerta de la zona llega también al libro de cada legajo afectado.
"""
from typing import Any, Dict, List, Optional

TIPOS = ("HeritageBuilding", "HeritageZone", "HeritageElement", "EnvironmentalSensor", "IndoorEnvironmentObserved",
         "ClimateAssessment", "ConservationAlert")
TIPOS_ZONA = ("sala", "depósito", "capilla", "cubierta", "fachada", "otro")


def urn(tipo: str, tenant: str, codigo: str) -> str:
    return f"urn:ngsi-ld:{tipo}:{tenant}:{codigo}"


def codigo(urn_: str) -> str:
    return urn_.split(":")[-1]


def prop(v: Any, **extra) -> Dict[str, Any]:
    return {"type": "Property", "value": v, **extra}


def rel(obj: str) -> Dict[str, Any]:
    return {"type": "Relationship", "object": obj}


def v(entidad: Optional[dict], attr: str, defecto=None):
    """Valor de un atributo (formato normalizado o keyValues)."""
    if not entidad or attr not in entidad:
        return defecto
    a = entidad[attr]
    return a.get("value", a.get("object", defecto)) if isinstance(a, dict) else a


def observado(entidad: Optional[dict], attr: str) -> Optional[str]:
    a = (entidad or {}).get(attr)
    return a.get("observedAt") if isinstance(a, dict) else None


# ---------- entidades ----------
def edificio(tenant: str, cod: str, *, nombre: str, proteccion: str, ano: int, estilo: str,
             lon: float, lat: float) -> dict:
    return {"id": urn("HeritageBuilding", tenant, cod), "type": "HeritageBuilding", "name": prop(nombre),
            "protectionLevel": prop(proteccion), "yearOfConstruction": prop(ano), "architecturalStyle": prop(estilo),
            "location": {"type": "GeoProperty", "value": {"type": "Point", "coordinates": [lon, lat]}}}


def zona(tenant: str, cod: str, *, edificio_cod: str, nombre: str, tipo: str, materiales: List[str], area: float,
         clima: Dict[str, float], plano: Dict[str, float], deposito: Optional[str] = None) -> dict:
    if tipo not in TIPOS_ZONA:
        raise ValueError(f"zoneType: {', '.join(TIPOS_ZONA)}")
    e = {"id": urn("HeritageZone", tenant, cod), "type": "HeritageZone", "name": prop(nombre), "zoneType": prop(tipo),
         "dominantMaterials": prop(materiales), "areaSqm": prop(area), "climateReference": prop(clima),
         "planPosition": prop(plano), "refBuilding": rel(urn("HeritageBuilding", tenant, edificio_cod))}
    if deposito:
        e["refDeposito"] = rel(deposito)
    return e


def elemento(tenant: str, cod: str, *, zona_cod: str, nombre: str, tipo: str, material: str, estado: str,
             inspeccion: str) -> dict:
    return {"id": urn("HeritageElement", tenant, cod), "type": "HeritageElement", "name": prop(nombre),
            "elementType": prop(tipo), "material": prop(material), "conditionStatus": prop(estado),
            "lastInspection": prop(inspeccion), "refZone": rel(urn("HeritageZone", tenant, zona_cod))}


def sensor(tenant: str, cod: str, *, zona_cod: str, nombre: str, x: float, y: float) -> List[dict]:
    """El sensor y su observación (una por sensor: se actualiza en cada lectura y el catastro guarda el historial)."""
    z = urn("HeritageZone", tenant, zona_cod)
    s = {"id": urn("EnvironmentalSensor", tenant, cod), "type": "EnvironmentalSensor", "name": prop(nombre),
         "deviceCategory": prop(["temperatura", "humedad"]), "serialNumber": prop(f"SIM-{tenant[:6].upper()}-{cod}"),
         "operStatus": prop("instalado"), "planPosition": prop({"x": x, "y": y}), "refZone": rel(z)}
    o = {"id": urn("IndoorEnvironmentObserved", tenant, cod), "type": "IndoorEnvironmentObserved",
         "refDevice": rel(s["id"]), "refZone": rel(z)}
    return [s, o]


def lectura_attrs(t: float, h: float, cuando: str) -> dict:
    return {"temperature": prop(t, unitCode="CEL", observedAt=cuando),
            "relativeHumidity": prop(h, unitCode="P1", observedAt=cuando),
            "dateObserved": prop({"@type": "DateTime", "@value": cuando})}


# ---------- el inmueble de ejemplo ----------
def inmueble_ejemplo(tenant: str, depositos: Optional[Dict[str, str]] = None) -> List[dict]:
    """Un inmueble piloto con 4 zonas, 3 elementos y 6 sensores. `depositos` = {"D1": urn, "D2": urn} enlaza las
    zonas de depósito con los Deposito del gemelo del archivo, si la institución los tiene."""
    depositos = depositos or {}
    ents = [edificio(tenant, "B01", nombre="Edificio histórico del archivo", proteccion="BIC (Bien de Interés Cultural)",
                     ano=1786, estilo="Neoclásico", lon=-3.70379, lat=40.41678)]
    zonas = [
        ("Z01", "Sala de lectura", "sala", ["madera", "papel"], 140,
         {"temperatura": 20.0, "humedad": 50.0, "amplitudTemperatura": 2.5, "amplitudHumedad": 6.0},
         {"x": 4, "y": 4, "w": 44, "h": 26}, None),
        ("Z02", "Depósito 1 · sótano", "depósito", ["papel", "cartón"], 95,
         {"temperatura": 15.5, "humedad": 61.0, "amplitudTemperatura": 2.0, "amplitudHumedad": 5.0},
         {"x": 52, "y": 4, "w": 44, "h": 26}, depositos.get("D1")),
        ("Z03", "Depósito 2 · planta primera", "depósito", ["pergamino", "papel"], 80,
         {"temperatura": 19.0, "humedad": 48.0, "amplitudTemperatura": 3.0, "amplitudHumedad": 8.0},
         {"x": 52, "y": 34, "w": 44, "h": 22}, depositos.get("D2")),
        ("Z04", "Capilla", "capilla", ["madera policromada", "piedra"], 120,
         {"temperatura": 16.0, "humedad": 58.0, "amplitudTemperatura": 4.0, "amplitudHumedad": 9.0},
         {"x": 4, "y": 34, "w": 44, "h": 22}, None),
    ]
    for cod, nombre, tipo, mat, area, clima, plano, dep in zonas:
        ents.append(zona(tenant, cod, edificio_cod="B01", nombre=nombre, tipo=tipo, materiales=mat, area=area,
                         clima=clima, plano=plano, deposito=dep))
    ents += [
        elemento(tenant, "E01", zona_cod="Z04", nombre="Retablo mayor", tipo="retablo", material="madera policromada",
                 estado="estable con fisuras", inspeccion="2026-03-12"),
        elemento(tenant, "E02", zona_cod="Z02", nombre="Protocolos notariales (s. XVII)", tipo="fondo documental",
                 material="papel", estado="bueno", inspeccion="2026-05-20"),
        elemento(tenant, "E03", zona_cod="Z03", nombre="Pergaminos medievales", tipo="fondo documental",
                 material="pergamino", estado="frágil", inspeccion="2026-02-03"),
    ]
    for cod, zc, nombre, x, y in [("S01", "Z01", "Sala · mesa central", 26, 17), ("S02", "Z02", "Sótano · pasillo A", 64, 19),
                                  ("S03", "Z02", "Sótano · pasillo B", 86, 22), ("S04", "Z03", "Planta 1ª · armarios", 74, 47),
                                  ("S05", "Z04", "Capilla · retablo", 30, 45), ("S06", "Z04", "Capilla · nave", 14, 50)]:
        ents += sensor(tenant, cod, zona_cod=zc, nombre=nombre, x=x, y=y)
    return ents
