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


SUB_DEPOSITOS = "urn:ngsi-ld:Subscription:puente-depositos"


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


def suscripcion_depositos(tenant: str) -> dict:
    """Gemelo digital: cada lectura nueva de un depósito (→ deposito.medicion).
    Solo vigila temperatura y humedad: los cambios de estado que escribe conservación no avisan."""
    return {
        "id": SUB_DEPOSITOS,
        "type": "Subscription",
        "description": "Avisa al puente de cada lectura de los sensores de un depósito",
        "entities": [{"type": "Deposito"}],
        "watchedAttributes": ["temperatura", "humedad"],
        "notification": {
            "endpoint": {"uri": f"{PUENTE}/ngsi-ld/notificaciones/{tenant}", "accept": "application/json"},
        },
    }


SUSCRIPCIONES_PUENTE = [(SUB_ID, suscripcion), (SUB_DEPOSITOS, suscripcion_depositos)]


def preparar(reg: Registro, t: str) -> list:
    """Deja el catastro de la institución `t` listo y conectado al bus. Idempotente.
    Lo usan el arranque (instituciones fijas) y el alta de una institución nueva (services/instituciones)."""
    hecho = []
    # 1 · El tenant existe (inscribir y borrar una ficha de marca lo crea si hacía falta)
    marca = {"id": f"urn:ngsi-ld:Tenant:{t}", "type": "Tenant"}
    reg.crear(t, marca)
    reg.borrar(t, marca["id"])
    for sub_id, hacer in SUSCRIPCIONES_PUENTE:
        # 2 · Borrar la suscripción anterior, si la había
        existia = reg.suscripcion(t, sub_id) is not None
        if existia:
            reg._req("DELETE", f"{SUSCRIPCIONES}/{urllib.parse.quote(sub_id, safe='')}", t)
        # 3 · Crearla de nuevo
        estado, cuerpo = reg.crear_suscripcion(t, hacer(t))
        if estado not in (201, 204):
            raise RuntimeError(f"{t}: no se pudo crear {sub_id} ({estado}): {cuerpo}")
        hecho.append(f"✓ {t}: {sub_id.split(':')[-1]} {'recreada' if existia else 'creada'}")
    return hecho


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
        try:
            for linea in preparar(reg, t):
                print(linea, flush=True)
        except RuntimeError as e:
            print(f"✗ {e}", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
