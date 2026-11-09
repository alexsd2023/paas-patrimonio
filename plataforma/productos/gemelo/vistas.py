"""Las vistas del producto del gemelo (HTML y JS). La consola del núcleo las envuelve con su barra y su cabecera."""

ESTILO = r"""
.deps{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:16px}
.dep{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;display:grid;gap:12px;min-width:0;box-shadow:inset 4px 0 0 var(--producto)}
.dep.alerta{border-color:var(--red);box-shadow:inset 4px 0 0 var(--red)}
.dep .top{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.lecturas{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.lectura .num{font:600 30px/1 var(--display);font-variant-numeric:tabular-nums}
.lectura .num small{font:500 14px var(--sans);color:var(--muted);margin-left:3px}
.lectura .rango{font:12px var(--mono);color:var(--muted)}
.lectura.fuera .num{color:var(--red)}
.lectura svg{width:100%;height:46px;display:block;margin-top:6px}
.dep .pie{display:flex;flex-wrap:wrap;gap:6px 14px;justify-content:space-between;align-items:center;color:var(--muted);font-size:13px}
.esc-btns{display:flex;gap:6px;flex-wrap:wrap}
.esc-btns button{font:500 12px var(--mono);padding:5px 9px;border-radius:999px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer}
.esc-btns button[aria-pressed="true"]{background:var(--ochre-t);border-color:var(--ochre)}
.banda-alerta{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between;padding:14px 18px;border-radius:10px;background:var(--red-t);border:1px solid var(--red)}
"""

DEPOSITOS = """<div id="banda" class="banda-alerta" role="alert" hidden></div>
<section aria-labelledby="t-dep"><div class="cab"><h2 id="t-dep">Depósitos</h2><span class="eyebrow">lecturas cada 5 s</span></div>
<div class="deps" id="deps"><p class="vacio">Cargando…</p></div></section>"""

