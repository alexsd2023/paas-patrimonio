"""La consola: plantilla común (barra lateral núcleo / productos, cabecera de producto) y las vistas del núcleo.

Las vistas de cada producto viven en ``productos/<id>/``; aquí solo está lo que es del PaaS.
"""
import html
import json
from typing import Any, Dict, List, Optional

FUENTES = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,600;1,9..144,400'
           '&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&display=swap">')

ESTILO = r"""
:root{
  --bg:#EDF0F2; --card:#FFFFFF; --ink:#1D2A3A; --muted:#5E6B79; --line:#CDD4DB; --line-2:#E3E7EB;
  --teal:#2E7D74; --teal-t:#DCEDEA; --ochre:#B97E15; --ochre-t:#F6E8CC; --red:#B8402D; --red-t:#F4DFDA;
  --nav:#1D2A3A; --nav-2:#263749; --nav-ink:#DCE3EA; --nav-muted:#9FB0C0; --nav-line:#34465A;
  --display:"Fraunces",Georgia,"Times New Roman",serif; --sans:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace; --producto:var(--teal);
}
@media (prefers-color-scheme:dark){:root{
  --bg:#121820; --card:#1A222C; --ink:#E6EBF0; --muted:#98A4B1; --line:#2C3743; --line-2:#242E39;
  --teal:#5FB3A8; --teal-t:#1C3431; --ochre:#E0AC4F; --ochre-t:#382D17; --red:#E07A66; --red-t:#3B2420;
  --nav:#0C1117; --nav-2:#16202B; --nav-line:#25313D; color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans)}
a{color:var(--teal)}
button,input,select{font:inherit}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.eyebrow{font:500 12px/1.2 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
h1{font:600 32px/1.1 var(--display);margin:4px 0 0}
h2{font:600 20px/1.2 var(--display);margin:0}
h3{font:600 17px/1.25 var(--display);margin:0}
[hidden]{display:none!important}
:focus-visible{outline:2px solid var(--ochre);outline-offset:2px}

/* ---------- consola: barra lateral + contenido ---------- */
.consola{display:flex;flex-wrap:wrap;min-height:100vh}
.barra{flex:1 1 260px;max-width:300px;background:var(--nav);color:var(--nav-ink);padding:20px 12px;display:flex;flex-direction:column;gap:14px}
@media (max-width:820px){.barra{max-width:none;flex-basis:100%}}
.marca-paas{padding:0 10px;display:flex;flex-direction:column;gap:2px}
.marca-paas .eyebrow{color:var(--nav-muted);font-size:11px}
.marca-paas b{font:600 22px var(--display);color:#fff}
.grupo{display:flex;flex-direction:column;gap:2px;padding:0 6px}
.grupo.nucleo{padding:10px 6px;border-radius:12px;background:var(--nav-2)}
.titulo-grupo{all:unset;box-sizing:border-box;width:100%;display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:7px 10px;border-radius:8px;cursor:pointer;font:700 12.5px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:#fff}
.titulo-grupo:hover{background:var(--nav-line)}
.titulo-grupo:focus-visible{outline:2px solid #F2C14E;outline-offset:2px}
.titulo-grupo .marca{display:flex;align-items:center;gap:8px}
.titulo-grupo .marca::before{content:"";width:4px;height:14px;border-radius:2px;background:var(--acento-grupo,#5FB3A1)}
.titulo-grupo .chev{width:8px;height:8px;border-right:2px solid #B9C6D3;border-bottom:2px solid #B9C6D3;transform:rotate(45deg);
  transition:transform .15s;margin:0 4px 3px 0}
.titulo-grupo[aria-expanded="false"] .chev{transform:rotate(-45deg);margin-bottom:0}
.grupo .items{display:flex;flex-direction:column;gap:2px;padding-top:2px}
.grupo .items[hidden]{display:none}
.grupo.g-capacidades{--acento-grupo:#7FA7E0}
.grupo.g-productos{--acento-grupo:#E3A64B}
.grupo.g-conectores{--acento-grupo:#C48BD6}
.grupo.g-institucion{--acento-grupo:#E07F7F}
@media (prefers-reduced-motion:reduce){.titulo-grupo .chev{transition:none}}
.barra a{padding:8px 10px;border-radius:8px;color:var(--nav-ink);text-decoration:none;display:flex;gap:10px;align-items:center;justify-content:space-between}
.barra a .izq{display:flex;gap:10px;align-items:center}
.barra a:hover{background:var(--nav-line)}
.barra a[aria-current="page"]{background:var(--nav-ink);color:var(--nav);font-weight:600}
.barra a .ext{font:12px var(--mono);color:var(--nav-muted)}
.barra a[aria-current="page"] .ext{color:var(--muted)}
.punto{width:10px;height:10px;border-radius:3px;flex:none}
.barra a.conectar{margin-top:4px;border:1px dashed #4A5D72;color:#B9C6D3}
.sesion{margin-top:auto;padding:12px 10px 0;border-top:1px solid var(--nav-line);display:flex;flex-direction:column;gap:6px}
.sesion b{color:#fff}
.sesion .mono{font-size:12px;color:var(--nav-muted)}
.sesion button{align-self:flex-start;background:transparent;border:1px solid #4A5D72;color:var(--nav-ink);border-radius:8px;padding:5px 12px;cursor:pointer}
.contenido{flex:999 1 640px;min-width:0;display:flex;flex-direction:column}
.cab-pagina{background:var(--card);border-bottom:1px solid var(--line);padding:24px clamp(16px,3vw,40px) 18px;display:flex;flex-direction:column;gap:12px}
.cab-pagina.producto{box-shadow:inset 0 6px 0 var(--producto);padding-bottom:0}
.cab-pagina .fila-cab{display:flex;flex-wrap:wrap;gap:12px 24px;justify-content:space-between;align-items:flex-end}
.cab-pagina .sub{color:var(--muted);font-size:14px}
.usa{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.usa>span:first-child{font-size:13px;color:var(--muted)}
.ficha-n{font:500 12px var(--mono);padding:3px 8px;border-radius:6px;background:var(--bg);border:1px solid var(--line)}
.pestanas{display:flex;flex-wrap:wrap;gap:4px}
.pestanas a{padding:10px 14px;font-weight:600;text-decoration:none;color:var(--muted);border-bottom:3px solid transparent}
.pestanas a[aria-current="page"]{color:var(--ink);border-bottom-color:var(--producto)}
.cuerpo{padding:22px clamp(16px,3vw,40px) 48px;display:flex;flex-direction:column;gap:20px}
.tarjeta{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;min-width:0}
.rejilla{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--min,260px)),1fr))}
.kpi .num{font:600 34px/1 var(--display);font-variant-numeric:tabular-nums;margin-top:6px}
.kpi .pie{color:var(--muted);font-size:13px;margin-top:6px}
.cab{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.vacio{padding:24px 16px;color:var(--muted)}
.aviso{background:var(--red-t);border:1px solid var(--red);color:var(--ink);padding:10px 12px;border-radius:8px;font-size:14px;margin:0}
.aviso.ok{background:var(--teal-t);border-color:var(--teal)}
.pill{font:500 12px/1 var(--mono);padding:5px 8px;border-radius:999px;border:1px solid var(--line);white-space:nowrap;align-self:start}
.pill.ok,.pill.validada{background:var(--teal-t);border-color:var(--teal);color:var(--teal)}
.pill.pendiente{background:var(--ochre-t);border-color:var(--ochre);color:var(--ochre)}
.pill.alerta,.pill.caida{background:var(--red-t);border-color:var(--red);color:var(--red)}
.btn{border:1px solid var(--teal);background:var(--teal);color:var(--card);padding:7px 14px;border-radius:8px;cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
.btn.sec{background:transparent;color:var(--teal)}
.btn:disabled{opacity:.5;cursor:default}
.tabla{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:8px 10px 8px 0;border-bottom:1px solid var(--line-2);vertical-align:top}
th{font:500 12px var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.05em;border-bottom-color:var(--line)}
label{display:grid;gap:4px;font-size:14px}
input[type=text],input[type=password],input[type=search],input[type=email],input[type=url],input[type=number],input:not([type]),select{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--bg);color:var(--ink)}
.sonda{display:grid;grid-template-columns:auto 1fr auto;gap:2px 10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line-2)}
.sonda:last-child{border-bottom:0}
.sonda .luz{width:10px;height:10px;border-radius:50%;background:var(--red)}
.sonda.ok .luz{background:var(--teal)}
.sonda .dest{grid-column:2/-1;font:12px var(--mono);color:var(--muted)}
.producto-t{border-left:5px solid var(--producto);display:flex;flex-direction:column;gap:10px}
.producto-t .lista-v{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:14px}
pre.manifiesto{margin:0;font:13px/1.5 var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:14px;overflow-x:auto}
ol.pasos-c{margin:0;padding-left:20px;display:grid;gap:6px}
"""

