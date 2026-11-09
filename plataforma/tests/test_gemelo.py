"""Gemelo digital: mediciones, umbrales con margen, alertas en el libro de cada legajo (sin red)."""
import json
from pathlib import Path

from sdk.contratos import validar
from sdk.registro import entidad_activo, entidad_caja, entidad_deposito, urn_deposito
from services.conservacion.app import Vigilante, evaluar
from services.procedencia.app import Registro as Libro
from services.puente.app import a_evento
from services.sensores.app import INVENTARIO_POR_DEFECTO, UMBRALES, Simulador

T = "archivo-villanueva"
DEP = urn_deposito(T, "D1")
EJ = Path(__file__).resolve().parents[1] / "contracts" / "ejemplos"


def deposito_con_lectura(temp, hum, cuando="2026-11-08T19:00:00Z"):
    e = entidad_deposito(T, "D1", nombre="Depósito 1 · sótano", umbrales=UMBRALES)
    e["temperatura"] = {"type": "Property", "value": temp, "observedAt": cuando}
    e["humedad"] = {"type": "Property", "value": hum, "observedAt": cuando}
    return e


def test_puente_traduce_la_lectura():
    ev = validar(a_evento(deposito_con_lectura(17.2, 46.0), T))
    assert ev["type"] == "deposito.medicion" and ev["data"]["umbrales"]["humedadMax"] == 55
    sin = entidad_deposito(T, "D1", nombre="x", umbrales=UMBRALES)
    assert a_evento(sin, T) is None   # recién inscrito, sin lecturas: no hay carta


def test_umbrales_con_margen():
    u = UMBRALES
    assert evaluar("humedad", 56, u, False)[:2] == (True, "alta")
    assert evaluar("humedad", 54, u, True)[0] is True     # aún dentro del margen: sigue en alerta
    assert evaluar("humedad", 52.5, u, True)[0] is False   # vuelve
    assert evaluar("temperatura", 12, u, False)[:2] == (True, "baja")


class RegistroMem:
    def __init__(self):
        self.e, self.attrs = {}, []

    def crear(self, t, x):
        self.e[(t, x["id"])] = x
        return 201

    def listar(self, t, tipo):
        return [x for (tt, _), x in self.e.items() if tt == t and x["type"] == tipo]

    def anadir_atributos(self, t, i, a):
        self.attrs.append((i, a))
        self.e[(t, i)].update(a)
        return 204


class Pub:
    def __init__(self):
        self.ev = []

    def publicar(self, e):
        self.ev.append(validar(e))


def test_alerta_con_los_legajos_del_deposito_y_acta_en_su_libro(tmp_path):
    reg, pub = RegistroMem(), Pub()
    reg.crear(T, entidad_deposito(T, "D1", nombre="Depósito 1 · sótano", umbrales=UMBRALES))
    reg.crear(T, entidad_caja(T, "C-001", "D1"))
    leg = entidad_activo(T, signatura="LEG-1", ark="ark:/99999/x", manifiesto="http://x/manifest",
                         imagenes=1, ingestado_por="m.ortega", caja="C-001")
    reg.crear(T, leg)
    v = Vigilante(reg, pub)
    for i, h in enumerate([46, 50, 58, 60, 54, 51]):
        v.manejar(a_evento(deposito_con_lectura(17.0, h, f"2026-11-08T19:00:{10 + i:02d}Z"), T))
    tipos = [e["type"] for e in pub.ev]
    assert tipos == ["conservacion.alerta", "conservacion.normalizada"]
    assert pub.ev[0]["data"]["legajos"] == [leg["id"]]
    assert reg.e[(T, DEP)]["estadoAmbiental"]["value"] == "ok"
    libro = Libro(str(tmp_path / "p.ttl"))
    for e in pub.ev:
        libro.anotar(e)
    actas = libro.actas(leg["id"])
    assert [a["tipo"] for a in actas] == ["alerta-conservacion", "fin-alerta"]
    assert "humedad 58" in actas[0]["detalle"] and "máx. 55" in actas[0]["detalle"]
    assert v.depositos(T)[0]["ultima"]["humedad"] == 51


def test_simulador_fuga_sube_la_humedad():
    sim = Simulador(RegistroMem(), INVENTARIO_POR_DEFECTO)
    sim.estado[(T, "D1")]["escenario"] = "fuga"
    hs = [sim.paso(T, "D1")["humedad"] for _ in range(6)]
    assert hs[-1] > 60 and sim.paso(T, "D2")["humedad"] < 50
