"""Comprueba el catálogo de servicios y el motor de flujos a través de la puerta (APISIX).

    python scripts/catalogo_check.py

1. m.ortega ve el catálogo y usa el modernizador suelto.
2. Usa el NER de Lancaster (si el servidor tiene NER_TOKEN; si no, lo avisa y sigue).
3. Lanza el flujo «Modernizar y anotar» (o solo modernizar, si no hay NER) sobre un texto.
4. Una archivera no puede firmar; la paleógrafa sí. El flujo termina y queda en el catastro.
5. Otra institución no ve ese flujo.
6. Conectores: la archivera ve el de OAI-PMH y la paleógrafa no. Con OAI_ENDPOINT en .env, cosecha 20 registros.
"""
import json
import sys
import time

from _comun import env, esperar, http, token

API = env("API_URL")
TEXTO = ("Registraron Baltasar Perez y Ernando de Sanctiago vesinos de Sevilla\n"
         "En la villa de Villanueva a diez días del mes de março de mill e quinientos")


def trabajo(sid, entrada, parametros=None, usuario="m.ortega", segundos=150):
    est, t = http(f"{API}/api/v1/servicios/{sid}/trabajos", {"entrada": entrada, "parametros": parametros or {}},
                  token=token(usuario))
    if est != 202:
        sys.exit(f"✗ {sid}: la puerta respondió {est}: {t}")
    return esperar(f"trabajo de {sid}", lambda: http(f"{API}/api/v1/trabajos/{t['id']}", token=token(usuario))[1],
                   lambda x: isinstance(x, dict) and x.get("estado") in ("terminado", "error"), segundos,
                   pista="docker compose logs --tail 40 catalogo srv-modernizador-demo")


est, servicios = http(f"{API}/api/v1/servicios", token=token("m.ortega"))
if est != 200:
    sys.exit(f"✗ El catálogo respondió {est}: {servicios}\n  Pista: docker compose ps catalogo apisix")
ids = [s["id"] for s in servicios]
print(f"✓ Catálogo: {', '.join(ids)}")

t = trabajo("modernizador-demo", {"texto": TEXTO})
if t["estado"] != "terminado":
    sys.exit(f"✗ El modernizador falló: {t.get('error')}")
print(f"✓ Modernizador suelto: {len(t['salida']['cambios'])} cambios · «{t['salida']['texto'].splitlines()[1][:60]}…»")

hay_ner = False
if "ner-historico" in ids:
    print("  Llamando al NER de Lancaster (el Space puede tardar en despertar)…")
    t = trabajo("ner-historico", {"texto": TEXTO}, {"modelo": "ruler"})
    if t["estado"] == "terminado":
        hay_ner = True
        ents = ", ".join(f"{e['texto']} ({e['tipo']})" for e in t["salida"]["entidades"][:6])
        print(f"✓ NER: {len(t['salida']['entidades'])} entidades · {ents}")
    else:
        print(f"! NER no disponible: {t.get('error')}\n  (define NER_TOKEN en platform/.env del servidor y "
              "docker compose up -d catalogo). Sigo sin él.")

pasos = [{"servicio": "modernizador-demo"}, {"firma": "paleografa", "instrucciones": "Revisa la grafía"}]
if hay_ner:
    pasos += [{"servicio": "ner-historico"}, {"firma": "paleografa", "instrucciones": "Revisa las entidades"}]
receta = {"nombre": "Comprobación del catálogo", "entrada": "transcripcion", "pasos": pasos, "publicar": True}

est, r = http(f"{API}/api/v1/flujos/validar", {"receta": {**receta, "pasos": [{"servicio": "no-existe"}]}},
              token=token("m.ortega"))
assert est == 422, (est, r)
print("✓ Una receta con un servicio que no existe se rechaza antes de lanzarse")

est, r = http(f"{API}/api/v1/flujos", {"receta": receta, "entrada": {"documento": {"texto": TEXTO}}}, token=token("m.ortega"))
if est != 202:
    sys.exit(f"✗ No se pudo lanzar el flujo ({est}): {r}")