SCRIPT_COMUN = r"""
const CFG = JSON.parse(document.getElementById('cfg').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fecha = s => s ? new Date(s).toLocaleString('es-ES', {day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit', second:'2-digit'}) : '';
const NUM = new Intl.NumberFormat('es-ES', {maximumFractionDigits: 1});
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { location.reload(); throw new Error('sesión caducada'); }
  const cuerpo = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(cuerpo.detail ? (typeof cuerpo.detail === 'string' ? cuerpo.detail : JSON.stringify(cuerpo.detail)) : r.statusText);
  return cuerpo;
}
function aviso(msg, ok) { const n = $('#mensaje'); if (!n) return; n.className = 'aviso' + (ok ? ' ok' : ''); n.textContent = msg; n.hidden = false; clearTimeout(aviso.t); aviso.t = setTimeout(() => n.hidden = true, 6000); }
"""

# Todas las piezas del núcleo, en la barra lateral: (nombre, tecnología, clave de su consola en «enlaces» o None).
# Las consolas en INCRUSTADAS se abren dentro de la consola (/panel/nucleo/<clave>); las demás con consola
# pública, en otra pestaña; las que no tienen consola, en su estado en /panel.
PIEZAS = [("Identidad", "Keycloak", "keycloak"), ("Puerta", "APISIX", None), ("Correos", "Kafka", "kafka"),
          ("Puente", "catastro → bus", None), ("Catastro", "Scorpio", "scorpio"), ("Procesos", "Temporal", "temporal"),
          ("Notario", "Fuseki", "fuseki"), ("Trazas", "Jaeger", "jaeger"), ("Modelos", "MLflow", "mlflow"),
          ("Catálogo", "servicios · conectores", None)]

