"""Las vistas del producto del legajo (HTML y JS). La consola del núcleo las envuelve con su barra y su cabecera."""
import html

ESTILO = r"""
.dos-col{display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:20px;align-items:start}
@media (max-width:980px){.dos-col{grid-template-columns:1fr}}
.lista{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.fila{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:12px 14px;border-bottom:1px solid var(--line-2);cursor:pointer}
.fila:last-child{border-bottom:0}
.fila:hover{background:var(--bg)}
.fila[aria-current="true"]{background:color-mix(in srgb,var(--producto) 16%,var(--card))}
.fila .sig{font:500 15px var(--mono)}
.fila .sub{grid-column:1/-1;color:var(--muted);font-size:13px}
.detalle h2{font-size:26px}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:13px;margin:6px 0 16px}
.minis{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px;margin-bottom:18px}
.minis img{height:150px;width:auto;max-width:none;border:1px solid var(--line);border-radius:6px;background:var(--bg)}
.recorrido{list-style:none;margin:0;padding:0;position:relative}
.recorrido li{display:grid;grid-template-columns:64px 22px 1fr;gap:0 12px;padding:0 0 18px;position:relative}
.recorrido li::before{content:"";position:absolute;left:86px;top:22px;bottom:-2px;width:2px;background:var(--line)}
.recorrido li:last-child::before{display:none}
.esc{font:500 12px var(--mono);color:var(--muted);padding-top:3px;text-align:right;white-space:nowrap}
.marca{width:22px;height:22px;border-radius:50%;border:2px solid var(--line);background:var(--card);margin-top:1px;position:relative;z-index:1}
.hecho .marca{background:var(--teal);border-color:var(--teal)}
.hecho .marca::after{content:"";position:absolute;left:6px;top:2px;width:5px;height:10px;border:solid var(--card);border-width:0 2.5px 2.5px 0;transform:rotate(45deg)}
.esperando .marca{border-color:var(--ochre);background:var(--ochre-t);animation:latido 1.6s ease-in-out infinite}
@keyframes latido{50%{box-shadow:0 0 0 6px color-mix(in srgb,var(--ochre) 25%,transparent)}}
@media (prefers-reduced-motion:reduce){.esperando .marca{animation:none}}
.paso .n{font-weight:600}
.paso .d{color:var(--muted);font-size:14px}
.pendiente .n{color:var(--muted);font-weight:500}
.paso .t{font:12px var(--mono);color:var(--muted)}
.accion{margin-top:8px}
.bloque{margin-top:22px;border-top:1px solid var(--line);padding-top:16px}
.bloque h3{margin:0 0 8px}
blockquote{margin:0;font:italic 17px/1.6 var(--display);border-left:3px solid var(--ochre);padding-left:14px}
.ubic{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;font-size:14px;margin:-6px 0 16px;padding:10px 12px;border-radius:8px;background:var(--bg)}
.ubic.alerta{background:var(--red-t)}
.vacio-detalle{color:var(--muted);padding:40px 8px;text-align:center}
.linaje{display:grid;gap:4px;margin-top:10px;padding:10px 12px;border-radius:8px;background:var(--bg);font-size:14px}
form.entrega{display:grid;gap:14px;max-width:560px}
.pestanas .cuenta:not(:empty){margin-left:6px;font:500 12px var(--mono);padding:1px 7px;border-radius:999px;background:var(--ochre-t);color:var(--ochre)}
.copia{display:grid;gap:10px;border-bottom:1px solid var(--line-2);padding:16px 0}
.copia:last-child{border-bottom:0}
.tramo{display:grid;grid-template-columns:32px 110px minmax(0,1fr) auto;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--line-2)}
.tramo:last-child{border-bottom:0}
"""

# Común a todas las vistas del producto: API del producto y el contador de copias por firmar en la pestaña «Validar».
SCRIPT = r"""
const BASE = CFG.base;
const ES_ARCHIVERA = CFG.roles.includes('archivera'), ES_PALEOGRAFA = CFG.roles.includes('paleografa');
async function contarPendientes() {
  try { const p = await api(BASE + '/api/pendientes'); const n = document.querySelector('.cuenta[data-vista="validar"]'); if (n) n.textContent = p.length || ''; } catch (e) {}
}
contarPendientes(); setInterval(contarPendientes, 6000);
"""

