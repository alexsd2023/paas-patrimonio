"""Las herramientas de Ameyalli (Scriptorium) como capacidades del PaaS, contra un Ameyalli simulado que se
comporta como el real: posiciones por línea, el agente que rechaza su propia salida, Spaces dormidos."""
import json

import httpx
import pytest
import yaml

from capacidades._ameyalli import localizar
from sdk.servicios import validar_documento
from services.catalogo.catalogo import Catalogo, descubrir
from services.catalogo.recetas import planificar

HTR = ("En la cibdad de Sevylla a treze dlas del mes de março\n"
       "ante mi Johan Peres escrivano publico parescio Diego Ferrandez vezino de Sevylla\n")

CORREGIR = {"dlas": "dias"}
MODERNO = {"cibdad": "ciudad", "Sevylla": "Sevilla", "treze": "trece", "março": "marzo", "mi": "mí",
           "Johan": "Juan", "Peres": "Pérez", "escrivano": "escribano", "publico": "público",
           "parescio": "pareció", "Ferrandez": "Fernández", "vezino": "vecino"}
ENTIDADES = [("Sevilla", "Lugar"), ("Juan Pérez", "Persona"), ("escribano público", "Cargo"),
             ("Diego Fernández", "Persona")]


def _sustituir(texto, mapa):
    """Cambia palabras; «position» es la posición en el texto que recibe (como el modernizador real)."""
    cambios, out, base = [], [], 0
    for linea in texto.split("\n"):
        palabras, col = [], 0
        for p in linea.split(" "):
            if p in mapa:
                cambios.append({"original": p, "proposed": mapa[p], "type": "grafía", "reason": f"{p} → {mapa[p]}",
                                "position": base + col})
            col += len(p) + 1
            palabras.append(mapa.get(p, p))
        out.append(" ".join(palabras))
        base += len(linea) + 1
    return "\n".join(out), cambios


class Ameyalli:
    """Simula scriptorium-api: guarda lo que le piden y responde como la API real."""

    def __init__(self, clave=None):
        self.clave, self.peticiones, self.fallo = clave, [], None

    def __call__(self, req: httpx.Request):
        cuerpo = json.loads(req.content or b"{}")
        self.peticiones.append((req.url.path, cuerpo, req.headers.get("authorization")))
        if self.clave and req.headers.get("authorization") != f"Bearer {self.clave}":
            return httpx.Response(401, json={"detail": "The API key is missing or invalid"})
        if self.fallo:
            return httpx.Response(self.fallo, json={"detail": "Space dormido"})
        ruta = req.url.path
        if ruta.startswith("/reviewer/") or ruta == "/rag/correct":
            if ruta == "/reviewer/agent" and "Sevilla" in cuerpo["text"]:
                return httpx.Response(409, json={"detail": "modernisations detected"})
            t, c = _sustituir(cuerpo["text"], CORREGIR)
            return httpx.Response(200, json={"engine": ruta, "text": t.rstrip("\n"), "changes": c, "latency_ms": 5})
        if ruta == "/modernizer/modernize":
            t, c = _sustituir(cuerpo["text"], MODERNO)
            return httpx.Response(200, json={"engine": "modernizer", "text": t, "changes": c, "latency_ms": 5})
        if ruta == "/paleo-ner/map":
            return httpx.Response(200, json=self._mapa(cuerpo["paleographic"], cuerpo["modern"]))
        return httpx.Response(404, json={"detail": "Not Found"})

    @staticmethod
    def _mapa(paleo, moderno):
        """Como paleo-ner-app: posiciones DENTRO DE LA LÍNEA (no absolutas), en ambas versiones."""
        inverso = {v: k for k, v in MODERNO.items()}
        lp, ents = paleo.split("\n"), []
        for n, linea in enumerate(moderno.split("\n")):
            for txt, tipo in ENTIDADES:
                i = linea.find(txt)
                while i >= 0:
                    antiguo = " ".join(inverso.get(w, w) for w in txt.split(" "))
                    j = lp[n].find(antiguo) if n < len(lp) else -1
                    ents.append({"id": f"e{len(ents)}", "text": txt, "label": tipo, "fields": [], "line": n,
                                 "start": i, "end": i + len(txt),
                                 "paleographic": {"start": j, "end": j + len(antiguo), "text": antiguo,
                                                  "similarity": 0.8} if j >= 0 else None})
                    i = linea.find(txt, i + 1)
        return {"format": "line", "entities": ents, "mapped": 0, "unmatched": 0, "unresolved": []}