# Consolas técnicas que viven detrás de la puerta, bajo /panel/<clave>/ (ver platform/apisix/apisix.yaml)
INCRUSTADAS = {"jaeger": ("Trazas", "Jaeger", "/panel/jaeger/search"), "temporal": ("Procesos", "Temporal", "/panel/temporal/"),
               "kafka": ("Correos", "Kafka UI", "/panel/kafka/"), "mlflow": ("Modelos", "MLflow", "/panel/mlflow/"),
               "fuseki": ("Notario", "Fuseki", "/panel/fuseki/")}

e = html.escape


def _a(href: str, texto: str, activo: bool = False, extra: str = "", clase: str = "", externo: bool = False) -> str:
    attrs = ' aria-current="page"' if activo else ""
    attrs += ' target="_blank" rel="noopener"' if externo else ""
    attrs += f' class="{clase}"' if clase else ""
    return f'<a href="{e(href)}"{attrs}><span class="izq">{texto}</span>{extra}</a>'


def _grupo(clave: str, titulo: str, contenido: str, clase: str = "") -> str:
    """Un grupo de la barra con su título como botón para plegarlo y desplegarlo."""
    return (f'<div class="grupo g-{clave} {clase}" data-grupo="{clave}">'
            f'<button type="button" class="titulo-grupo" aria-expanded="true" aria-controls="g-{clave}">'
            f'<span class="marca">{titulo}</span><span class="chev" aria-hidden="true"></span></button>'
            f'<div class="items" id="g-{clave}">{contenido}</div></div>')


