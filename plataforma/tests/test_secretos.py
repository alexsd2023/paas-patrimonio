"""Secretos de las capacidades: cifrados, por ámbito, resueltos al ejecutar y nunca devueltos por la API."""
import sqlite3

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sdk.identidad import Identidad, NoAutorizado
from sdk.servicios import leer_manifiesto
from services.catalogo.catalogo import Catalogo, descubrir
from services.catalogo.secretos import PLATAFORMA, Secretos

NER = descubrir()["ner-historico"]


class Verif:
    P = {"tok-a": Identidad("dir.a", "museo-a", ["admin-institucion"]),
         "tok-b": Identidad("dir.b", "museo-b", ["admin-institucion"]),
         "tok-u": Identidad("ana", "museo-a", ["archivera"]),
         "tok-op": Identidad("admin.paas", "paas", ["admin-paas"])}

    def verificar(self, t):
        if t not in self.P:
            raise NoAutorizado(401, "no")
        return self.P[t]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def test_el_ner_declara_su_token_como_secreto():
    assert NER.secretos == [{"nombre": "NER_TOKEN", "descripcion": NER.secretos[0]["descripcion"], "ambito": "ambos"}]
    # un externo con token_env sin declarar secretos también lo tiene (compatibilidad)
    m = leer_manifiesto({"id": "otro-externo", "nombre": "x", "resumen": "x", "autor": "x", "tipo": "tarea", "entrada": "texto",
                         "salida": "texto", "version": "1.0.0", "modo": "externo", "url": "http://x",
                         "externo": {"token_env": "X_TOKEN"}})
    assert [s["nombre"] for s in m.secretos] == ["X_TOKEN"]


def test_se_guardan_cifrados_y_se_resuelven_por_ambito(tmp_path, monkeypatch):
    monkeypatch.delenv("NER_TOKEN", raising=False)
    s = Secretos(str(tmp_path / "s.db"), Fernet.generate_key())
    assert s.valores(NER, "museo-a") == {}
    monkeypatch.setenv("NER_TOKEN", "del-entorno")
    assert s.valores(NER, "museo-a") == {"NER_TOKEN": "del-entorno"}
    s.poner(NER.id, PLATAFORMA, "NER_TOKEN", "de-la-plataforma", "admin.paas")
    s.poner(NER.id, "museo-a", "NER_TOKEN", "del-museo-a", "dir.a")
    assert s.valores(NER, "museo-a") == {"NER_TOKEN": "del-museo-a"}
    assert s.valores(NER, "museo-b") == {"NER_TOKEN": "de-la-plataforma"}
    with sqlite3.connect(tmp_path / "s.db") as c:  # en disco no aparece en claro
        assert all(b"museo-a" not in v and b"del-" not in v for (v,) in c.execute("select valor from secretos"))
    e = s.estado(NER, "museo-a")[0]
    assert e["listo"] and e["institucion"]["por"] == "dir.a" and e["entorno"] and "valor" not in e
    assert s.quitar(NER.id, "museo-a", "NER_TOKEN")
    assert s.valores(NER, "museo-a") == {"NER_TOKEN": "de-la-plataforma"}


def test_el_adaptador_recibe_el_secreto_de_su_institucion(tmp_path, monkeypatch):
    monkeypatch.delenv("NER_TOKEN", raising=False)
    vistos = []

    def responder(req):
        vistos.append(req.headers["authorization"])
        return httpx.Response(200, json=[{"Anotacion": "x", "entities": []}])
    s = Secretos(str(tmp_path / "s.db"), Fernet.generate_key())
    cat = Catalogo(descubrir(), http=httpx.Client(transport=httpx.MockTransport(responder)), secretos=s)
    s.poner(NER.id, "museo-a", "NER_TOKEN", "tok-museo-a", "dir.a")
    cat.ejecutar("ner-historico", {"texto": "x"}, {}, tenant="museo-a", roles=[])
    assert vistos == ["Bearer tok-museo-a"]


def _api(tmp_path):
    from services.catalogo.app import Indice, crear_app
    s = Secretos(str(tmp_path / "s.db"), Fernet.generate_key())
    app = crear_app(verificador=Verif(), catalogo=Catalogo(descubrir(), secretos=s), flujos=None,
                    indice=Indice(str(tmp_path / "f.db")))
    return TestClient(app), s


def test_api_de_secretos(tmp_path, monkeypatch):
    monkeypatch.delenv("NER_TOKEN", raising=False)
    c, s = _api(tmp_path)
    estado = c.get("/secretos", headers=_h("tok-a")).json()
    assert [x["servicio"] for x in estado] == ["ner-historico"] and not estado[0]["secretos"][0]["listo"]
    url = "/secretos/ner-historico/NER_TOKEN"
    assert c.put(url, json={"valor": "x"}, headers=_h("tok-u")).status_code == 403          # no es admin
    assert c.put(url, json={"valor": "x", "ambito": "plataforma"}, headers=_h("tok-a")).status_code == 403
    assert c.put("/secretos/ner-historico/OTRO", json={"valor": "x"}, headers=_h("tok-a")).status_code == 404
    assert c.put(url, json={"valor": " "}, headers=_h("tok-a")).status_code == 422
    r = c.put(url, json={"valor": "tok-a-secreto"}, headers=_h("tok-a"))
    assert r.status_code == 200 and "tok-a-secreto" not in r.text and r.json()["secretos"][0]["listo"]
    assert not c.get("/secretos", headers=_h("tok-b")).json()[0]["secretos"][0]["listo"]   # cada uno el suyo
    assert c.put(url, json={"valor": "comun", "ambito": "plataforma"}, headers=_h("tok-op")).status_code == 200
    assert c.get("/secretos", headers=_h("tok-b")).json()[0]["secretos"][0]["listo"]
    assert s.valores(NER, "museo-a") == {"NER_TOKEN": "tok-a-secreto"} and s.valores(NER, "museo-b") == {"NER_TOKEN": "comun"}
    assert "tok-a-secreto" not in c.get("/secretos", headers=_h("tok-a")).text
    assert c.delete(url, headers=_h("tok-a")).status_code == 200
    assert s.valores(NER, "museo-a") == {"NER_TOKEN": "comun"}
