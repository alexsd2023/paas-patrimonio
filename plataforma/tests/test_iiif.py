"""La sala de lectura: ingesta con identidad, manifiesto IIIF y ficha en el catastro (sin red)."""
import io

from fastapi.testclient import TestClient
from PIL import Image

from sdk.contratos import validar
from sdk.identidad import Identidad, NoAutorizado
from services.iiif.app import crear_app
from services.iiif.iiif import info_json
from services.puente.app import a_evento

PUBLICO = "http://servidor:9080"


class Verif:
    P = {"tok-ortega": Identidad("m.ortega", "archivo-villanueva", ["archivera"]),
         "tok-paleo": Identidad("paleografa-test", "archivo-villanueva", ["paleografa"])}

    def verificar(self, t):
        if t not in self.P:
            raise NoAutorizado(401, "no")
        return self.P[t]


class RegistroFalso:
    def __init__(self):
        self.fichas = {}

    def leer(self, tenant, i):
        return self.fichas.get((tenant, i))

    def crear(self, tenant, ficha):
        self.fichas[(tenant, ficha["id"])] = ficha
        return 201


def folio(n, w=1200, h=1600):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (235, 225, 200)).save(b, "PNG")
    return ("imagenes", (f"f{n}.png", b.getvalue(), "image/png"))


def cliente(tmp_path):
    reg = RegistroFalso()
    return TestClient(crear_app(datos=str(tmp_path), publico=PUBLICO, registro=reg, verificador=Verif())), reg


def subir(c, tok, sig="TEST-001", n=3):
    return c.post("/ingestas", data={"signatura": sig}, files=[folio(i) for i in range(1, n + 1)],
                  headers={"Authorization": f"Bearer {tok}"} if tok else {})


def test_solo_la_archivera_ingresa(tmp_path):
    c, _ = cliente(tmp_path)
    assert subir(c, None).status_code == 401
    assert subir(c, "tok-paleo").status_code == 403


def test_ingesta_completa(tmp_path):
    c, reg = cliente(tmp_path)
    r = subir(c, "tok-ortega")
    assert r.status_code == 202, r.text
    activo = r.json()["activo"]
    # el manifiesto: 3 lienzos, con servicio IIIF nivel 0
    man = c.get("/iiif/3/archivo-villanueva/TEST-001/manifest").json()
    assert man["id"] == f"{PUBLICO}/iiif/3/archivo-villanueva/TEST-001/manifest" == r.json()["manifiesto"]
    assert len(man["items"]) == 3
    info = c.get("/iiif/3/archivo-villanueva/TEST-001/1/info.json").json()
    assert (info["width"], info["height"], info["profile"]) == (1200, 1600, "level0")
    assert c.get("/iiif/3/archivo-villanueva/TEST-001/1/full/max/0/default.jpg").content[:2] == b"\xff\xd8"
    assert c.get("/iiif/3/archivo-villanueva/TEST-001/1/full/400,/0/default.jpg").status_code == 200
    assert c.get("/iiif/3/archivo-villanueva/TEST-001/1/full/123,/0/default.jpg").status_code == 501
    # la ficha inscrita produce, al pasar por el puente, una carta válida
    ficha = reg.fichas[("archivo-villanueva", activo)]
    ev = validar(a_evento(ficha, "archivo-villanueva"))
    assert ev["data"]["ingestadoPor"] == "m.ortega" and ev["data"]["imagenes"] == 3
    # repetir la signatura: 409
    assert subir(c, "tok-ortega").status_code == 409


def test_rechaza_lo_que_no_es_imagen(tmp_path):
    c, _ = cliente(tmp_path)
    r = c.post("/ingestas", data={"signatura": "TEST-002"}, files=[("imagenes", ("x.jpg", b"no soy imagen", "image/jpeg"))],
               headers={"Authorization": "Bearer tok-ortega"})
    assert r.status_code == 400


def test_info_json_nivel0():
    i = info_json("http://x/iiif/3/t/S/1", 1000, 2000)
    assert i["sizes"][0] == {"width": 400, "height": 800} and i["sizes"][-1] == {"width": 1000, "height": 2000}