LEGAJOS = """<div class="dos-col">
<section aria-labelledby="t-leg"><div class="cab"><h2 id="t-leg">Legajos <span class="mono" id="cuenta"></span></h2>
<a class="btn sec" href="legajo/entregar" id="ir-entregar">Entregar legajo</a></div>
<div class="lista" id="lista"><p class="vacio">Cargando…</p></div></section>
<section aria-live="polite"><div class="tarjeta detalle" id="detalle"><p class="vacio-detalle">Elige un legajo para ver su recorrido.</p></div></section>
</div>"""

SCRIPT_LEGAJOS = r"""
document.getElementById('ir-entregar').href = BASE + '/entregar';
if (!ES_ARCHIVERA) document.getElementById('ir-entregar').hidden = true;
let sel = null;
try { sel = sessionStorage.getItem('legajo'); } catch (e) {}
async function cargarLista() {
  let filas;
  try { filas = await api(BASE + '/api/legajos'); } catch (e) { $('#lista').innerHTML = `<p class="vacio">No se pudo leer el catastro: ${esc(e.message)}</p>`; return; }
  $('#cuenta').textContent = filas.length ? `${filas.length}` : '';
  if (!filas.length) {
    $('#lista').innerHTML = `<p class="vacio">Tu institución aún no tiene legajos. ${ES_ARCHIVERA ? 'Entrega el primero en «Entregar».' : 'Aparecerán aquí cuando una archivera entregue uno.'}</p>`;
    return;
  }
  if (!sel || !filas.some(f => f.activo === sel)) sel = filas[0].activo;
  $('#lista').innerHTML = filas.map(f => `
    <div class="fila" role="button" tabindex="0" data-a="${esc(f.activo)}" aria-current="${f.activo === sel}">
      <span class="sig">${esc(f.signatura)}</span>
      <span class="pill ${f.estado === 'validada' ? 'validada' : f.estado === 'pendiente' ? 'pendiente' : ''}">${esc(f.estado)}</span>
      <span class="sub">${esc(f.imagenes)} imágenes · ${esc(f.ingestadoPor)} · ${fecha(f.creado)}</span>
    </div>`).join('');
  document.querySelectorAll('.fila').forEach(el => {
    const elegir = () => { sel = el.dataset.a; try { sessionStorage.setItem('legajo', sel); } catch (e) {} cargarLista(); };
    el.onclick = elegir; el.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); elegir(); } };
  });
  cargarDetalle();
}
async function cargarDetalle() {
  if (!sel) return;
  let d;
  try { d = await api(BASE + '/api/legajo?activo=' + encodeURIComponent(sel)); }
  catch (e) { $('#detalle').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  const r = d.resumen;
  const puedeFirmar = ES_PALEOGRAFA && d.proceso && d.proceso.estado === 'pendiente-validacion';
  const enlaces = [
    d.visor ? `<a href="${esc(d.visor)}" target="_blank" rel="noopener">Ver en el visor IIIF</a>` : '',
    d.temporal ? `<a href="${esc(d.temporal)}" target="_blank" rel="noopener">Ver el proceso en Temporal</a>` : '',
    d.manifiesto ? `<a href="${esc(d.manifiesto)}" target="_blank" rel="noopener">Manifiesto</a>` : '',
  ].filter(Boolean).join('');
  const u = d.ubicacion;
  $('#detalle').innerHTML = `
    ${d.avisos.map(a => `<p class="aviso" style="margin-bottom:10px">${esc(a)}</p>`).join('')}
    <p class="eyebrow" style="margin:0">Legajo</p>
    <h2 class="mono">${esc(r.signatura)}</h2>
    <div class="meta"><span class="mono">${esc(d.ark)}</span><span class="mono">${esc(r.activo)}</span></div>
    ${enlaces ? `<div class="meta">${enlaces}</div>` : ''}
    ${u ? `<div class="ubic ${u.estado === 'alerta' ? 'alerta' : ''}"><strong>${esc(u.deposito)}</strong><span class="mono">caja ${esc(u.caja)}</span>
      <span class="mono">${u.temperatura == null ? '' : NUM.format(u.temperatura) + ' °C · '}${u.humedad == null ? '' : NUM.format(u.humedad) + ' %'}</span>
      <span class="pill ${u.estado === 'alerta' ? 'alerta' : 'ok'}">${u.estado === 'alerta' ? 'condiciones fuera de rango' : 'condiciones en rango'}</span></div>`
      : `<div class="ubic"><span>Sin ubicación física registrada.</span></div>`}
    <div class="minis"></div>
    <ol class="recorrido">${d.pasos.map(p => `
      <li class="paso ${p.estado}">
        <span class="esc">esc. ${esc(p.escena)}</span><span class="marca" aria-hidden="true"></span>
        <div><div class="n">${esc(p.nombre)}</div><div class="d">${esc(p.detalle ?? '')}</div>
        ${p.cuando ? `<div class="t">${fecha(p.cuando)}</div>` : ''}
        ${p.nombre === 'La paleógrafa firma' && puedeFirmar ? `<div class="accion"><button class="btn" id="firmar">Firmar la copia</button></div>` : ''}
        </div></li>`).join('')}
    </ol>
    ${d.copia && d.copia.texto ? `<div class="bloque"><h3>La copia del taller</h3>
      <blockquote>${esc(d.copia.texto)}</blockquote>
      <div class="meta"><span>${esc(d.copia.modelo)} · ${esc(d.copia.lineas)} líneas · confianza ${esc(d.copia.confianza)}</span><span>${d.copia.estado === 'validada' ? 'validada por ' + esc(d.copia.validadoPor) : 'pendiente de validar por una paleógrafa'}</span></div>
      ${d.copia.modeloRun ? `<div class="linaje"><span class="eyebrow">De dónde sale esta copia</span>
        <span>Modelo <b class="mono">${esc(d.copia.modelo)}</b>${d.copia.cerModelo != null ? ` · CER ${NUM.format(d.copia.cerModelo * 100)} %` : ''}</span>
        <span>Entrenado en el run <span class="mono">${esc(d.copia.modeloRun.slice(0, 8))}</span> con los datos <span class="mono">${esc((d.copia.datosVersion || '').slice(0, 10))}</span> (DVC)</span>
        ${d.copia.modeloUrl ? `<a href="${esc(d.copia.modeloUrl)}" target="_blank" rel="noopener">Ver el modelo en MLflow</a>` : ''}</div>` : ''}</div>` : ''}
    <div class="bloque"><h3>Libro del notario</h3>${d.actas.length ? `<div class="tabla"><table><thead><tr><th>Acta</th><th>Cuándo</th><th>Quién</th><th>Detalle</th></tr></thead><tbody>
      ${d.actas.map(a => `<tr><td>${esc(a.tipo)}</td><td class="mono">${fecha(a.tiempo)}</td><td class="mono">${(a.agentes || []).map(x => esc(x.split(/[:/]/).pop())).join(', ')}</td><td>${esc(a.detalle || '')}</td></tr>`).join('')}
      </tbody></table></div>` : '<p class="vacio">Aún no hay actas de este legajo.</p>'}</div>`;
  const cont = document.querySelector('.minis');
  cont.innerHTML = (d.miniaturas || []).map((m, i) => `<img src="${esc(m)}" alt="Imagen ${i + 1} del legajo ${esc(r.signatura)}" loading="lazy">`).join('');
  if (!cont.innerHTML) cont.remove();
  const b = $('#firmar');
  if (b) b.onclick = () => firmar(sel, b).then(cargarLista);
}
async function firmar(activo, b) {
  b.disabled = true; b.textContent = 'Firmando…';
  try { await api(BASE + '/api/validar', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({activo})}); aviso('Copia firmada. El notario levantará el acta.', true); }
  catch (e) { aviso(e.message); b.disabled = false; b.textContent = 'Firmar la copia'; }
  contarPendientes();
}
cargarLista(); setInterval(cargarLista, 4000);
"""

