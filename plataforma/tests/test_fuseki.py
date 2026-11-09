"""El notario sobre Fuseki: las mismas consultas SPARQL, contra un Fuseki de mentira hecho con rdflib."""
import json
from pathlib import Path

from rdflib import Dataset

from services.procedencia.app import Registro, RegistroFuseki

EJ = Path(__file__).resolve().parents[1] / "contracts" / "ejemplos"
cargar = lambda n: json.loads((EJ / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
ACTIVO = "urn:ngsi-ld:ActivoPatrimonial:archivo-villanueva:TEST-001"


class FusekiFalso:
    """Ejecuta las peticiones SPARQL como lo haría Fuseki (dataset con grafos con nombre)."""

    def __init__(self):
        self.ds = Dataset()

    def __call__(self, servicio, campo, texto, acepta):
        if servicio == "update":
            self.ds.update(texto)
            return b""
        r = self.ds.query(texto)
        if r.type == "ASK":
            return json.dumps({"boolean": bool(r.askAnswer)}).encode()
        if r.type == "CONSTRUCT":
            return r.graph.serialize(format="turtle").encode()
        return r.serialize(format="json")


def libro():
    f = FusekiFalso()
    return RegistroFuseki("http://fuseki:3030", enviar=f), f


def test_mismas_actas_que_el_fichero(tmp_path):
    fus, _ = libro()
    loc = Registro(str(tmp_path / "p.ttl"))
    evs = [cargar(n) for n in ("legajo.ingestado", "htr.completado", "transcripcion.validada", "conservacion.alerta")]
    for e in evs:
        assert fus.anotar(e) and loc.anotar(e)
    a, b = fus.actas(ACTIVO), loc.actas(ACTIVO)
    assert [x["tipo"] for x in a] == ["ingreso", "htr", "validacion", "alerta-conservacion"]
    assert a == b
    assert "humedad 61.0" in a[-1]["detalle"]


def test_no_duplica_y_cada_institucion_en_su_grafo():
    fus, f = libro()
    ev = cargar("legajo.ingestado")
    assert fus.anotar(ev) is True and fus.anotar(ev) is False
    otro = dict(ev, id="99999999-9999-4999-8999-999999999999", tenant="otro-archivo",
                subject="urn:ngsi-ld:ActivoPatrimonial:otro-archivo:X-1",
                source="/tenants/otro-archivo/servicios/puente")
    fus.anotar(otro)
    grafos = {str(g.identifier) for g in f.ds.graphs() if len(g)}
    assert {"urn:paas:grafo:archivo-villanueva", "urn:paas:grafo:otro-archivo"} <= grafos
    assert fus.actas("urn:ngsi-ld:ActivoPatrimonial:otro-archivo:X-1")[0]["tipo"] == "ingreso"
    assert fus.tamano() > 0 and "Activity" in fus.turtle()
