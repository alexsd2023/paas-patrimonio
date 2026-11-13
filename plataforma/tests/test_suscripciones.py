"""Conectar el catastro de una institución al bus: crea (o recrea) sus suscripciones de Scorpio hacia el puente."""
import pytest

from services.suscripciones.crear import SUB_DEPOSITOS, SUB_ID, preparar


class CatastroFalso:
    def __init__(self, ya=(), falla=False):
        self.subs = {s: {"id": s} for s in ya}
        self.borradas, self.creadas, self.fichas, self.falla = [], [], [], falla

    def crear(self, t, e):
        self.fichas.append((t, e["id"]))

    def borrar(self, t, eid):
        pass

    def suscripcion(self, t, sid):
        return self.subs.get(sid)

    def _req(self, metodo, ruta, t):
        self.borradas.append(ruta)

    def crear_suscripcion(self, t, sub):
        if self.falla:
            return 500, "error"
        self.creadas.append((t, sub["id"], sub["notification"]["endpoint"]["uri"]))
        return 201, ""


def test_crea_las_dos_suscripciones_hacia_el_puente():
    r = CatastroFalso()
    hecho = preparar(r, "museo-naval")
    assert [(s, u.endswith("/ngsi-ld/notificaciones/museo-naval")) for _, s, u in r.creadas] == \
        [(SUB_ID, True), (SUB_DEPOSITOS, True)]
    assert r.fichas == [("museo-naval", "urn:ngsi-ld:Tenant:museo-naval")]   # el tenant existe antes de suscribirse
    assert all("creada" in h for h in hecho)


def test_es_idempotente_recrea_las_que_existian():
    r = CatastroFalso(ya=[SUB_ID])
    hecho = preparar(r, "museo-naval")
    assert len(r.borradas) == 1 and len(r.creadas) == 2 and "recreada" in hecho[0]


def test_si_scorpio_falla_lo_dice():
    with pytest.raises(RuntimeError, match="no se pudo crear"):
        preparar(CatastroFalso(falla=True), "museo-naval")
