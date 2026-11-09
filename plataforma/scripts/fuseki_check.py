"""Parte 10 · el libro del notario en Fuseki, consultable con SPARQL.

Uso (desde plataforma/, con el venv activo):  python scripts/fuseki_check.py
"""
import json
import urllib.parse
import urllib.request
import uuid

from _comun import env, esperar, http  # noqa: I100
from sdk.registro import Registro, entidad_activo

FUSEKI, PROC = env("FUSEKI_URL"), env("PROCEDENCIA_URL")
T = "archivo-villanueva"
PREF = "PREFIX prov: <http://www.w3.org/ns/prov#>\nPREFIX paas: <https://paas-patrimonio.example/ns#>\n"


def sparql(q):
    req = urllib.request.Request(f"{FUSEKI}/paas/query", data=urllib.parse.urlencode({"query": PREF + q}).encode(),
                                 headers={"Accept": "application/sparql-results+json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return [{k: v["value"] for k, v in b.items()} for b in json.loads(r.read())["results"]["bindings"]]


estado, salud = http(f"{PROC}/salud")
if salud.get("almacen") != "fuseki":
    raise SystemExit(f"✗ El notario no está usando Fuseki: {salud}")
print(f"✓ El notario escribe en Fuseki ({salud['tripletas']} tripletas)")

# 1 · Un grafo por institución
filas = sparql("SELECT ?g (COUNT(DISTINCT ?a) AS ?actas) WHERE { GRAPH ?g { ?a a prov:Activity } } GROUP BY ?g ORDER BY ?g")
for f in filas:
    print(f"  · {f['g']}: {f['actas']} actas")

# 2 · Una pregunta que solo responde el grafo
print("\n¿Qué copias hizo cada modelo y quién las validó?")
filas = sparql("""
SELECT ?modelo ?copia ?validadaPor WHERE { GRAPH <urn:paas:grafo:archivo-villanueva> {
  ?hecha prov:wasAssociatedWith ?modelo . ?modelo a prov:SoftwareAgent .
  ?copia prov:wasGeneratedBy ?hecha .
  OPTIONAL { ?copia prov:wasAttributedTo ?validadaPor }
  FILTER(STRSTARTS(STR(?modelo), "urn:paas:modelo:"))
} } ORDER BY ?copia LIMIT 10""")
for f in filas:
    print(f"  · {f['modelo'].split(':')[-1]} → {f['copia'].split(':')[-1]} · "
          f"{'validada por ' + f['validadaPor'].split(':')[-1] if 'validadaPor' in f else 'sin validar'}")

# 3 · Un legajo nuevo llega al libro en Fuseki
SIG = f"TEST-{uuid.uuid4().hex[:6].upper()}"
ficha = entidad_activo(T, signatura=SIG, ark=f"ark:/99999/av-{SIG.lower()}", manifiesto=f"http://x/{SIG}/manifest",
                       imagenes=1, ingestado_por="m.ortega")
Registro(env("SCORPIO_URL")).crear(T, ficha)
esperar("El acta de ingreso llega a Fuseki", lambda: sparql(
    f"SELECT ?a WHERE {{ GRAPH <urn:paas:grafo:{T}> {{ ?a paas:sobre <{ficha['id']}> ; paas:tipoActa \"ingreso\" }} }}"),
        lambda v: len(v) == 1, 30, "docker compose logs --tail 30 procedencia fuseki")
print(f"\n✓ El ingreso de {SIG} está en el grafo de {T}")
print(f"Parte 10 completada: el libro del notario vive en Fuseki. Interfaz y SPARQL en {FUSEKI}")