SCRIPT_DEPOSITOS = r"""
const BASE = CFG.base;
function spark(serie, k, lo, hi) {
  const xs = serie.map(p => p[k]).filter(x => typeof x === 'number');
  if (xs.length < 2) return '<svg viewBox="0 0 260 46" aria-hidden="true"></svg>';
  const vmin = Math.min(...xs, lo ?? Infinity) - 1, vmax = Math.max(...xs, hi ?? -Infinity) + 1;
  const X = i => 2 + i * 256 / (xs.length - 1), Y = val => 44 - (val - vmin) / (vmax - vmin) * 42;
  const band = (lo != null && hi != null) ? `<rect x="0" y="${Y(hi)}" width="260" height="${Y(lo) - Y(hi)}" fill="var(--teal-t)"/>` : '';
  const fuera = (lo != null && xs.at(-1) < lo) || (hi != null && xs.at(-1) > hi);
  const c = fuera ? 'var(--red)' : 'var(--teal)';
  const d = xs.map((x, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(x).toFixed(1)}`).join('');
  return `<svg viewBox="0 0 260 46" preserveAspectRatio="none" role="img" aria-label="Evolución de ${k}">${band}<path d="${d}" fill="none" stroke="${c}" stroke-width="2" vector-effect="non-scaling-stroke"/><circle cx="${X(xs.length - 1)}" cy="${Y(xs.at(-1))}" r="3.5" fill="${c}"/></svg>`;
}
async function cargar() {
  let ds;
  try { ds = await api(BASE + '/api/depositos'); } catch (e) { $('#deps').innerHTML = `<p class="vacio">${esc(e.message)}</p>`; return; }
  if (!ds.length) { $('#deps').innerHTML = '<p class="vacio">Tu institución aún no tiene depósitos en el catastro. Los sensores los inscriben al arrancar.</p>'; return; }
  const enAlerta = ds.filter(d => d.estado === 'alerta');
  $('#banda').hidden = !enAlerta.length;
  $('#banda').innerHTML = enAlerta.map(d => `<span><strong>Alerta en ${esc(d.nombre)}.</strong> ${esc(d.alertas.join(', ') || 'revisar')} · afecta a ${d.legajos} ${d.legajos === 1 ? 'legajo' : 'legajos'}.</span>`).join('')
    + `<a href="${BASE}/cajas" style="font-weight:600;color:var(--red)">Ver cajas y legajos afectados</a>`;
  $('#deps').innerHTML = ds.map(d => {
    const u = d.umbrales || {};
    const lect = (k, val, uni, lo, hi) => {
      const fuera = typeof val === 'number' && ((lo != null && val < lo) || (hi != null && val > hi));
      return `<div class="lectura ${fuera ? 'fuera' : ''}"><div class="num">${val == null ? '—' : NUM.format(val)}<small>${uni}</small></div>
        <div class="rango">${k} · ${lo ?? '?'}–${hi ?? '?'} ${uni}</div>${spark(d.serie, k, lo, hi)}</div>`;
    };
    const alerta = d.estado === 'alerta';
    const btns = CFG.roles.includes('archivera') ? `<div class="esc-btns" role="group" aria-label="Simular en ${esc(d.nombre)}">${[['normal','Normal'],['fuga','Fuga de agua'],['calor','Avería del clima']].map(([e, t]) =>
      `<button type="button" data-dep="${esc(d.codigo)}" data-esc="${e}" aria-pressed="${d.escenario === e}">${t}</button>`).join('')}</div>` : '';
    return `<article class="dep ${alerta ? 'alerta' : ''}">
      <div class="top"><h3>${esc(d.nombre)}</h3><span class="pill ${alerta ? 'alerta' : 'ok'}">${alerta ? 'alerta · ' + esc(d.alertas.join(', ') || 'revisar') : 'en rango'}</span></div>
      <div class="lecturas">${lect('temperatura', d.temperatura, '°C', u.temperaturaMin, u.temperaturaMax)}${lect('humedad', d.humedad, '%', u.humedadMin, u.humedadMax)}</div>
      <div class="pie"><span>${d.cajas.length} ${d.cajas.length === 1 ? 'caja' : 'cajas'} · ${d.legajos} ${d.legajos === 1 ? 'legajo' : 'legajos'}</span>${btns}</div></article>`;
  }).join('');
  document.querySelectorAll('.esc-btns button').forEach(b => b.onclick = async () => {
    try { await api(BASE + '/api/escenario', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({deposito: b.dataset.dep, escenario: b.dataset.esc})}); }
    catch (e) { aviso(e.message); }
    cargar();
  });
}
cargar(); setInterval(cargar, 4000);
"""

CAJAS = """<section class="tarjeta" aria-labelledby="t-cajas"><div class="cab"><h2 id="t-cajas">Cajas y legajos</h2>
<span class="eyebrow">dónde está cada legajo y en qué condiciones</span></div><div id="cajas"><p class="vacio">Cargando…</p></div></section>"""

SCRIPT_CAJAS = r"""
const BASE = CFG.base;
async function cargar() {
  let cs;
  try { cs = await api(BASE + '/api/cajas'); } catch (e) { $('#cajas').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  if (!cs.length) { $('#cajas').innerHTML = '<p class="vacio">No hay cajas en el catastro de tu institución.</p>'; return; }
  $('#cajas').innerHTML = `<div class="tabla"><table><thead><tr><th>Depósito</th><th>Caja</th><th>Condiciones</th><th>Legajos</th></tr></thead><tbody>${
    cs.map(c => `<tr><td>${esc(c.deposito)}</td><td class="mono">${esc(c.caja)}</td>
      <td><span class="pill ${c.estado === 'alerta' ? 'alerta' : 'ok'}">${c.temperatura == null ? '' : NUM.format(c.temperatura) + ' °C · '}${c.humedad == null ? '' : NUM.format(c.humedad) + ' %'}</span></td>
      <td class="mono">${c.legajos.map(esc).join(', ') || '<span style="color:var(--muted)">vacía</span>'}</td></tr>`).join('')}</tbody></table></div>`;
}
cargar(); setInterval(cargar, 5000);
"""
