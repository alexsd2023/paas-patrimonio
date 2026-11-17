"""Visitas por IP a partir del registro JSON de Caddy (lo llama visitas.sh).

    python3 visitas.py <base.mmdb> [días] [csv] [código de país]   < registro

Una visita agrupa las peticiones de una IP sin pausas de más de 30 minutos. El tiempo dentro va de la
primera a la última petición: es aproximado (no se sabe cuánto se quedó leyendo la última página).
"""
import json, re, subprocess, sys, time

PAUSA = 1800
geo, args = sys.argv[1], sys.argv[2:]
dias = next((int(a) for a in args if a.isdigit()), 7)
formato = "csv" if "csv" in [a.lower() for a in args] else "tabla"
filtro = next((a.upper() for a in args if len(a) == 2 and a.isalpha()), None)
desde = time.time() - dias * 86400

peticiones = []
for linea in sys.stdin:
    try:
        d = json.loads(linea)
    except ValueError:
        continue
    r = d.get("request") or {}
    ip = r.get("client_ip") or r.get("remote_ip")
    ts = d.get("ts")
    sitio = (r.get("host") or "?").split(":")[0].split(".")[0]     # paas · auth · neo4j
    if ip and ts and ts >= desde:
        peticiones.append((ip, ts, sitio))
peticiones.sort(key=lambda p: (p[0], p[1]))

visitas = []          # [ip, inicio, fin, peticiones, sitios]
for ip, ts, sitio in peticiones:
    if visitas and visitas[-1][0] == ip and ts - visitas[-1][2] <= PAUSA:
        visitas[-1][2] = ts; visitas[-1][3] += 1; visitas[-1][4].add(sitio)
    else:
        visitas.append([ip, ts, ts, 1, {sitio}])
visitas.sort(key=lambda v: v[1], reverse=True)


def hora(ts, segundos=False):
    return time.strftime("%Y-%m-%d %H:%M:%S" if segundos else "%Y-%m-%d %H:%M", time.localtime(ts))


def duracion(seg):
    seg = int(seg)
    if seg < 60:
        return "<1 min"
    h, m = divmod(seg // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


_lugares = {}
def lugar(ip):
    """(código de país, país, región, ciudad)"""
    if ip not in _lugares:
        def busca(*ruta):
            s = subprocess.run(["mmdblookup", "--file", geo, "--ip", ip, *ruta],
                               capture_output=True, text=True).stdout
            m = re.search(r"\"(.*)\"", s)
            return m.group(1) if m else ""
        def nombre(*ruta):
            return busca(*ruta, "names", "es") or busca(*ruta, "names", "en")
        _lugares[ip] = (busca("country", "iso_code") or "--", nombre("country") or "desconocido",
                        nombre("subdivisions", "0"), nombre("city"))
    return _lugares[ip]


filas = []
for ip, ini, fin, n, sitios in visitas:
    c, p, region, ciudad = lugar(ip)
    if filtro and c != filtro:
        continue
    filas.append((ini, ip, duracion(fin - ini), "+".join(sorted(sitios)), c, p, region, ciudad, n))

if formato == "csv":
    print("hora;ip;tiempo_dentro;sitios;codigo_pais;pais;region;ciudad;peticiones")
    for ini, ip, t, s, c, p, region, ciudad, n in filas:
        print(f"{hora(ini, True)};{ip};{t};{s};{c};{p};{region};{ciudad};{n}")
else:
    print(f"{'HORA':<16}  {'IP':<39}  {'DENTRO':<12}  {'SITIO':<11}  UBICACIÓN")
    for ini, ip, t, s, c, p, region, ciudad, n in filas:
        donde = ", ".join(x for x in (ciudad, region, p) if x)
        print(f"{hora(ini):<16}  {ip:<39}  {t:<12}  {s:<11}  {c} · {donde}")
    print(f"\n{len(filas)} visitas de {len(set(f[1] for f in filas))} IP distintas en los últimos {dias} días"
          + (f" ({filtro})" if filtro else ""), file=sys.stderr)