# Pliega/despliega los grupos de la barra y recuerda la elección en este navegador.
# El grupo con la página actual siempre se abre.
BARRA_SCRIPT = r"""<script>(() => {
  let plegados = [];
  try { plegados = JSON.parse(localStorage.getItem('barra-plegados') || '[]'); } catch (e) {}
  const guardar = () => { try { localStorage.setItem('barra-plegados', JSON.stringify(plegados)); } catch (e) {} };
  document.querySelectorAll('.barra .grupo[data-grupo]').forEach(g => {
    const b = g.querySelector('.titulo-grupo'), items = g.querySelector('.items'), k = g.dataset.grupo;
    const poner = abierto => { b.setAttribute('aria-expanded', String(abierto)); items.hidden = !abierto; };
    poner(!plegados.includes(k) || !!items.querySelector('[aria-current="page"]'));
    b.addEventListener('click', () => {
      const abrir = b.getAttribute('aria-expanded') !== 'true';
      poner(abrir);
      plegados = plegados.filter(x => x !== k).concat(abrir ? [] : [k]);
      guardar();
    });
  });
})();</script>"""


def barra(productos: List[Any], activo: str, quien: Any, enlaces: Dict[str, str],
          activos: Optional[List[str]] = None) -> str:
    """activo: 'nucleo:estado|cartas', 'capacidades:servicios|recetas|nueva-receta|ejecuciones', 'productos', 'producto:<id>', 'conectores'
    o 'institucion'. activos: productos activados por la institución (None = todos)."""
    def pieza(t, n, k):
        if k in INCRUSTADAS:
            return _a(f"/panel/nucleo/{k}", t, activo == f"nucleo:{k}", extra=f'<span class="ext">{n}</span>')
        if k and enlaces.get(k):
            return _a(enlaces[k], t, extra=f'<span class="ext">{n} ↗</span>', externo=True)
        return _a(f"/panel#pieza-{t.lower()}", t, extra=f'<span class="ext">{n}</span>')
    ext = "".join(pieza(t, n, k) for t, n, k in PIEZAS)
    mis = "".join(_a(c.entrada, f'<span class="punto" style="background:{e(c.color)}" aria-hidden="true"></span>{e(c.nombre)}'
                     + (" ↗" if c.externo else ""), activo == f"producto:{c.id}", externo=c.externo) for c in productos
                  if c.estado == "conectado" and (activos is None or c.id in activos))
    roles = " · ".join(r for r in quien.roles if r in ("archivera", "paleografa", "admin-institucion", "admin-paas")) or "sin rol"
    gestiona = any(r in quien.roles for r in ("admin-institucion", "admin-paas"))
    mia = _grupo("institucion", "Mi institución",
                 _a("/panel/institucion", "Personas, productos y claves" if gestiona else "Mi institución", activo == "institucion")
                 + (_a("/panel/instituciones", "Instituciones · altas", activo == "instituciones") if "admin-paas" in quien.roles else ""))
    nucleo = (_a('/panel', 'Estado de la plataforma', activo == 'nucleo:estado')
              + _a('/panel/cartas', 'Cartas · bus', activo == 'nucleo:cartas') + ext)
    capacidades = (_a('/panel/servicios', 'Servicios', activo == 'capacidades:servicios')
                   + _a('/panel/recetas', 'Recetas', activo == 'capacidades:recetas')
                   + _a('/panel/recetas/nueva', 'Nueva receta', activo == 'capacidades:nueva-receta')
                   + _a('/panel/recetas/ejecuciones', 'Ejecuciones', activo == 'capacidades:ejecuciones')
                   + _a('/panel/servicios#publicar', 'Publicar un servicio', clase='conectar'))
    prods = (_a('/panel/productos', 'Marketplace', activo == 'productos')
             + _a('/panel/mis-productos', 'Mis productos', activo == 'mis-productos') + mis
             + _a('/panel/productos#publicar', 'Publicar un producto', clase='conectar'))
    cons = (_a('/panel/conectores', 'Sistemas de la institución', activo == 'conectores')
            + _a('/panel/conectores#escribir', 'Escribir un conector', clase='conectar'))
    return f"""<nav class="barra" aria-label="Consola">
<div class="marca-paas"><span class="eyebrow">PaaS Patrimonio</span><b>Consola</b></div>
{_grupo("nucleo", "Núcleo del PaaS", nucleo, "nucleo")}
{_grupo("capacidades", "Capacidades", capacidades)}
{_grupo("productos", "Productos", prods)}
{_grupo("conectores", "Conectores", cons)}
{mia}
<div class="sesion"><b>{e(quien.usuario)}</b><span class="mono">{e(quien.tenant)} · {e(roles)}</span>
<form method="post" action="/panel/salir"><button type="submit">Salir</button></form></div>
{BARRA_SCRIPT}
</nav>"""


