"""El cálculo de EN 15757:2010, sin red ni dependencias: funciones puras sobre listas.

Idea de la norma: los objetos orgánicos higroscópicos (madera, papel, pergamino, textil) se han adaptado al
clima en el que han vivido. El riesgo no es un valor absoluto, sino salirse de las fluctuaciones que ya han
soportado. Por eso el objetivo se calcula con el propio clima histórico de la zona:

  1. media móvil centrada de 30 días (el ciclo estacional);
  2. fluctuaciones a corto plazo = lectura − media;
  3. banda objetivo = media + [P7, P93] de las fluctuaciones, y al menos ±10 puntos de humedad relativa.

Para el periodo reciente, la referencia es la media del clima histórico en el mismo momento del año anterior,
si hay un año de calibración: así la propia excursión no desplaza su referencia. Si no lo hay, se usa la
media móvil de toda la serie, como en la norma.

El método «simplificado» es el de la versión 1.0 de la especificación: media de 7 días y la banda fija
[P10, P90] de la serie suavizada.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

HORA = timedelta(hours=1)
ANO = 365 * 24


def _fecha(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def percentil(xs: Sequence[float], p: float) -> float:
    """Percentil con interpolación lineal (como numpy por defecto)."""
    s = sorted(xs)
    if not s:
        raise ValueError("sin datos")
    k = (len(s) - 1) * p / 100
    i = int(k)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


def rejilla_horaria(puntos: List[dict]) -> Tuple[datetime, List[Optional[float]], List[Optional[float]]]:
    """Promedia por hora y deja huecos (None) donde no hay lecturas."""
    cubos: Dict[datetime, List[Tuple[float, float]]] = {}
    for p in puntos:
        h = _fecha(p["t"]).replace(minute=0, second=0, microsecond=0)
        cubos.setdefault(h, []).append((float(p["temperatura"]), float(p["humedad"])))
    inicio, fin = min(cubos), max(cubos)
    n = int((fin - inicio) / HORA) + 1
    t: List[Optional[float]] = [None] * n
    h: List[Optional[float]] = [None] * n
    for cuando, vs in cubos.items():
        i = int((cuando - inicio) / HORA)
        t[i] = sum(v[0] for v in vs) / len(vs)
        h[i] = sum(v[1] for v in vs) / len(vs)
    return inicio, t, h


def media_movil(xs: List[Optional[float]], medio_ancho: int, hasta: Optional[int] = None) -> List[Optional[float]]:
    """Media centrada en [i - medio_ancho, i + medio_ancho] con los valores disponibles (y solo hasta `hasta`)."""
    n = len(xs) if hasta is None else hasta
    suma, cuenta = [0.0], [0]
    for x in xs[:n]:
        suma.append(suma[-1] + (x or 0.0))
        cuenta.append(cuenta[-1] + (x is not None))
    out: List[Optional[float]] = []
    for i in range(n):
        a, b = max(0, i - medio_ancho), min(n, i + medio_ancho + 1)
        c = cuenta[b] - cuenta[a]
        out.append((suma[b] - suma[a]) / c if c else None)
    return out


def _referencia(ma_cal: List[Optional[float]], ma_todo: List[Optional[float]], i: int) -> Optional[float]:
    """Media de referencia para el punto reciente i: la del clima histórico en el mismo momento del año anterior
    o, si no hay un año de calibración, la media móvil de toda la serie (la de la norma tal cual)."""
    if 0 <= i - ANO < len(ma_cal) and ma_cal[i - ANO] is not None:
        return ma_cal[i - ANO]
    return ma_todo[i]


def _es(x: float) -> str:
    """Número con coma decimal, como se escribe en castellano."""
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


PARAMETROS = {
    "en15757": {"media_movil_dias": 30, "percentil_bajo": 7, "percentil_alto": 93},
    "simplificado": {"media_movil_dias": 7, "percentil_bajo": 10, "percentil_alto": 90},
}


def resolver_parametros(p: dict) -> dict:
    metodo = p.get("metodo") or "en15757"
    if metodo not in PARAMETROS:
        raise ValueError(f"metodo: en15757 | simplificado (no {metodo!r})")
    out = {"metodo": metodo}
    defectos = {**PARAMETROS[metodo], "minimo_hr": 10, "minimo_temperatura": 1, "reciente_dias": 30,
                "umbral_medio": 5, "umbral_alto": 15, "fluctuacion_hr_2h": 8}
    for k, d in defectos.items():
        v = p.get(k)
        out[k] = float(d if v in (None, "") else v)
    if not 0 <= out["percentil_bajo"] < out["percentil_alto"] <= 100:
        raise ValueError("percentiles: 0 ≤ bajo < alto ≤ 100")
    if out["media_movil_dias"] <= 0 or out["reciente_dias"] <= 0:
        raise ValueError("media_movil_dias y reciente_dias deben ser positivos")
    return out


def _variable(xs, ma_cal, ma_todo, n_cal, p, minimo, metodo):
    """Banda y tiempo fuera de ella, para una variable."""
    lo_p, hi_p = p["percentil_bajo"], p["percentil_alto"]
    if metodo == "en15757":
        fl = [x - m for x, m in zip(xs[:n_cal], ma_cal) if x is not None and m is not None]
        lo, hi = min(percentil(fl, lo_p), -minimo), max(percentil(fl, hi_p), minimo)
        banda = lambda ref: (ref + lo, ref + hi)  # noqa: E731
    else:
        suave = [m for m in ma_cal if m is not None]
        fijo = (percentil(suave, lo_p), percentil(suave, hi_p))
        banda = lambda ref: fijo  # noqa: E731

    def fuera(i, ref):
        x = xs[i]
        if x is None or ref is None:
            return None
        a, b = banda(ref)
        return x < a or x > b

    cal = [fuera(i, ma_cal[i]) for i in range(n_cal)]
    rec = [fuera(i, _referencia(ma_cal, ma_todo, i)) for i in range(n_cal, len(xs))]
    pct = lambda vs: 100 * sum(1 for v in vs if v) / max(1, sum(1 for v in vs if v is not None))  # noqa: E731
    return banda, pct(cal), pct(rec)


def evaluar(serie: dict, parametros: dict) -> dict:
    p = resolver_parametros(parametros)
    if len(serie.get("puntos") or []) < 2:
        raise ValueError("la serie necesita al menos dos puntos")
    inicio, tt, hh = rejilla_horaria(serie["puntos"])
    n = len(hh)
    reciente = int(p["reciente_dias"] * 24)
    calibra_entera = n - reciente < 60 * 24        # menos de 60 días antes del periodo reciente: se calibra con todo
    n_cal = n if calibra_entera else n - reciente
    inicio_rec = 0 if calibra_entera else n_cal
    medio = int(p["media_movil_dias"] * 24 / 2)
    ma_h, ma_t = media_movil(hh, medio, n_cal), media_movil(tt, medio, n_cal)
    todo_h, todo_t = media_movil(hh, medio), media_movil(tt, medio)

    banda_h, base_h, fuera_h = _variable(hh, ma_h, todo_h, n_cal, p, p["minimo_hr"], p["metodo"])
    banda_t, base_t, fuera_t = _variable(tt, ma_t, todo_t, n_cal, p, p["minimo_temperatura"], p["metodo"])
    if calibra_entera:  # sin periodo reciente aparte: lo que se mide es la propia calibración
        fuera_h, fuera_t = base_h, base_t
        base_h = base_t = (100 - (p["percentil_alto"] - p["percentil_bajo"]))

    exceso_h, exceso_t = max(0.0, fuera_h - base_h), max(0.0, fuera_t - base_t)
    desviacion = max(exceso_h, exceso_t)
    salto = 0.0
    for i in range(max(inicio_rec, 2), n):
        if hh[i] is not None and hh[i - 2] is not None:
            salto = max(salto, abs(hh[i] - hh[i - 2]))

    if desviacion > p["umbral_alto"] or salto > p["fluctuacion_hr_2h"]:
        nivel = "alto"
    elif desviacion > p["umbral_medio"]:
        nivel = "medio"
    else:
        nivel = "bajo"
    peor = "humedad" if exceso_h >= exceso_t else "temperatura"
    if salto > p["fluctuacion_hr_2h"]:
        causa = (f"La humedad relativa ha cambiado {_es(salto)} puntos en 2 horas "
                 f"(límite {_es(p['fluctuacion_hr_2h'])})")
    elif nivel == "bajo":
        causa = "La zona se mantiene dentro de las fluctuaciones de su clima histórico"
    else:
        causa = (f"La {peor} pasa un {_es(max(exceso_h, exceso_t))} % más de tiempo fuera de su banda "
                 f"que en su clima histórico")

    def ref(ma, todo, i):
        return ma[i] if i < n_cal else _referencia(ma, todo, i)

    banda = []
    for i in range(inicio_rec, n, 6):
        rh, rt = ref(ma_h, todo_h, i), ref(ma_t, todo_t, i)
        if rh is None or rt is None:
            continue
        (h0, h1), (t0, t1) = banda_h(rh), banda_t(rt)
        banda.append({"t": _iso(inicio + i * HORA), "hMin": round(h0, 2), "hMax": round(h1, 2), "hMedia": round(rh, 2),
                      "tMin": round(t0, 2), "tMax": round(t1, 2), "tMedia": round(rt, 2)})
    ult_h, ult_t = ref(ma_h, todo_h, n - 1), ref(ma_t, todo_t, n - 1)
    (oh0, oh1), (ot0, ot1) = banda_h(ult_h), banda_t(ult_t)
    vh = [x for x in hh[inicio_rec:] if x is not None]
    vt = [x for x in tt[inicio_rec:] if x is not None]
    r2 = lambda x: round(x, 2)  # noqa: E731
    out = {
        "zona": serie["zona"], "metodo": p["metodo"], "origenDatos": serie.get("metodo", "historico"),
        "periodo": {"desde": _iso(inicio), "hasta": _iso(inicio + (n - 1) * HORA),
                    "calibracionDias": round(n_cal / 24, 1), "recienteDias": round((n - inicio_rec) / 24, 1)},
        "humedad": {"media": r2(sum(vh) / len(vh)), "objetivo": [r2(oh0), r2(oh1)], "fuera30d": r2(fuera_h), "lineaBase": r2(base_h)},
        "temperatura": {"media": r2(sum(vt) / len(vt)), "objetivo": [r2(ot0), r2(ot1)], "fuera30d": r2(fuera_t), "lineaBase": r2(base_t)},
        "desviacion30d": r2(desviacion), "fluctuacionMaxHR2h": r2(salto), "nivel": nivel, "causa": causa,
        "parametros": p, "banda": banda,
    }
    if serie.get("nombre"):
        out["nombre"] = serie["nombre"]
    return out