@pytest.fixture
def ameyalli(monkeypatch):
    for k in ("SCRIPTORIUM_API_KEY", "GROQ_API_KEY", "AMEYALLI_URL"):
        monkeypatch.delenv(k, raising=False)
    a = Ameyalli()
    return a, Catalogo(descubrir(), http=httpx.Client(transport=httpx.MockTransport(a)))


def _ej(cat, sid, doc, params=None, **kw):
    return cat.ejecutar(sid, doc, params or {}, tenant="museo-a", roles=["paleografa"], **kw)["salida"]


def test_estan_en_el_catalogo_y_la_receta_encaja():
    s = descubrir()
    assert {"corrector-htr", "modernizador-paleografico", "entidades-en-el-original"} <= set(s)
    plan = planificar(yaml.safe_load(open("flujos/edicion-anotada.yaml", encoding="utf-8")), Catalogo(s),
                      roles=["paleografa"], tenant="t")
    assert [(p.get("recibe"), p.get("entrega")) for p in plan["pasos"] if p["clase"] == "servicio"] == \
        [("transcripcion", "transcripcion"), ("transcripcion", "texto-modernizado"), ("texto-modernizado", "edicion-anotada")]
    assert plan["salida"] == "edicion-anotada"
    # la edición anotada sirve donde se pida una transcripción anotada (y un texto)
    from sdk.servicios import encaja
    assert encaja("edicion-anotada", "transcripcion-anotada") and encaja("edicion-anotada", "texto")


def test_la_receta_completa_de_punta_a_punta(ameyalli):
    a, cat = ameyalli
    corregida = _ej(cat, "corrector-htr", {"texto": HTR, "activo": "urn:legajo:1"}, {"motor": "mt5"})
    assert "treze dias" in corregida["texto"] and corregida["texto"].endswith("\n")
    assert corregida["correccion"]["motor"] == "mt5" and corregida["correccion"]["texto_htr"] == HTR
    moderna = _ej(cat, "modernizador-paleografico", corregida)
    assert moderna["original"] == corregida["texto"] and "Juan Pérez" in moderna["texto"]
    assert any(c["original"] == "escrivano" and c["moderno"] == "escribano" for c in moderna["cambios"])
    ed = _ej(cat, "entidades-en-el-original", moderna)
    validar_documento("edicion-anotada", ed)
    assert ed["texto"] == corregida["texto"] and ed["activo"] == "urn:legajo:1"
    # todas las entidades están exactamente donde dicen, en la grafía ORIGINAL
    for e in ed["entidades"]:
        assert ed["texto"][e["inicio"]:e["fin"]] == e["texto"]
    assert [(e["tipo"], e["texto"], e["moderno"]) for e in ed["entidades"]] == [
        ("Lugar", "Sevylla", "Sevilla"), ("Persona", "Johan Peres", "Juan Pérez"),
        ("Cargo", "escrivano publico", "escribano público"), ("Persona", "Diego Ferrandez", "Diego Fernández"),
        ("Lugar", "Sevylla", "Sevilla")]
    # las de la segunda línea venían con posiciones por línea: se han pasado a absolutas
    assert ed["entidades"][1]["inicio"] > HTR.index("\n")
    for e in ed["modernizado"]["entidades"]:
        assert ed["modernizado"]["texto"][e["inicio"]:e["fin"]] == e["texto"]
    assert [p for p, *_ in a.peticiones] == ["/reviewer/mt5", "/modernizer/modernize", "/paleo-ner/map"]


def test_motor_rag_y_el_agente_que_se_niega(ameyalli):
    a, cat = ameyalli
    _ej(cat, "corrector-htr", {"texto": HTR}, {"motor": "rag", "ejemplos_rag": 3})
    assert a.peticiones[-1][0] == "/rag/correct" and a.peticiones[-1][1]["top_k"] == 3
    with pytest.raises(Exception, match="prueba con otro motor"):
        _ej(cat, "corrector-htr", {"texto": "ciudad de Sevilla"}, {"motor": "agent"})