MARCO_ESTILO = """
.cuerpo.marco{padding:0;gap:0}
.cuerpo.marco #mensaje{margin:12px clamp(16px,3vw,40px)}
.consola-externa{display:block;width:100%;height:calc(100vh - 97px);min-height:520px;border:0;background:var(--card)}
"""


def cuerpo_marco(clave: str, ruta: str, nombre: str) -> str:
    return (f'<iframe class="consola-externa" src="{e(ruta)}" title="{e(nombre)}" '
            f'referrerpolicy="same-origin"></iframe>')


def cabecera_nucleo(eyebrow: str, titulo: str, sub: str = "", derecha: str = "", capa: str = "Núcleo del PaaS") -> str:
    return f"""<header class="cab-pagina"><div class="fila-cab"><div>
<p class="eyebrow" style="margin:0">{e(capa)} · {e(eyebrow)}</p><h1>{e(titulo)}</h1>
{f'<p class="sub" style="margin:6px 0 0">{e(sub)}</p>' if sub else ''}</div>{derecha}</div></header>"""


def cabecera_producto(producto: Any, vista: str) -> str:
    from services.panel.productos import PIEZAS_NUCLEO
    usa = "".join(f'<span class="ficha-n" title="{e(PIEZAS_NUCLEO.get(u, u))}">{e(PIEZAS_NUCLEO.get(u, u).split(" · ")[0])}</span>'
                  for u in producto.usa)
    actual = ' aria-current="page"'
    pest = "".join(f'<a href="{e(producto.url(v.id))}"{actual if v.id == vista else ""}>{e(v.nombre)}'
                   f'<span class="cuenta" data-vista="{e(v.id)}"></span></a>' for v in producto.vistas)
    return f"""<header class="cab-pagina producto" style="--producto:{e(producto.color)}">
<div class="fila-cab"><div><p class="eyebrow" style="margin:0;color:var(--producto)">Producto</p><h1>{e(producto.nombre)}</h1>
<p class="sub" style="margin:6px 0 0">{e(producto.resumen)}</p></div>
<div class="usa"><span>Del núcleo usa</span>{usa}</div></div>
<nav class="pestanas" aria-label="Vistas del producto">{pest}</nav></header>"""


def documento(titulo: str, barra_html: str, cabecera: str, cuerpo: str, cfg: Dict[str, Any],
              script: str = "", estilo: str = "", color: Optional[str] = None) -> str:
    cfg_json = json.dumps(cfg).replace("</", "<\\/")
    var = f' style="--producto:{e(color)}"' if color else ""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(titulo)} · Consola</title>{FUENTES}
<style>{ESTILO}{estilo}</style></head><body>
<div class="consola"{var}>{barra_html}<div class="contenido">{cabecera}
<main class="cuerpo{' marco' if 'class="consola-externa"' in cuerpo else ''}"><p id="mensaje" class="aviso" role="status" hidden></p>{cuerpo}</main></div></div>
<script type="application/json" id="cfg">{cfg_json}</script>
<script>{SCRIPT_COMUN}{script}</script></body></html>"""


def entrar_html(error: str = "") -> str:
    err = f'<p class="aviso" role="alert">{e(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Consola del PaaS</title>{FUENTES}
<style>{ESTILO}
.entrar{{max-width:380px;margin:12vh auto;padding:0 16px;display:grid;gap:14px}}
.entrar form{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;display:grid;gap:12px}}
.pista{{color:var(--muted);font-size:13px;margin:0}}
</style></head><body><div class="entrar">
<div><p class="eyebrow" style="margin:0">PaaS Patrimonio</p><h1>Consola</h1></div>
<p class="pista">Entra con tu usuario de Keycloak. Verás el núcleo de la plataforma y los productos de tu institución.</p>{err}
<form method="post" action="/panel/entrar">
<label>Usuario<input type="text" id="usuario" name="usuario" autocomplete="username" required autofocus></label>
<label>Contraseña<input type="password" id="clave" name="clave" autocomplete="current-password" required></label>
<button class="btn" type="submit">Entrar</button></form>
<p class="pista">¿Tu institución aún no usa la plataforma? <a href="/panel/alta">Dadla de alta</a>.</p>
<p class="pista">Usuarios de prueba: <span class="mono">m.ortega</span> (archivera), <span class="mono">paleografa-test</span> (paleógrafa), <span class="mono">p.otro</span> (otra institución).</p>
</div></body></html>"""


