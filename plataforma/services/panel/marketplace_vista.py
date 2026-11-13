"""Marketplace de productos: escaparate, ficha, activar (permisos y quién lo usa) y Mis productos.

La consola pinta; quien guarda las activaciones (con sus permisos y sus roles) es el servicio de
instituciones. Solo quien administra la institución activa, cambia permisos o desactiva.
`act` es lo que devuelve /activaciones: {gestionada, activos, detalle: {id: {permisos, roles, por, cuando}}}
o None si el servicio no responde.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from services.panel.pagina import e
from services.panel.productos import MODELOS, OFICIOS, PIEZAS_NUCLEO

CANDADO = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex-shrink:0;margin-top:2px;color:var(--teal)">'
           '<rect x="4" y="10" width="16" height="10" rx="2"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path></svg>')
ROLES = [("archivera", "Archiveras"), ("paleografa", "Paleógrafas"), ("admin-institucion", "Administración")]
_FLUJOS = Path(__file__).resolve().parents[2] / "flujos"
# El Marketplace no enseña precios. Para volver a enseñarlos: MOSTRAR_PRECIOS=si
MOSTRAR_PRECIOS = os.environ.get("MOSTRAR_PRECIOS", "no").strip().lower() in ("si", "sí", "1", "true")

ESTILO = r"""
:root{--azul:#2F5DA8;--azul-t:#E3EBF8}
@media (prefers-color-scheme:dark){:root{--azul:#8AAEE8;--azul-t:#1B2A40}}
.modelo{font:600 12.5px/1 var(--sans);padding:5px 10px;border-radius:999px;border:1px solid;align-self:flex-start;white-space:nowrap}
.modelo.integrado{background:var(--teal-t);border-color:var(--teal);color:var(--teal)}
.modelo.alojado{background:var(--azul-t);border-color:var(--azul);color:var(--azul)}
.modelo.externo{background:var(--ochre-t);border-color:var(--ochre);color:var(--ochre)}
.mk-filtros{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.mk-filtros .chip{min-height:40px;padding:0 14px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;font:600 14px var(--sans)}
.mk-filtros .chip[aria-pressed="true"]{background:var(--nav);border-color:var(--nav);color:#fff}
.mk-filtros label{display:flex;gap:8px;align-items:center;margin-left:auto;min-height:40px;cursor:pointer}
.mk-rejilla{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.mk-tarjeta{display:flex;flex-direction:column;gap:12px;border-top:4px solid var(--producto)}
.mk-tarjeta h2{margin:0;font:600 21px/1.2 var(--display)}
.mk-autor{font-size:13.5px;color:var(--muted)}
.mk-etqs{display:flex;flex-wrap:wrap;gap:6px}
.mk-etqs span{font-size:13px;background:var(--line-2);border-radius:999px;padding:4px 10px}
.mk-ficha{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.mk-ficha h2{margin:0 0 10px;font-size:17px}
.mk-permiso{display:flex;gap:10px;align-items:flex-start;padding:6px 0}
.mk-permiso small{display:block;color:var(--muted);font-size:13px}
.mk-datos{border-radius:12px;padding:18px;border:1px solid}
.mk-datos.dentro{background:var(--teal-t);border-color:var(--teal)}
.mk-datos.fuera{background:var(--ochre-t);border-color:var(--ochre)}
.mk-datos b{display:block;margin-bottom:6px}
.mk-precio{display:flex;flex-direction:column;gap:10px;min-width:240px}
.mk-cab{display:flex;flex-wrap:wrap;justify-content:space-between;gap:20px;align-items:flex-start}
.mk-cab h1{margin:6px 0;font:600 32px/1.15 var(--display)}
.mk-activar{max-width:680px;margin:0 auto;display:flex;flex-direction:column;gap:18px}
.mk-activar fieldset{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
.mk-activar legend{font-weight:600;margin-bottom:6px}
.mk-activar label{display:flex;gap:10px;align-items:flex-start;min-height:40px;cursor:pointer}
.mk-activar input[type=checkbox]{width:18px;height:18px;margin-top:3px;accent-color:var(--teal)}
.mk-roles{display:flex;flex-wrap:wrap;gap:16px}
.mk-mis{display:flex;flex-wrap:wrap;gap:16px;align-items:center}
.mk-mis>div{display:flex;flex-direction:column;gap:4px;min-width:0}
.mk-acciones{display:flex;gap:8px;flex-wrap:wrap}
.btn.peligro{background:transparent;border-color:var(--red);color:var(--red)}
.btn.grande{padding:11px 18px;font-size:16px}
"""


def _modelo(c) -> str:
    return f'<span class="modelo {e(c.modelo)}">{e(MODELOS.get(c.modelo, c.modelo))}</span>'


def _datos(c) -> str:
    if c.datos_salen:
        return (f'<div class="mk-datos fuera"><b>Tus datos salen de la plataforma</b>Este producto corre en los servidores '
                f'de su autor ({e(c.url_externa)}). Los documentos que abras en él viajan allí; lo que guarde vuelve a tu '
                f'catastro con su procedencia.</div>')
    quien = "el equipo del PaaS" if c.autor == "Equipo PaaS Patrimonio" else "su autor"
    donde = ("dentro de la consola" if c.modelo == "integrado"
             else "en su propio contenedor, en los servidores de la plataforma")
    return (f'<div class="mk-datos dentro"><b>Tus datos no salen de la plataforma</b>Lo mantiene {quien} y corre '
            f'{donde}. Solo ve lo que le permitas.</div>')


def _receta(rid: str) -> str:
    f = _FLUJOS / f"{rid}.yaml"
    try:
        return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("nombre") or rid
    except (OSError, ValueError):
        return rid


def _usa(c) -> List[str]:
    return ([PIEZAS_NUCLEO.get(u, u) for u in c.usa] + [f"Capacidad · {x}" for x in c.requiere]
            + [f"Receta · {_receta(x)}" for x in c.recetas])


def _estado(c, act: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Su activación en esta institución, o None."""
    return None if act is None else (act.get("detalle") or {}).get(c.id)


def _puede_usar(det: Optional[Dict[str, Any]], roles: List[str]) -> bool:
    return bool(det) and (det.get("roles") is None or bool(set(det["roles"]) & set(roles)))


def _quien(det: Dict[str, Any]) -> str:
    if det.get("roles") is None:
        return "Todo tu equipo"
    return ", ".join(n for r, n in ROLES if r in det["roles"]) or "Nadie"


# ---------- escaparate ----------
def escaparate(productos: List[Any], act: Optional[Dict[str, Any]], quien: Any) -> str:
    oficios = [o for o in OFICIOS if any(c.oficio == o for c in productos)]
    chips = "".join(f'<button type="button" class="chip" data-oficio="{e(o)}" aria-pressed="{str(o == "Todos").lower()}">{e(o)}</button>'
                    for o in ["Todos"] + oficios)
    tarjetas = []
    for c in productos:
        det = _estado(c, act)
        estado = '<span class="pill ok">activado</span>' if det else ""
        tarjetas.append(f"""<article class="tarjeta mk-tarjeta" data-oficio="{e(c.oficio)}" data-fuera="{str(c.datos_salen).lower()}" style="--producto:{e(c.color)}">
<div style="display:flex;justify-content:space-between;gap:8px">{_modelo(c)}{estado}</div>
<div><h2>{e(c.nombre)}</h2><span class="mk-autor">{e(c.autor)}</span></div>
<p style="margin:0;flex-grow:1">{e(c.resumen)}</p>
<div class="mk-etqs"><span>{e(c.oficio)}</span>{f"<span>{e(c.precio)}</span>" if MOSTRAR_PRECIOS else ""}</div>
<a class="btn sec" href="/panel/marketplace/{e(c.id)}" style="align-self:flex-start">Ver ficha</a></article>""")
    caido = ('<p class="aviso">No sé qué tiene activado tu institución: el servicio de instituciones no responde.</p>'
             if act is None else "")
    return f"""{caido}<div class="mk-filtros" role="group" aria-label="Filtrar">
<span style="color:var(--muted);font-size:14px">Oficio</span>{chips}
<label><input type="checkbox" id="solo-dentro"> Mis datos no salen de la plataforma</label></div>
<section class="mk-rejilla" aria-label="Productos" style="margin-top:16px">{''.join(tarjetas) or '<p class="vacio">No hay productos.</p>'}</section>
<p class="vacio" id="sin-resultados" hidden>Ningún producto cumple esos filtros.</p>
{publicar_seccion()}"""


SCRIPT_ESCAPARATE = r"""
let oficio = 'Todos';
function filtrar() {
  const dentro = $('#solo-dentro').checked;
  let n = 0;
  document.querySelectorAll('.mk-tarjeta').forEach(t => {
    const ver = (oficio === 'Todos' || t.dataset.oficio === oficio) && !(dentro && t.dataset.fuera === 'true');
    t.hidden = !ver; n += ver ? 1 : 0;
  });
  $('#sin-resultados').hidden = n > 0;
}
document.querySelectorAll('.chip').forEach(b => b.onclick = () => {
  oficio = b.dataset.oficio;
  document.querySelectorAll('.chip').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  filtrar();
});
$('#solo-dentro').onchange = filtrar;
"""


def publicar_seccion() -> str:
    return """<section class="tarjeta" id="publicar" aria-labelledby="t-publicar" style="margin-top:24px">
<div class="cab"><h2 id="t-publicar">Publicar un producto</h2></div>
<div class="rejilla" style="--min:320px"><ol class="pasos-c">
<li>Crea <span class="mono">productos/&lt;id&gt;/producto.yaml</span>: quién lo hace, para qué oficio, <b>dónde corre</b>
(<span class="mono">integrado</span>, <span class="mono">alojado</span> o <span class="mono">externo</span>) y <b>qué permisos pide</b>.</li>
<li>Si es integrado, escribe <span class="mono">productos/&lt;id&gt;/__init__.py</span> con <span class="mono">montar(nucleo, producto)</span>.
Si es externo, basta su <span class="mono">url</span>: la plataforma no ejecuta nada suyo.</li>
<li>Envíalo al equipo del PaaS. Hoy la revisión es a mano; aparecerá aquí al reconstruir la consola.</li></ol>
<pre class="manifiesto">id: scriptorium
nombre: Scriptorium
autor: Ameyalli · Lancaster y Monterrey
oficio: Investigación
modelo: externo
url: https://scriptorium-nsf.appincubator.dev
requiere: [corrector-htr, modernizador-paleografico]
recetas: [edicion-anotada]
permisos:
  - {id: expedientes-lectura, texto: Leer expedientes}
  - {id: ediciones, texto: Guardar ediciones, opcional: true}</pre></div></section>"""


# ---------- ficha ----------
def ficha(c, act: Optional[Dict[str, Any]], quien: Any) -> str:
    det = _estado(c, act)
    admin = quien.tiene("admin-institucion")
    if act is None:
        accion = '<p class="aviso" style="margin:0">El servicio de instituciones no responde: prueba en un momento.</p>'
    elif det:
        usar = ""
        if _puede_usar(det, list(quien.roles)):
            usar = (f'<a class="btn" href="{e(c.entrada)}" target="_blank" rel="noopener">Abrir {e(c.nombre)} ↗</a>' if c.externo
                    else f'<a class="btn" href="{e(c.entrada)}">Abrir {e(c.nombre)}</a>')
        accion = (f'<span class="pill ok">Activado en tu institución</span>{usar}'
                  f'<a class="btn sec" href="/panel/mis-productos">Ver en Mis productos</a>')
    elif admin:
        accion = f'<a class="btn grande" href="/panel/marketplace/{e(c.id)}/activar">Activar en mi institución</a>'
    else:
        accion = '<p style="margin:0;color:var(--muted)">Pide a quien administra tu institución que lo active.</p>'
    permisos = "".join(f'<div class="mk-permiso">{CANDADO}<span>{e(x.texto)}'
                       f'<small>{e(x.detalle)}{" · opcional" if x.opcional else ""}</small></span></div>' for x in c.permisos) \
        or '<p style="margin:0;color:var(--muted)">No pide permisos sobre tus datos.</p>'
    usa = "".join(f"<span>{e(u)}</span>" for u in _usa(c))
    vistas = ""
    if c.vistas:
        vistas = ('<section class="tarjeta"><h2>Sus pantallas</h2><div class="mk-etqs">'
                  + "".join(f"<span>{e(v.nombre)}</span>" for v in c.vistas) + "</div></section>")
    precio = (f'<span style="color:var(--muted);font-size:13px">Precio</span><b style="font-size:19px">{e(c.precio)}</b>'
              if MOSTRAR_PRECIOS else "")
    return f"""<p style="margin:0 0 12px"><a href="/panel/productos">← Marketplace</a></p>
<div class="mk-cab"><div style="max-width:720px">{_modelo(c)}<h1>{e(c.nombre)}</h1>
<span class="mk-autor">{e(c.autor)} · versión {e(c.version)} · {e(c.oficio)}</span>
<p style="font-size:17px;margin:10px 0 0">{e(c.descripcion)}</p></div>
<div class="tarjeta mk-precio">{precio}{accion}</div></div>
<div class="mk-ficha" style="margin-top:20px">
<section class="tarjeta"><h2>Qué permisos pide</h2>{permisos}</section>
<section><h2 style="margin:0 0 10px;font-size:17px">Dónde van tus datos</h2>{_datos(c)}</section>
<section class="tarjeta"><h2>Qué usa de la plataforma</h2><div class="mk-etqs">{usa or '<span>—</span>'}</div></section>
{vistas}</div>"""


# ---------- activar (o revisar permisos) ----------
def activar(c, act: Optional[Dict[str, Any]], quien: Any) -> str:
    det = _estado(c, act) or {}
    concedidos = det.get("permisos")
    roles = det.get("roles")
    filas = "".join(
        f'<label><input type="checkbox" name="permiso" value="{e(x.id)}"'
        f'{" checked" if (concedidos is None or x.id in concedidos or not x.opcional) else ""}'
        f'{" disabled" if not x.opcional else ""}><span>{e(x.texto)}<small style="display:block;color:var(--muted)">'
        f'{e(x.detalle)} · {"opcional" if x.opcional else "imprescindible"}</small></span></label>' for x in c.permisos) \
        or '<p style="margin:0;color:var(--muted)">No pide permisos sobre tus datos.</p>'
    por_defecto = ["archivera", "paleografa"]
    rol = "".join(f'<label><input type="checkbox" name="rol" value="{r}"'
                  f'{" checked" if (r in roles if roles is not None else r in por_defecto) else ""}> {n}</label>' for r, n in ROLES)
    accion = "Guardar cambios" if det else "Aceptar y activar"
    return f"""<p style="margin:0 0 12px"><a href="/panel/marketplace/{e(c.id)}">← {e(c.nombre)}</a></p>
<form class="tarjeta mk-activar" id="f-activar" data-producto="{e(c.id)}" data-nombre="{e(c.nombre)}">
<div>{_modelo(c)}<h1 style="margin:8px 0 4px;font:600 26px/1.2 var(--display)">{e(c.nombre)} quiere acceso a tu institución</h1>
<p style="margin:0;color:var(--muted)">Solo podrá hacer esto, y solo con los datos de <b>{e(quien.tenant)}</b>.
Puedes cambiarlo o retirarlo cuando quieras en Mis productos.</p></div>
<fieldset><legend>Permisos</legend>{filas}</fieldset>
<fieldset><legend>Quién de tu equipo puede usarlo</legend><div class="mk-roles">{rol}</div></fieldset>
{_datos(c)}
<div class="mk-acciones" style="justify-content:flex-end">
<a class="btn sec grande" href="/panel/marketplace/{e(c.id)}">Cancelar</a>
<button class="btn grande" type="submit">{accion}</button></div></form>"""


SCRIPT_ACTIVAR = r"""
$('#f-activar').onsubmit = async ev => {
  ev.preventDefault();
  const f = ev.target, id = f.dataset.producto;
  const permisos = [...f.querySelectorAll('input[name=permiso]:checked')].map(i => i.value);
  const roles = [...f.querySelectorAll('input[name=rol]:checked')].map(i => i.value);
  try {
    await api(`/panel/api/instituciones/activaciones/${encodeURIComponent(id)}`, {method: 'PUT',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({activo: true, permisos, roles})});
    location.href = `/panel/mis-productos?hecho=${encodeURIComponent(f.dataset.nombre)}`;
  } catch (e) { aviso(e.message); }
};
"""


# ---------- Mis productos ----------
def mis_productos(productos: List[Any], act: Optional[Dict[str, Any]], quien: Any) -> str:
    if act is None:
        return '<p class="aviso">El servicio de instituciones no responde: prueba en un momento.</p>'
    admin = quien.tiene("admin-institucion")
    filas = []
    for c in productos:
        det = _estado(c, act)
        if not det:
            continue
        concedidos = [x.texto for x in c.permisos if x.id in (det.get("permisos") or [])]
        acciones = f'<a class="btn sec" href="/panel/marketplace/{e(c.id)}">Ver ficha</a>'
        if _puede_usar(det, list(quien.roles)):
            fuera = ' target="_blank" rel="noopener"' if c.externo else ""
            flecha = " ↗" if c.externo else ""
            acciones = f'<a class="btn" href="{e(c.entrada)}"{fuera}>Abrir{flecha}</a>' + acciones
        if admin:
            acciones += (f'<a class="btn sec" href="/panel/marketplace/{e(c.id)}/activar">Revisar permisos</a>'
                         f'<button type="button" class="btn peligro" data-desactivar="{e(c.id)}" data-nombre="{e(c.nombre)}">Desactivar</button>')
        desde = f' · activado por {e(det["por"])}' if det.get("por") else ""
        filas.append(f"""<article class="tarjeta mk-mis" style="border-left:4px solid {e(c.color)}">
<div style="flex:1 1 220px">{_modelo(c)}<b style="font-size:18px">{e(c.nombre)}</b><span class="mk-autor">{e(c.autor)}{desde}</span></div>
<div style="flex:2 1 300px;font-size:14px"><span style="color:var(--muted)">Permisos concedidos</span>
{''.join(f'<span>· {e(t)}</span>' for t in concedidos) or '<span>Ninguno sobre tus datos</span>'}</div>
<div style="flex:1 1 150px;font-size:14px"><span style="color:var(--muted)">Lo usan</span><span>{e(_quien(det))}</span></div>
<div class="mk-acciones">{acciones}</div></article>""")
    vacio = ('<p class="vacio">Tu institución no tiene productos activados. '
             '<a href="/panel/productos">Búscalos en el Marketplace</a>.</p>')
    antigua = ("" if act.get("gestionada") else
               '<p class="aviso ok">Tu institución es anterior al Marketplace: tiene todos los productos activados, '
               'con todos sus permisos. Al cambiar cualquiera, pasa a gestionarlos desde aquí.</p>')
    return f"""{antigua}<div style="display:flex;flex-direction:column;gap:12px">{''.join(filas) or vacio}</div>
<p style="color:var(--muted);font-size:14px;margin-top:16px">Desactivar un producto no borra nada: lo que ha hecho
(expedientes, transcripciones, ediciones) es de tu institución y sigue en la plataforma.</p>"""


SCRIPT_MIS = r"""
const hecho = new URLSearchParams(location.search).get('hecho');
if (hecho) aviso(`${hecho} activado. Ya aparece en la barra de quienes pueden usarlo.`, true);
document.querySelectorAll('[data-desactivar]').forEach(b => b.onclick = async () => {
  if (!confirm(`¿Desactivar ${b.dataset.nombre}? Tus datos se quedan en la plataforma.`)) return;
  try {
    await api(`/panel/api/instituciones/activaciones/${encodeURIComponent(b.dataset.desactivar)}`, {method: 'PUT',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({activo: false})});
    location.reload();
  } catch (e) { aviso(e.message); }
});
"""