ENTREGAR = """<section class="tarjeta" aria-labelledby="t-ent"><div class="cab"><h2 id="t-ent">Entregar un legajo</h2></div>
<p style="margin:0 0 16px;color:var(--muted)">La sala de lectura publica los folios como IIIF y los inscribe en el catastro.
Desde ahí el núcleo avisa por el bus, abre el proceso de transcripción y el notario empieza el libro del legajo.</p>
<form class="entrega" id="entrega">
<label>Signatura<input type="text" id="signatura" name="signatura" required pattern="[A-Za-z0-9-]{1,64}" placeholder="LEG-0001"></label>
<label>Imágenes del legajo<input type="file" id="imagenes" name="imagenes" accept="image/*" multiple required></label>
<label>Caja donde se guarda<select id="caja" name="caja"><option value="">Sin ubicar</option></select></label>
<div><button class="btn" type="submit">Entregar</button></div></form></section>"""

SOLO_ARCHIVERA = """<section class="tarjeta"><h2>Entregar un legajo</h2>
<p style="color:var(--muted)">Solo una archivera puede entregar legajos. Entra con un usuario con ese rol (por ejemplo <span class="mono">m.ortega</span>).</p></section>"""

SCRIPT_ENTREGAR = r"""
const f = $('#entrega');
if (f) {
  api(BASE + '/api/cajas').then(gs => {
    $('#caja').innerHTML = '<option value="">Sin ubicar</option>' + gs.map(g => `<optgroup label="${esc(g.deposito)}">${g.cajas.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}</optgroup>`).join('');
  }).catch(() => {});
  f.onsubmit = async ev => {
    ev.preventDefault();
    const btn = f.querySelector('button[type=submit]'); btn.disabled = true; btn.textContent = 'Entregando…';
    try {
      const r = await api(BASE + '/api/ingesta', {method:'POST', body: new FormData(f)});
      try { sessionStorage.setItem('legajo', r.activo); } catch (e) {}
      aviso(`Legajo entregado: ${r.imagenes} imágenes. Ábrelo en «Legajos» para seguir su recorrido.`, true);
      f.reset();
    } catch (e) { aviso(e.message); }
    btn.disabled = false; btn.textContent = 'Entregar';
  };
}
"""

