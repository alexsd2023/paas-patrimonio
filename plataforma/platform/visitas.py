"""Visitas por IP, hora y país a partir del registro JSON de Caddy (lo llama visitas.sh)."""
import json, re, subprocess, sys, time
dias, formato, geo = int(sys.argv[1]), sys.argv[2], sys.argv[3]
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
    if ip and ts and ts >= desde:
        peticiones.append((ip, ts))
peticiones.sort(key=lambda p: (p[0], p[1]))

visitas = []          # [ip, inicio, fin, peticiones]
for ip, ts in peticiones:
    if visitas and visitas[-1][0] == ip and ts - visitas[-1][2] <= 1800:
        visitas[-1][2] = ts; visitas[-1][3] += 1
    else:
        visitas.append([ip, ts, ts, 1])
visitas.sort(key=lambda v: v[1], reverse=True)

def hora(ts, segundos=False):
    return time.strftime("%Y-%m-%d %H:%M:%S" if segundos else "%Y-%m-%d %H:%M", time.localtime(ts))

paises = {}
def pais(ip):
    if ip not in paises:
        def busca(*ruta):
            s = subprocess.run(["mmdblookup", "--file", geo, "--ip", ip, *ruta], capture_output=True, text=True).stdout
            m = re.search(r"\"(.*)\"", s)
            return m.group(1) if m else ""
        paises[ip] = (busca("country", "iso_code") or "--", busca("country", "names", "es") or busca("country", "names", "en") or "desconocido")
    return paises[ip]

if formato == "csv":
    print("hora;ip;codigo_pais;pais;peticiones")
    for ip, ini, fin, n in visitas:
        c, p = pais(ip)
        print(f"{hora(ini, True)};{ip};{c};{p};{n}")
else:
    print(f"{'HORA':<19}  {'IP':<39}  PAÍS")
    for ip, ini, fin, n in visitas:
        c, p = pais(ip)
        print(f"{hora(ini):<19}  {ip:<39}  {c} {p}")
    print(f"\n{len(visitas)} visitas de {len(set(v[0] for v in visitas))} IP distintas en los últimos {dias} días", file=sys.stderr)
