"""Capacidad evaluacion-en15757: el microclima objetivo (EN 15757:2010) sobre series conocidas, sin red."""
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from capacidades.evaluacion_en15757.motor import evaluar, percentil, resolver_parametros
from productos.gemelo.clima import CLIMA_POR_DEFECTO, historico
from sdk.servicios import validar_documento

AHORA = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)


def serie(perfil="estable", dias_perfil=0, dias=395, zona="urn:ngsi-ld:HeritageZone:t:Z01"):
    return {"zona": zona, "metodo": "sintetico",
            "puntos": list(historico(CLIMA_POR_DEFECTO, zona, AHORA, dias, perfil, dias_perfil))}


def test_percentil_como_numpy():
    assert percentil([1, 2, 3, 4], 50) == 2.5 and percentil([5], 93) == 5 and percentil(range(101), 7) == 7


def test_una_zona_estable_es_riesgo_bajo_y_cumple_su_tipo():
    r = evaluar(serie(), {})
    validar_documento("evaluacion-climatica", r)
    assert r["nivel"] == "bajo" and r["metodo"] == "en15757" and r["origenDatos"] == "sintetico"
    h0, h1 = r["humedad"]["objetivo"]
    assert h1 - h0 >= 20 - 1e-9          # al menos ±10 puntos de humedad relativa (la norma)
    assert h0 < r["humedad"]["media"] < h1
    assert r["periodo"]["recienteDias"] == 30 and r["banda"] and "hMin" in r["banda"][0]


@pytest.mark.parametrize("dias,nivel", [(3, "medio"), (8, "alto")])
def test_una_desviacion_sostenida_sube_el_nivel(dias, nivel):
    r = evaluar(serie("desviacion", dias), {})
    assert r["nivel"] == nivel, r["causa"]
    assert "humedad" in r["causa"] and r["humedad"]["fuera30d"] > r["humedad"]["lineaBase"]


def test_una_fluctuacion_rapida_es_riesgo_alto_aunque_la_media_no_cambie():
    r = evaluar(serie("fluctuacion", 1), {})
    assert r["nivel"] == "alto" and r["fluctuacionMaxHR2h"] > 8 and "2 horas" in r["causa"]


def test_sin_un_ano_de_datos_usa_la_media_movil_de_toda_la_serie():
    assert evaluar(serie(dias=200), {})["nivel"] == "bajo"
    assert evaluar(serie("desviacion", 8, dias=200), {})["nivel"] == "alto"


def test_el_metodo_simplificado_sigue_disponible_y_ve_los_saltos():
    r = evaluar(serie("fluctuacion", 1), {"metodo": "simplificado"})
    assert r["metodo"] == "simplificado" and r["parametros"]["media_movil_dias"] == 7 and r["nivel"] == "alto"


def test_parametros_desde_la_consola_llegan_como_texto():
    p = resolver_parametros({"metodo": "en15757", "reciente_dias": "15", "minimo_hr": "", "percentil_bajo": None})
    assert p["reciente_dias"] == 15 and p["minimo_hr"] == 10 and p["percentil_bajo"] == 7
    with pytest.raises(ValueError):
        resolver_parametros({"percentil_bajo": 95, "percentil_alto": 90})
    with pytest.raises(ValueError):
        resolver_parametros({"metodo": "magia"})


def test_una_serie_corta_se_evalua_entera():
    r = evaluar(serie(dias=20), {})
    assert r["periodo"]["calibracionDias"] == r["periodo"]["recienteDias"] and r["nivel"] in ("bajo", "medio", "alto")


def test_la_capacidad_con_la_interfaz_estandar():
    from capacidades.evaluacion_en15757.app import app
    c = TestClient(app)
    assert c.get("/describir").json()["entrada"] == "serie-ambiental"
    tid = c.post("/trabajos", json={"entrada": serie(dias=120), "parametros": {"reciente_dias": 10}}).json()["id"]
    for _ in range(100):
        t = c.get(f"/trabajos/{tid}").json()
        if t["estado"] in ("terminado", "error"):
            break
        time.sleep(0.05)
    assert t["estado"] == "terminado", t
    assert t["salida"]["periodo"]["recienteDias"] == 10
    assert c.post("/trabajos", json={"entrada": {"zona": "x", "puntos": []}}).status_code == 422
