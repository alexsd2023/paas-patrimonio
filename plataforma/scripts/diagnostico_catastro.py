"""Diagnóstico: ¿envía avisos el catastro (Scorpio)? ¿Depende del tenant?

Crea, en el tenant por defecto y en archivo-villanueva, una suscripción y una entidad
de prueba (tipo DiagPrueba, que el puente ignora) y mira si Scorpio intenta avisar.
El aviso apunta a /salud del puente, que no acepta POST: no importa que falle, solo
queremos ver si Scorpio LO INTENTA (timesSent / timesFailed). Al terminar lo borra todo.

Uso (desde plataforma/, con el venv activo):  python scripts/diagnostico_catastro.py
"""
import os
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

from sdk.registro import SUSCRIPCIONES, Registro  # noqa: E402
from services.suscripciones.crear import SUB_ID  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
reg = Registro(os.environ["SCORPIO_URL"])


def contadores(tenant, sub_id):
    s = reg.suscripcion(tenant, sub_id) or {}
    n = s.get("notification", {})
    return n.get("timesSent", 0) + n.get("timesFailed", 0), n


def probar(tenant):
    nombre = tenant or "(tenant por defecto)"
    k = uuid.uuid4().hex[:6]
    sub_id, ent_id = f"urn:ngsi-ld:Subscription:diag-{k}", f"urn:ngsi-ld:DiagPrueba:{k}"
    estado, cuerpo = reg.crear_suscripcion(tenant, {
        "id": sub_id, "type": "Subscription", "entities": [{"type": "DiagPrueba"}],
        "notification": {"endpoint": {"uri": "http://puente:8080/salud", "accept": "application/json"}}})
    if estado not in (201, 204):
        print(f"  {nombre}: no se pudo crear la suscripción de prueba ({estado}): {cuerpo}")
        return None
    time.sleep(2)
    reg.crear(tenant, {"id": ent_id, "type": "DiagPrueba", "valor": {"type": "Property", "value": 1}})
    fin, n, det = time.time() + 15, 0, {}
    while time.time() < fin:
        n, det = contadores(tenant, sub_id)
        if n:
            break
        time.sleep(1)
    reg.borrar(tenant, ent_id)
    reg._req("DELETE", f"{SUSCRIPCIONES}/{urllib.parse.quote(sub_id, safe='')}", tenant)
    print(f"  {nombre}: {'INTENTA avisar' if n else 'NO avisa'}  "
          f"(enviados {det.get('timesSent', 0)}, fallidos {det.get('timesFailed', 0)}, último fallo: {det.get('lastFailure', '—')})")
    return bool(n)


print("1 · Suscripción nueva + entidad nueva, en cada tenant:")
por_defecto = probar(None)
villanueva = probar("archivo-villanueva")

print("2 · La suscripción original del puente en archivo-villanueva:")
_, det = contadores("archivo-villanueva", SUB_ID)
print(f"  enviados {det.get('timesSent', 0)}, fallidos {det.get('timesFailed', 0)}")

print("\nDiagnóstico:")
if por_defecto is False and villanueva is False:
    print("  → Scorpio no envía avisos en ningún tenant: falla su sistema interno de avisos.")
elif por_defecto and villanueva is False:
    print("  → Avisa en el tenant por defecto pero no en archivo-villanueva: problema de Scorpio con los tenants.")
elif villanueva:
    print("  → Una suscripción nueva sí avisa: la original quedó mal porque se creó antes que el tenant.")
else:
    print("  → Resultado mixto: pásame toda la salida.")