fid = r["id"]
print(f"✓ Flujo {fid} lanzado: {' → '.join(p.get('servicio') or 'firma ' + p['rol'] for p in r['plan']['pasos'])}")


def estado(usuario="m.ortega"):
    return http(f"{API}/api/v1/flujos/{fid}", token=token(usuario))[1]


for n in range(len(pasos) // 2):
    esperar(f"firma {n + 1} pendiente", estado, lambda e: isinstance(e, dict) and e.get("estado") == "esperando-firma",
            150, pista="docker compose logs --tail 40 catalogo")
    if n == 0:
        est, r = http(f"{API}/api/v1/flujos/{fid}/firmar", {"decision": "aprueba"}, token=token("m.ortega"))
        assert est == 409, (est, r)
        print("✓ La archivera no puede firmar un paso de paleógrafa (409)")
    est, r = http(f"{API}/api/v1/flujos/{fid}/firmar", {"decision": "aprueba", "comentario": "revisado"},
                  token=token("paleografa-test"))
    assert est == 200, (est, r)
    print(f"✓ Firma {n + 1}: {r['firmadoPor']}")
    time.sleep(1)

final = esperar("flujo terminado", estado, lambda e: isinstance(e, dict) and e.get("estado") in ("terminado", "error"),
                150, pista="docker compose logs --tail 40 catalogo")
if final["estado"] != "terminado":
    sys.exit(f"✗ El flujo terminó con error: {final.get('error')}")
print(f"✓ Flujo terminado → {final['resultado']}")

from sdk.registro import Registro  # noqa: E402
ent = Registro(env("SCORPIO_URL")).leer("archivo-villanueva", final["resultado"])
if not ent:
    sys.exit(f"✗ {final['resultado']} no está en el catastro")
proc = json.loads(ent["procedencia"]["value"])
print(f"✓ En el catastro como {ent['type']}: " + ", ".join(f"{x['servicio']} {x['version']}" for x in proc["servicios"])
      + " · firmas: " + ", ".join(x["usuario"] for x in proc["firmas"]))

est, _ = http(f"{API}/api/v1/flujos/{fid}", token=token("p.otro"))
assert est == 404, est
print("✓ Otra institución no ve el flujo (404)")
# ---------- capa Conectores ----------
import os  # noqa: E402
est, cons = http(f"{API}/api/v1/conectores", token=token("m.ortega"))
assert est == 200, (est, cons)
print(f"✓ Conectores disponibles para la archivera: {', '.join(c['id'] for c in cons)}")
est, _ = http(f"{API}/api/v1/conectores/oai-pmh", token=token("paleografa-test"))
assert est == 403, est
print("✓ La paleógrafa no puede usar el conector OAI-PMH (403)")
oai = os.environ.get("OAI_ENDPOINT")
if not oai:
    print("! Para probar una cosecha real, pon OAI_ENDPOINT=<dirección OAI-PMH> en plataforma/.env")
else:
    est, r = http(f"{API}/api/v1/conectores/oai-pmh/configuracion", {"endpoint": oai, "maximo": 20},
                  token=token("m.ortega"), metodo="PUT")
    assert est == 200, (est, r)
    est, r = http(f"{API}/api/v1/conectores/oai-pmh/ejecuciones", {}, token=token("m.ortega"))
    assert est == 202, (est, r)
    e = esperar("cosecha OAI-PMH", lambda: http(f"{API}/api/v1/ejecuciones/{r['id']}", token=token("m.ortega"))[1],
                lambda x: isinstance(x, dict) and x.get("estado") != "en-curso", 180, pista="docker compose logs --tail 40 catalogo")
    if e["estado"] != "terminada":
        sys.exit(f"✗ La cosecha falló: {e.get('error')}")
    res = e["resumen"]
    print(f"✓ Cosecha de {oai}: {res['nuevos']} nuevos, {res['actualizados']} actualizados, {res['borrados']} borrados")
    for m in res.get("muestra", [])[:3]:
        print(f"    · {m['titulo'][:80]}")

print("\nCapacidades, flujos y conectores completados. En la consola: /panel/servicios, /panel/recetas y /panel/conectores")
