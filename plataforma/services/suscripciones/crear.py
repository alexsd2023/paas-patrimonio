"""Al arrancar la plataforma: crea en el catastro la suscripción que avisa al puente.

Una por tenant. Se ejecuta una vez y termina. En cada arranque:
  1. espera a que Scorpio responda y le da unos segundos más para terminar de arrancar;
  2. se asegura de que el tenant existe (una suscripción creada antes que su tenant
     queda registrada pero nunca avisa: lo vimos con el diagnóstico);
  3. borra la suscripción si existía y la vuelve a crear, así se repara sola.
"""
import os
import sys
import time
import urllib.parse

from sdk.registro import SUSCRIPCIONES, Registro

SCORPIO = os.environ.get("SCORPIO_URL", "http://scorpio:9090")
PUENTE = os.environ.get("PUENTE_INTERNO", "http://puente:8080")
TENANTS = [t.strip() for t in os.environ.get("TENANTS", "archivo-villanueva").split(",") if t.strip()]
SUB_ID = "urn:ngsi-ld:Subscription:puente-activos"
MARGEN_ARRANQUE = int(os.environ.get("MARGEN_ARRANQUE", "20"))


def suscripcion(tenant: str) -> dict:
    return {
        "id": SUB_ID,
        "type": "Subscription",
        "description": "Avisa al puente de cada ActivoPatrimonial inscrito (→ legajo.ingestado)",
        "entities": [{"type": "ActivoPatrimonial"}],
        "notification": {
            "endpoint": {"uri": f"{PUENTE}/ngsi-ld/notificaciones/{tenant}", "accept": "application/json"},
        },
    }


def main() -> int:
    reg = Registro(SCORPIO)
    print(f"Esperando al catastro en {SCORPIO}…", flush=True)
    fin = time.time() + 240
    while not reg.disponible():
        if time.time() > fin:
            print("✗ El catastro no responde en 4 min", flush=True)
            return 1
        time.sleep(3)

    print(f"Catastro arriba; espero {MARGEN_ARRANQUE} s a que termine de arrancar…", flush=True)
    time.sleep(MARGEN_ARRANQUE)

    for t in TENANTS:
        # 1 · El tenant existe (inscribir y borrar una ficha de marca lo crea si hacía falta)
        marca = {"id": f"urn:ngsi-ld:Tenant:{t}", "type": "Tenant"}
        reg.crear(t, marca)
        reg.borrar(t, marca["id"])
        # 2 · Borrar la suscripción anterior, si la había
        existia = reg.suscripcion(t, SUB_ID) is not None
        if existia:
            reg._req("DELETE", f"{SUSCRIPCIONES}/{urllib.parse.quote(SUB_ID, safe='')}", t)
        # 3 · Crearla de nuevo
        estado, cuerpo = reg.crear_suscripcion(t, suscripcion(t))
        if estado not in (201, 204):
            print(f"✗ {t}: no se pudo crear la suscripción ({estado}): {cuerpo}", flush=True)
            return 1
        print(f"✓ {t}: suscripción {'recreada' if existia else 'creada'} → {PUENTE}/ngsi-ld/notificaciones/{t}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
