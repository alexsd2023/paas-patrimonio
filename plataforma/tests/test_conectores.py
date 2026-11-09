"""Conectores: manifiesto, configuración por institución y la cosecha OAI-PMH (sin red)."""
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from conectores.oai_pmh.conector import ErrorOAI, leer_pagina, urn_registro
from sdk.conectores import ConectorInvalido, ConfiguracionInvalida, leer_manifiesto
from services.catalogo.conectores import Conectores, descubrir

CAB = '<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><responseDate>2026-11-09T10:00:00Z</responseDate>'
REC = ('<record><header{st}><identifier>{i}</identifier><datestamp>2026-01-0{n}</datestamp><setSpec>legajos</setSpec></header>'
       '{md}</record>')
MD = ('<metadata><oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
      '<dc:title>{t}</dc:title><dc:creator>Escribano de Villanueva</dc:creator><dc:creator>Juan de Ayala</dc:creator>'
      '<dc:date>1570</dc:date><dc:type>Text</dc:type><dc:identifier>https://repo.example/{n}</dc:identifier>'
      '<dc:description>  Protocolo   notarial </dc:description></oai_dc:dc></metadata>')


def pagina(regs, token=None, total=3):
    cuerpo = "".join(REC.format(st=' status="deleted"' if b else "", i=f"oai:repo:{n}", n=n,
                                md="" if b else MD.format(t=f"Legajo {n}", n=n)) for n, b in regs)
    tok = f'<resumptionToken completeListSize="{total}">{token}</resumptionToken>' if token else '<resumptionToken completeListSize="3"/>'
    return (CAB + f"<ListRecords>{cuerpo}{tok}</ListRecords></OAI-PMH>").encode()


def repo(peticiones):
    def responder(req: httpx.Request):
        peticiones.append(dict(req.url.params))
        if req.url.params.get("resumptionToken") == "p2":
            return httpx.Response(200, content=pagina([(3, False)]))
        if req.url.params.get("set") == "vacio":
            return httpx.Response(200, content=(CAB + '<error code="noRecordsMatch">nada</error></OAI-PMH>').encode())
        return httpx.Response(200, content=pagina([(1, False), (2, True)], token="p2"))
    return httpx.Client(transport=httpx.MockTransport(responder))


class Reg:
    def __init__(self):
        self.e = {}

    def crear(self, t, e):
        if (t, e["id"]) in self.e:
            return 409
        self.e[(t, e["id"])] = dict(e)
        return 201

    def anadir_atributos(self, t, i, attrs):
        self.e[(t, i)].update(attrs)
        return 204

    def listar(self, t, tipo, limite=200):
        return [e for (tt, _), e in self.e.items() if tt == t and e["type"] == tipo][:limite]


def test_leer_una_pagina_oai():
    p = leer_pagina(pagina([(1, False), (2, True)], token="p2"))
    assert p["token"] == "p2" and p["total"] == 3
    r = p["registros"][0]
    assert r["titulo"] == "Legajo 1" and r["creadores"] == ["Escribano de Villanueva", "Juan de Ayala"]
    assert r["descripcion"] == "Protocolo notarial" and r["conjuntos"] == ["legajos"]
    assert p["registros"][1]["borrado"]
    with pytest.raises(ErrorOAI, match="badArgument"):
        leer_pagina((CAB + '<error code="badArgument">mal</error></OAI-PMH>').encode())
    with pytest.raises(ErrorOAI, match="no es XML"):
        leer_pagina(b"<html>")


def test_manifiesto_y_configuracion():
    c = descubrir()["oai-pmh"]
    assert c.sentido == "entrada" and c.escribe == ["RegistroCatalografico"]
    assert c.validar_configuracion({"endpoint": "https://repo.example/oai", "maximo": "50"})["maximo"] == 50
    with pytest.raises(ConfiguracionInvalida) as e:
        c.validar_configuracion({"endpoint": "ftp://x", "maximo": 0, "otro": 1})
    assert "desconocidos" in str(e.value)
    with pytest.raises(ConfiguracionInvalida) as e:
        c.validar_configuracion({"maximo": 0})
    assert "falta endpoint" in str(e.value) and "maximo" in str(e.value)
    with pytest.raises(ConectorInvalido):
        leer_manifiesto({"id": "X", "sentido": "ambos"})