# ======================= vistas del núcleo =======================

ESTADO_CUERPO = """
<section class="rejilla" style="--min:200px" aria-label="Resumen">
<div class="tarjeta kpi"><span class="eyebrow">Piezas del núcleo</span><div class="num" id="k-piezas">—</div><div class="pie" id="k-piezas-pie">sondeando…</div></div>
<div class="tarjeta kpi"><span class="eyebrow">Productos conectados</span><div class="num" id="k-productos">—</div><div class="pie" id="k-capas">—</div></div>
<div class="tarjeta kpi"><span class="eyebrow">Cartas en el bus</span><div class="num" id="k-cartas">—</div><div class="pie" id="k-buzones">—</div></div>
<div class="tarjeta kpi"><span class="eyebrow">Tu institución</span><div class="num mono" style="font-size:20px;line-height:1.3" id="k-tenant"></div><div class="pie">aislada en catastro, notario y bus</div></div>
</section>
<section aria-labelledby="t-capas"><div class="cab"><h2 id="t-capas">La plataforma por capas</h2></div>
<div class="rejilla" style="--min:200px" id="capas"></div></section>
<div class="rejilla" style="--min:340px">
<section class="tarjeta" aria-labelledby="t-piezas"><div class="cab"><h2 id="t-piezas">Piezas del núcleo</h2><span class="eyebrow">cada 5 s</span></div>
<div id="sondas"><p class="vacio">Sondeando…</p></div></section>
<section class="tarjeta" aria-labelledby="t-contrato"><div class="cab"><h2 id="t-contrato">Contrato de integración</h2></div>
<p style="margin:0 0 10px;color:var(--muted);font-size:14px">Lo que cualquier producto recibe del núcleo, igual para todos.</p>
<div class="tabla"><table><tbody>
<tr><td class="mono">ID</td><td><b>Identidad</b> · token de Keycloak con institución y roles; la puerta lo exige.</td></tr>
<tr><td class="mono">API</td><td><b>Puerta</b> · rutas /api/v1 en APISIX, con OIDC.</td></tr>
<tr><td class="mono">EV</td><td><b>Correos</b> · cartas CloudEvents 1.0 con contrato JSON Schema en <span class="mono">contracts/</span>.</td></tr>
<tr><td class="mono">DAT</td><td><b>Catastro</b> NGSI-LD por institución y <b>notario</b> PROV-O con un grafo por institución.</td></tr>
<tr><td class="mono">PRO</td><td><b>Procesos</b> en Temporal y <b>trazas</b> OpenTelemetry de punta a punta.</td></tr>
</tbody></table></div></section>
</div>
<div class="rejilla" style="--min:340px">
<section class="tarjeta" aria-labelledby="t-productos"><div class="cab"><h2 id="t-productos">Productos conectados</h2><a href="/panel/productos">Catálogo</a></div>
<div id="productos" style="display:grid;gap:12px"></div></section>
<section class="tarjeta" aria-labelledby="t-buz"><div class="cab"><h2 id="t-buz">Buzones del bus</h2><a href="/panel/cartas">Cartas</a></div>
<div id="buzones"><p class="vacio">Leyendo Kafka…</p></div></section>
</div>"""