VALIDAR = """<section class="tarjeta" aria-labelledby="t-val"><div class="cab"><h2 id="t-val">Copias esperando la firma</h2>
<span class="eyebrow" id="quien-firma"></span></div><div id="pendientes"><p class="vacio">Cargando…</p></div></section>"""

SCRIPT_VALIDAR = r"""
$('#quien-firma').textContent = ES_PALEOGRAFA ? 'puedes firmar' : 'solo una paleógrafa puede firmar';
async function cargarPendientes() {
  let ps;
  try { ps = await api(BASE + '/api/pendientes'); } catch (e) { $('#pendientes').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  if (!ps.length) { $('#pendientes').innerHTML = '<p class="vacio">No hay copias esperando la firma en tu institución.</p>'; return; }
  $('#pendientes').innerHTML = ps.map(p => `<article class="copia">
    <div class="cab" style="margin:0"><h3 class="mono">${esc(p.signatura)}</h3><span class="pill pendiente">esperando la firma</span></div>
    <blockquote>${esc(p.texto || '')}</blockquote>
    <div class="cab" style="margin:0"><span style="color:var(--muted);font-size:14px">${esc(p.modelo)} · ${esc(p.lineas)} líneas · confianza ${esc(p.confianza)} · ${fecha(p.creado)}</span>
    ${ES_PALEOGRAFA ? `<button class="btn" data-a="${esc(p.activo)}">Firmar la copia</button>` : ''}</div></article>`).join('');
  document.querySelectorAll('#pendientes button[data-a]').forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = 'Firmando…';
    try { await api(BASE + '/api/validar', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({activo: b.dataset.a})}); aviso('Copia firmada.', true); }
    catch (e) { aviso(e.message); }
    cargarPendientes(); contarPendientes();
  });
}
cargarPendientes(); setInterval(cargarPendientes, 5000);
"""


def tramos_html(tramos) -> str:
    from services.panel.productos import PIEZAS_NUCLEO
    e = html.escape
    hechos = sum(1 for t in tramos if t.get("hecho"))
    filas = []
    for n, t in enumerate(tramos, 1):
        pieza = PIEZAS_NUCLEO.get(t.get("pieza", ""), t.get("pieza", ""))
        estado = '<span class="pill validada">hecho</span>' if t.get("hecho") else \
            f'<span class="pill">parte {e(str(t.get("parte", "?")))}</span>'
        filas.append(f'<li class="tramo"><span class="mono" style="color:var(--muted)">{n:02d}</span>'
                     f'<span class="mono" style="font-size:12px;color:var(--producto)">{e(pieza.split(" · ")[0])}</span>'
                     f'<span>{e(t.get("texto", ""))}</span>{estado}</li>')
    return f"""<section class="tarjeta" aria-labelledby="t-tr"><div class="cab"><h2 id="t-tr">Tramos del producto · {hechos} de {len(tramos)}</h2>
<span style="color:var(--muted);font-size:13px">Cada tramo dice qué pieza del núcleo aporta. Se editan en <span class="mono">productos/legajo/producto.yaml</span>.</span></div>
<ol style="list-style:none;margin:0;padding:0">{''.join(filas)}</ol></section>"""