def test_cosecha_completa_e_idempotente(tmp_path):
    peticiones, reg = [], Reg()
    cs = Conectores(descubrir(), reg, str(tmp_path / "c.db"), http=repo(peticiones))
    with pytest.raises(ConfiguracionInvalida, match="configura"):
        cs.lanzar("oai-pmh", "archivo-villanueva", "m.ortega", en_hilo=False)
    cs.configurar("oai-pmh", "archivo-villanueva", "m.ortega", {"endpoint": "https://repo.example/oai", "conjunto": "legajos"})
    cs.lanzar("oai-pmh", "archivo-villanueva", "m.ortega", en_hilo=False)
    e = cs.ejecuciones("oai-pmh", "archivo-villanueva")[0]
    assert e["estado"] == "terminada"
    assert {k: e["resumen"][k] for k in ("nuevos", "actualizados", "borrados", "paginas")} == \
        {"nuevos": 2, "actualizados": 0, "borrados": 1, "paginas": 2}
    assert peticiones[0] == {"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": "legajos"}
    assert peticiones[1] == {"verb": "ListRecords", "resumptionToken": "p2"}
    ent = reg.e[("archivo-villanueva", urn_registro("archivo-villanueva", "oai:repo:1"))]
    assert ent["titulo"]["value"] == "Legajo 1" and ent["creadores"]["value"] == "Escribano de Villanueva | Juan de Ayala"
    cs.lanzar("oai-pmh", "archivo-villanueva", "m.ortega", en_hilo=False)  # otra vez: actualiza, no duplica
    assert cs.ejecuciones("oai-pmh", "archivo-villanueva")[0]["resumen"]["actualizados"] == 2
    assert len(reg.listar("archivo-villanueva", "RegistroCatalografico")) == 2
    assert cs.ejecuciones("oai-pmh", "otro-archivo") == [] and cs.configuracion("oai-pmh", "otro-archivo") is None


def test_maximo_y_errores(tmp_path):
    reg = Reg()
    cs = Conectores(descubrir(), reg, str(tmp_path / "c.db"), http=repo([]))
    cs.configurar("oai-pmh", "t", "u", {"endpoint": "https://repo.example/oai", "maximo": 1})
    cs.lanzar("oai-pmh", "t", "u", en_hilo=False)
    r = cs.ejecuciones("oai-pmh", "t")[0]["resumen"]
    assert r["nuevos"] == 1 and r["incompleta"]
    cs.configurar("oai-pmh", "t", "u", {"endpoint": "https://repo.example/oai", "conjunto": "vacio"})
    cs.lanzar("oai-pmh", "t", "u", en_hilo=False)
    assert cs.ejecuciones("oai-pmh", "t")[0]["resumen"]["nuevos"] == 0


def test_api_de_conectores(tmp_path):
    from services.catalogo.app import Indice, crear_app
    from services.catalogo.catalogo import Catalogo, descubrir as servicios
    from test_catalogo import FlujosFalsos, Verif
    reg = Reg()
    cs = Conectores(descubrir(), reg, str(tmp_path / "c.db"), http=repo([]))
    c = TestClient(crear_app(verificador=Verif(), catalogo=Catalogo(servicios()), flujos=FlujosFalsos(),
                             indice=Indice(str(tmp_path / "f.db")), conectores=cs))
    h = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
    assert c.get("/conectores", headers=h("tok-p")).json() == []           # la paleógrafa no tiene acceso
    assert c.get("/conectores/oai-pmh", headers=h("tok-p")).status_code == 403
    lista = c.get("/conectores", headers=h("tok-o")).json()
    assert lista[0]["id"] == "oai-pmh" and not lista[0]["configurado"]
    assert c.post("/conectores/oai-pmh/ejecuciones", headers=h("tok-o")).status_code == 409
    assert c.put("/conectores/oai-pmh/configuracion", json={"endpoint": "nada"}, headers=h("tok-o")).status_code == 422
    assert c.put("/conectores/oai-pmh/configuracion", json={"endpoint": "https://repo.example/oai"},
                 headers=h("tok-o")).status_code == 200
    eid = c.post("/conectores/oai-pmh/ejecuciones", headers=h("tok-o")).json()["id"]
    for _ in range(100):
        e = c.get(f"/ejecuciones/{eid}", headers=h("tok-o")).json()
        if e["estado"] != "en-curso":
            break
        time.sleep(0.02)
    assert e["estado"] == "terminada" and e["resumen"]["nuevos"] == 2
    regs = c.get("/registros/RegistroCatalografico", headers=h("tok-o")).json()
    assert sorted(r["titulo"] for r in regs) == ["Legajo 1", "Legajo 3"]
    assert c.get("/registros/ActivoPatrimonial", headers=h("tok-o")).status_code == 404  # no lo escribe ningún conector
    assert c.get(f"/ejecuciones/{eid}", headers=h("tok-x")).status_code == 404