ESTADO_SCRIPT = r"""
function pintarCapas(c) {
  $('#k-capas').textContent = `${c.capacidades ?? '?'} capacidades · ${c.conectores ?? '?'} conectores`;
  $('#capas').innerHTML = [
    ['Núcleo', 'lo común a todos', c.nucleo, '/panel'],
    ['Capacidades', 'servicios reutilizables y flujos', c.capacidades, '/panel/servicios'],
    ['Productos', 'lo que activa cada institución', c.productos, '/panel/productos'],
    ['Conectores', 'los sistemas que ya tiene', c.conectores, '/panel/conectores']].map(([n, d, v, u]) =>
    `<a href="${u}" class="tarjeta kpi" style="text-decoration:none;color:inherit"><span class="eyebrow">${n}</span><div class="num">${v ?? '—'}</div><div class="pie">${d}</div></a>`).join('');
}
function pintarCasos(productos) {
  $('#k-productos').textContent = productos.filter(c => c.estado === 'conectado').length;
  $('#productos').innerHTML = productos.map(c => `<a href="${esc(c.url)}" style="text-decoration:none;color:inherit;display:grid;grid-template-columns:12px 1fr;gap:4px 10px;align-items:center">
    <span class="punto" style="background:${esc(c.color)}"></span><b>${esc(c.nombre)}</b>
    <span></span><span style="color:var(--muted);font-size:13px">usa ${c.usa.map(esc).join(' · ')}</span></a>`).join('') || '<p class="vacio">Ningún producto conectado.</p>';
}
function pintarBuzones(buz, porCaso, error) {
  if (error) { $('#buzones').innerHTML = `<p class="aviso">${esc(error)}</p>`; $('#k-cartas').textContent = '—'; return; }
  $('#k-cartas').textContent = NUM.format(buz.reduce((s, b) => s + b.cartas, 0));
  $('#k-buzones').textContent = `${buz.length} buzones`;
  $('#buzones').innerHTML = `<div class="tabla"><table><thead><tr><th>Buzón</th><th>Cartas</th><th>Productos que lo usan</th></tr></thead><tbody>${
    buz.map(b => `<tr><td class="mono">${esc(b.buzon)}</td><td class="mono">${NUM.format(b.cartas)}</td><td>${(porCaso[b.buzon] || []).map(esc).join(', ') || '<span style="color:var(--muted)">núcleo</span>'}</td></tr>`).join('')}</tbody></table></div>`;
}
async function cargar() {
  let d;
  try { d = await api('/panel/api/nucleo/estado'); } catch (e) { $('#sondas').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  const ok = d.sondas.filter(s => s.ok).length;
  $('#k-piezas').textContent = `${ok}/${d.sondas.length}`;
  $('#k-piezas-pie').textContent = ok === d.sondas.length ? 'todas responden' : `${d.sondas.length - ok} sin respuesta`;
  $('#sondas').innerHTML = d.sondas.map(s => `<div class="sonda ${s.ok ? 'ok' : ''}" id="pieza-${esc((s.nombre.split(' ')[0] || '').toLowerCase())}"><span class="luz" aria-hidden="true"></span>
    <span>${esc(s.nombre)}</span><span class="pill ${s.ok ? 'ok' : 'caida'}">${s.ok ? s.ms + ' ms' : 'sin respuesta'}</span>
    <span class="dest">${esc(s.destino)}${s.detalle ? ' · ' + esc(s.detalle) : ''}</span></div>`).join('');
  pintarCasos(d.productos);
  pintarCapas({...d.capas, nucleo: `${ok}/${d.sondas.length}`});
  pintarBuzones(d.buzones, d.buzonesPorProducto, d.errorBus);
}
$('#k-tenant').textContent = CFG.tenant;
cargar(); setInterval(cargar, 5000);
"""

CARTAS_CUERPO = """
<section class="rejilla" style="--min:200px" id="buzones" aria-label="Buzones"><p class="vacio">Leyendo Kafka…</p></section>
<section class="tarjeta" aria-labelledby="t-ult"><div class="cab"><h2 id="t-ult">Últimas cartas de tu institución</h2>
<span class="eyebrow">filtradas por la cabecera ce_tenant</span></div>
<div id="ultimas"><p class="vacio">Leyendo…</p></div></section>"""