def test_claves_como_secretos(monkeypatch):
    from cryptography.fernet import Fernet
    from services.catalogo.secretos import PLATAFORMA, Secretos
    import tempfile, os
    for k in ("SCRIPTORIUM_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    a = Ameyalli(clave="clave-nsf")
    s = Secretos(os.path.join(tempfile.mkdtemp(), "s.db"), Fernet.generate_key())
    cat = Catalogo(descubrir(), http=httpx.Client(transport=httpx.MockTransport(a)), secretos=s)
    with pytest.raises(Exception, match="SCRIPTORIUM_API_KEY"):
        _ej(cat, "modernizador-paleografico", {"texto": "En Sevylla"})
    s.poner("modernizador-paleografico", PLATAFORMA, "SCRIPTORIUM_API_KEY", "clave-nsf", "admin.paas")
    _ej(cat, "modernizador-paleografico", {"texto": "En Sevylla"})
    assert "api_key" not in a.peticiones[-1][1]          # sin clave propia: usa la de Ameyalli
    assert set(a.peticiones[-1][1]) == {"text", "provider"}   # los campos vacíos no se envían
    s.poner("modernizador-paleografico", "museo-a", "GROQ_API_KEY", "gsk-del-museo", "dir.a")
    _ej(cat, "modernizador-paleografico", {"texto": "En Sevylla"}, {"reglas": [{"patron": "ç", "reemplazo": "z"}]})
    path, cuerpo, auth = a.peticiones[-1]
    assert auth == "Bearer clave-nsf" and cuerpo["api_key"] == "gsk-del-museo"
    assert cuerpo["rules"] == [{"pattern": "ç", "replacement": "z", "criterion": None, "is_regex": False, "active": True}]
    # los secretos opcionales no ponen la capacidad en rojo
    est = {x["nombre"]: x for x in s.estado(descubrir()["modernizador-paleografico"], "museo-b")}
    assert est["OPENROUTER_API_KEY"]["listo"] and est["OPENROUTER_API_KEY"]["opcional"]


def test_textos_largos_se_trocean_por_lineas(ameyalli):
    a, cat = ameyalli
    largo = HTR * 120                                       # ~16 000 caracteres
    m = _ej(cat, "modernizador-paleografico", {"texto": largo})
    assert len([p for p, *_ in a.peticiones if p == "/modernizer/modernize"]) == 2
    assert m["texto"].count("Juan Pérez") == 120 and m["original"] == largo
    assert all(m["original"][c["inicio"]:c["inicio"] + len(c["original"])] == c["original"] for c in m["cambios"])
    ed = _ej(cat, "entidades-en-el-original", {"texto": m["texto"] * 2, "original": largo * 2})
    assert len([p for p, *_ in a.peticiones if p == "/paleo-ner/map"]) >= 2
    assert len(ed["entidades"]) == 5 * 240
    assert all(ed["texto"][e["inicio"]:e["fin"]] == e["texto"] for e in ed["entidades"])


def test_un_space_dormido_da_un_error_que_se_entiende(ameyalli):
    a, cat = ameyalli
    a.fallo = 504
    with pytest.raises(Exception, match="despertar"):
        _ej(cat, "corrector-htr", {"texto": HTR})


def test_localizar_no_inventa():
    t = "Sevylla y Sevylla"
    assert localizar(t, "Sevylla", [10]) == (10, 17)        # la pista cuadra
    assert localizar(t, "Sevylla", [11]) == (10, 17)        # cerca: la más próxima
    assert localizar(t, "Sevilla", [0]) is None             # no está: no se marca


def test_un_error_largo_de_ameyalli_se_ve_por_el_final(ameyalli):
    a, cat = ameyalli
    traza = "Traceback (most recent call last):\n" + "  File x, line 1\n" * 200 + "KeyError: 'rules'"
    cat.http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"detail": traza})))
    with pytest.raises(Exception, match="KeyError: 'rules'"):
        _ej(cat, "modernizador-paleografico", {"texto": "En Sevylla"})