CARTAS_SCRIPT = r"""
async function cargar() {
  let d;
  try { d = await api('/panel/api/nucleo/cartas'); } catch (e) { $('#ultimas').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  if (d.error) { $('#buzones').innerHTML = `<p class="aviso">${esc(d.error)}</p>`; $('#ultimas').innerHTML = ''; return; }
  $('#buzones').innerHTML = d.buzones.map(b => `<div class="tarjeta kpi"><span class="eyebrow">buzón</span>
    <div class="mono" style="font-size:20px;font-weight:500;margin-top:4px">${esc(b.buzon)}</div>
    <div class="num">${NUM.format(b.cartas)}</div>
    <div class="pie">${(d.buzonesPorProducto[b.buzon] || []).map(esc).join(', ') || 'núcleo'}</div></div>`).join('');
  $('#ultimas').innerHTML = d.ultimas.length ? `<div class="tabla"><table><thead><tr><th>Cuándo</th><th>Buzón</th><th>Tipo</th><th>Sujeto</th><th>Traza</th></tr></thead><tbody>${
    d.ultimas.map(c => `<tr><td class="mono">${fecha(c.tiempo)}</td><td class="mono">${esc(c.buzon)}</td><td class="mono">${esc(c.tipo)}</td>
      <td class="mono" style="word-break:break-all">${esc(c.sujeto)}</td>
      <td>${c.traza && CFG.enlaces.jaeger ? `<a class="mono" href="${esc(CFG.enlaces.jaeger)}/trace/${esc(c.traza)}" target="_blank" rel="noopener">${esc(c.traza.slice(0, 8))}</a>` : ''}</td></tr>`).join('')}</tbody></table></div>`
    : '<p class="vacio">Aún no hay cartas de tu institución.</p>';
}
cargar(); setInterval(cargar, 5000);
"""


def catalogo_cuerpo(productos: List[Any], activos: Optional[List[str]] = None) -> str:
    from services.panel.productos import PIEZAS_NUCLEO
    tarjetas = []
    for c in productos:
        usa = "".join(f'<span class="ficha-n">{e(PIEZAS_NUCLEO.get(u, u))}</span>' for u in c.usa)
        vistas = "".join(f'<a href="{e(c.url(v.id))}">{e(v.nombre)}</a>' for v in c.vistas) if c.estado == "conectado" else ""
        estado = "" if c.estado == "conectado" else f'<span class="pill pendiente">{e(c.estado)}</span>'
        if c.estado == "conectado" and activos is not None:
            on = c.id in activos
            estado = (f'<span class="pill {"ok" if on else "pendiente"}">{"activado" if on else "sin activar"}</span>'
                      + ("" if on else ' <a class="btn sec" href="/panel/institucion">Activar</a>'))
            vistas = vistas if on else ""
        tarjetas.append(f"""<article class="tarjeta producto-t" style="--producto:{e(c.color)}">
<div class="cab" style="margin:0"><h2>{e(c.nombre)}</h2>{estado}</div>
<p style="margin:0;color:var(--muted)">{e(c.resumen)}</p>
<div class="usa"><span>Del núcleo usa</span>{usa}</div>
<div style="font-size:14px"><b>Capacidades que requiere:</b> <span class="mono">{e(', '.join(c.requiere) or '—')}</span><br>
<b>Contenedores propios:</b> <span class="mono">{e(', '.join(c.contenedores) or '—')}</span><br>
<b>Buzones:</b> <span class="mono">{e(', '.join(c.buzones) or '—')}</span></div>
{f'<div class="lista-v"><b>Vistas:</b>{vistas}</div>' if vistas else ''}</article>""")
    return f"""<section class="rejilla" style="--min:360px" aria-label="Productos">{''.join(tarjetas) or '<p class="vacio">No hay productos en productos/.</p>'}</section>
<section class="tarjeta" id="conectar" aria-labelledby="t-conectar"><div class="cab"><h2 id="t-conectar">Conectar un producto</h2></div>
<div class="rejilla" style="--min:320px"><ol class="pasos-c">
<li>Crea <span class="mono">productos/&lt;id&gt;/producto.yaml</span> con su nombre, su color, lo que usa del núcleo y sus vistas.</li>
<li>Escribe <span class="mono">productos/&lt;id&gt;/__init__.py</span> con <span class="mono">montar(nucleo, producto)</span>, que devuelve sus rutas.</li>
<li>Si publica cartas, añade sus contratos en <span class="mono">contracts/eventos/</span> y su buzón en <span class="mono">TOPIC_POR_TIPO</span>.</li>
<li>Reconstruye el panel. Aparece en la barra lateral y aquí, sin tocar el núcleo.</li></ol>
<pre class="manifiesto">id: edicion-tei
nombre: Edición TEI
color: "#7A5BB5"
resumen: De la copia validada a la edición crítica
usa: [identidad, correos, catastro, notario]
requiere: [ner-historico]
contenedores: [editor-tei]
buzones: [htr, ediciones]
vistas:
  - {{id: ediciones, nombre: Ediciones}}
  - {{id: revisar, nombre: Revisar, ruta: revisar}}</pre></div></section>"""
