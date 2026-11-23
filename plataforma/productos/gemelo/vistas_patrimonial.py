"""Vistas del gemelo patrimonial (HTML y JS). La consola del núcleo las envuelve con su barra y su cabecera.

Sin librerías: las gráficas y la planta son SVG dibujado aquí (funciona sin salir a internet, también en la demo).
"""

ESTILO = r"""
.gp-kpis{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));margin-bottom:20px}
.gp-zonas{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))}
.gp-zona{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;display:grid;gap:10px;
  box-shadow:inset 4px 0 0 var(--teal);text-decoration:none;color:inherit;min-width:0}
.gp-zona.medio{box-shadow:inset 4px 0 0 var(--ochre)} .gp-zona.alto{box-shadow:inset 4px 0 0 var(--red);border-color:var(--red)}
.gp-zona:hover{border-color:var(--ink)}
.gp-top{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.gp-top h3{margin:0;font:600 18px/1.25 var(--display)}
.gp-lect{display:flex;gap:18px;font:600 24px/1 var(--display);font-variant-numeric:tabular-nums}
.gp-lect small{font:500 13px var(--sans);color:var(--muted);margin-left:2px}
.gp-meta{color:var(--muted);font-size:13px}
.pill.bajo{background:var(--teal-t);border-color:var(--teal);color:var(--teal)}
.pill.medio{background:var(--ochre-t);border-color:var(--ochre);color:var(--ochre)}
.pill.alto{background:var(--red-t);border-color:var(--red);color:var(--red)}
.gp-graf{width:100%;height:auto;display:block}
.gp-graf text{font:12px var(--mono);fill:var(--muted)}
.gp-dos{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))}
.gp-dl{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;margin:0;font-size:14px}
.gp-dl dt{color:var(--muted)} .gp-dl dd{margin:0}
.gp-ley{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--muted);margin-top:6px}
.gp-ley i{display:inline-block;width:14px;height:8px;border-radius:2px;margin-right:5px;vertical-align:middle}
.gp-plano{width:100%;height:auto;display:block;background:var(--bg);border:1px solid var(--line);border-radius:10px}
.gp-plano a rect{cursor:pointer} .gp-plano text{font:2.2px var(--sans);fill:var(--ink)}
.gp-acc{display:flex;gap:6px;flex-wrap:wrap}
.gp-acc .btn{padding:4px 10px;font-size:13px}
.gp-form{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,160px),1fr));align-items:end}
.gp-form select,.gp-form input{min-width:0;width:100%;box-sizing:border-box}
.gp-actas{margin:8px 0 0;padding-left:18px;font-size:13px;color:var(--muted)}
.gp-nota{font-size:13px;color:var(--muted);margin:8px 0 0}
"""

_UTIL = r"""
const BASE = CFG.base;
const NIVEL = {bajo: 'riesgo bajo', medio: 'riesgo medio', alto: 'riesgo alto'};
const pillNivel = n => n ? `<span class="pill ${esc(n)}">${esc(NIVEL[n] || n)}</span>` : '<span class="pill">sin evaluar</span>';
const banda = b => b ? `${NUM.format(b[0])}–${NUM.format(b[1])}` : '—';
const fechaCorta = s => s ? new Date(s).toLocaleString('es-ES', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'}) : '';
const ORIGEN = {historico: 'lecturas reales', sintetico: 'histórico sintético', mixto: 'sintético + lecturas reales'};
"""

# ---------- Inicio ----------
INICIO = """<section id="sin-inmueble" class="tarjeta" hidden></section>
<p id="aviso-g" class="aviso" hidden></p>
<section class="gp-kpis" id="kpis" aria-label="Resumen del inmueble"></section>
<section aria-labelledby="t-zonas"><div class="cab"><h2 id="t-zonas">¿Qué zona me preocupa hoy y por qué?</h2>
<span class="eyebrow" id="edificio"></span></div>
<div class="gp-zonas" id="zonas"><p class="vacio">Cargando…</p></div></section>"""

SCRIPT_INICIO = _UTIL + r"""
async function cargar() {
  let d;
  try { d = await api(BASE + '/api/inmueble'); } catch (e) { $('#zonas').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  $('#aviso-g').hidden = !d.aviso; $('#aviso-g').textContent = d.aviso ? 'Conservación no responde: ' + d.aviso : '';
  if (!d.edificio) {
    $('#sin-inmueble').hidden = false;
    $('#sin-inmueble').innerHTML = `<p style="margin:0 0 12px">Tu institución aún no tiene su inmueble en el catastro.</p>` +
      (CFG.puedeConfigurar ? `<a class="btn" href="${BASE}/configuracion">Crear el inmueble de ejemplo</a>` : '<p class="gp-nota">Pídeselo a quien administra tu institución.</p>');
    $('#zonas').innerHTML = ''; $('#kpis').innerHTML = ''; return;
  }
  $('#sin-inmueble').hidden = true;
  const e = d.edificio, k = d.kpis;
  $('#edificio').textContent = `${e.nombre} · ${e.proteccion || ''} · ${e.ano || ''}`;
  const kpi = (n, t, pie, cls) => `<article class="tarjeta kpi"><div class="eyebrow">${t}</div><div class="num" ${cls ? `style="color:var(--${cls})"` : ''}>${n}</div><div class="pie">${pie}</div></article>`;
  $('#kpis').innerHTML = kpi(k.zonas, 'Zonas', 'del inmueble')
    + kpi(k.enRiesgo, 'En riesgo', 'nivel medio o alto', k.enRiesgo ? 'ochre' : '')
    + kpi(k.alertas, 'Alertas abiertas', `${k.criticas} de nivel alto · <a href="${BASE}/alertas">ver</a>`, k.criticas ? 'red' : '')
    + kpi(`${k.sensoresOK}/${k.sensores}`, 'Sensores', 'operativos · <a href="' + BASE + '/mapa">mapa</a>');
  $('#zonas').innerHTML = d.zonas.map(z => `<a class="gp-zona ${esc(z.nivel || '')}" href="${BASE}/zona?z=${encodeURIComponent(z.codigo)}">
    <div class="gp-top"><h3>${esc(z.nombre)}</h3>${pillNivel(z.nivel)}</div>
    <div class="gp-lect"><span>${z.temperatura == null ? '—' : NUM.format(z.temperatura)}<small>°C</small></span>
      <span>${z.humedad == null ? '—' : NUM.format(z.humedad)}<small>% HR</small></span></div>
    <div>${esc(z.causa || 'Aún sin evaluar')}</div>
    <div class="gp-meta">objetivo HR ${banda(z.objetivoHumedad)} % · T ${banda(z.objetivoTemperatura)} °C${z.alerta ? ` · <strong style="color:var(--red)">alerta ${esc(z.alerta.codigo)} ${esc(z.alerta.estado)}</strong>` : ''}</div>
    <div class="gp-meta">${esc(z.tipo || '')}${z.legajos != null ? ' · ' + z.legajos + ' legajos' : ''}${z.materiales && z.materiales.length ? ' · ' + esc(z.materiales.join(', ')) : ''}${z.calculadaEn ? ' · evaluada ' + fechaCorta(z.calculadaEn) : ''}</div></a>`).join('')
    || '<p class="vacio">El inmueble no tiene zonas.</p>';
}
cargar(); setInterval(cargar, 15000);
"""

# ---------- Zona ----------
ZONA = """<p style="margin:0 0 12px"><a id="volver">← Inicio</a></p>
<section class="tarjeta" style="margin-bottom:16px"><div class="cab" style="margin:0"><h2 id="t-zona">Zona</h2><span id="nivel"></span></div>
<p id="causa" style="margin:6px 0 0"></p><p id="meta" class="gp-nota"></p></section>
<div class="gp-dos">
 <section class="tarjeta"><div class="cab"><h2>Humedad relativa · 7 días</h2><span class="eyebrow">% HR</span></div><div id="g-h"></div></section>
 <section class="tarjeta"><div class="cab"><h2>Temperatura · 7 días</h2><span class="eyebrow">°C</span></div><div id="g-t"></div></section>
</div>
<p class="gp-ley"><span><i style="background:var(--teal-t);border:1px solid var(--teal)"></i>microclima objetivo (EN 15757)</span>
<span><i style="background:var(--ink)"></i>lecturas reales</span><span><i style="background:var(--muted);opacity:.6"></i>datos sintéticos</span></p>
<div class="gp-dos" style="margin-top:16px">
 <section class="tarjeta"><div class="cab"><h2>Evaluación vigente</h2><button class="btn sec" id="recalcular" type="button" hidden>Recalcular</button></div><dl class="gp-dl" id="eval"></dl></section>
 <section class="tarjeta"><div class="cab"><h2>Sensores</h2></div><div class="tabla"><table><thead><tr><th>Sensor</th><th>Estado</th><th>Ahora</th></tr></thead><tbody id="sens"></tbody></table></div>
 <h3 style="margin:16px 0 6px;font-size:15px">Elementos</h3><ul id="elems" style="margin:0;padding-left:18px"></ul></section>
</div>
<section class="tarjeta" id="archivo" style="margin-top:16px" hidden><div class="cab"><h2>Cajas y legajos de este depósito</h2><span class="eyebrow" id="archivo-dep"></span></div><div id="archivo-cajas"></div>
<p class="gp-nota">Una alerta de esta zona llega también al libro del notario de cada uno de estos legajos.</p></section>
<section class="tarjeta" style="margin-top:16px"><div class="cab"><h2>Alertas de esta zona</h2><a id="ir-alertas">Todas las alertas</a></div><div id="alertas-z"></div></section>"""

SCRIPT_ZONA = _UTIL + r"""
const COD = new URLSearchParams(location.search).get('z') || 'Z01';
$('#volver').href = BASE; $('#ir-alertas').href = BASE + '/alertas';
function grafica(serie, bandaEv, clave, kMin, kMax) {
  const W = 560, H = 230, iz = 42, de = 8, ar = 12, ab = 26;
  if (!serie.length) return '<p class="vacio">Sin datos todavía.</p>';
  const t0 = new Date(serie[0].t).getTime(), t1 = new Date(serie.at(-1).t).getTime() || t0 + 1;
  const b = (bandaEv || []).filter(p => { const t = new Date(p.t).getTime(); return t >= t0 - 6 * 3600e3 && t <= t1; });
  const vals = serie.map(p => p[clave]).concat(b.flatMap(p => [p[kMin], p[kMax]]));
  let lo = Math.min(...vals), hi = Math.max(...vals); const m = (hi - lo) * 0.08 || 1; lo -= m; hi += m;
  const X = t => iz + (new Date(t).getTime() - t0) / (t1 - t0 || 1) * (W - iz - de), Y = val => ar + (hi - val) / (hi - lo) * (H - ar - ab);
  let g = '';
  for (let i = 0; i <= 4; i++) { const val = lo + (hi - lo) * i / 4, y = Y(val).toFixed(1);
    g += `<line x1="${iz}" x2="${W - de}" y1="${y}" y2="${y}" stroke="var(--line-2)"/><text x="${iz - 6}" y="${+y + 4}" text-anchor="end">${NUM.format(val)}</text>`; }
  for (let t = Math.ceil(t0 / 864e5) * 864e5; t <= t1; t += 864e5) { const x = X(t).toFixed(1);
    g += `<line x1="${x}" x2="${x}" y1="${ar}" y2="${H - ab}" stroke="var(--line-2)"/><text x="${x}" y="${H - 8}" text-anchor="middle">${new Date(t).toLocaleDateString('es-ES', {day: '2-digit', month: 'short'})}</text>`; }
  if (b.length > 1) {
    const arriba = b.map(p => `${X(p.t).toFixed(1)},${Y(p[kMax]).toFixed(1)}`), abajo = b.slice().reverse().map(p => `${X(p.t).toFixed(1)},${Y(p[kMin]).toFixed(1)}`);
    g += `<polygon points="${arriba.concat(abajo).join(' ')}" fill="var(--teal-t)" stroke="var(--teal)" stroke-width="1" vector-effect="non-scaling-stroke" opacity=".9"/>`;
  }
  const tramo = (filtro, color, op) => { let d = '', prev = false;
    serie.forEach(p => { const ok = filtro(p); if (ok) d += `${prev ? 'L' : 'M'}${X(p.t).toFixed(1)} ${Y(p[clave]).toFixed(1)}`; prev = ok; });
    return d ? `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" opacity="${op}" vector-effect="non-scaling-stroke"/>` : ''; };
  g += tramo(p => (p.origen || '').includes('sintetico'), 'var(--muted)', .6) + tramo(p => !(p.origen || '').includes('sintetico'), 'var(--ink)', 1);
  return `<svg class="gp-graf" viewBox="0 0 ${W} ${H}" role="img" aria-label="Serie de ${clave} de 7 días con su banda objetivo">${g}</svg>`;
}
async function cargar() {
  let z;
  try { z = await api(`${BASE}/api/zonas/${encodeURIComponent(COD)}`); } catch (e) { $('#t-zona').textContent = e.message; return; }
  const ev = z.evaluacion;
  document.title = z.nombre + ' · Gemelo patrimonial';
  $('#t-zona').textContent = z.nombre; $('#nivel').innerHTML = pillNivel(ev && ev.nivel);
  $('#causa').textContent = ev ? ev.causa : 'Aún sin evaluar.';
  $('#meta').textContent = [z.tipo, (z.materiales || []).join(', '), z.area ? z.area + ' m²' : '', z.archivo ? `${z.archivo.legajos} legajos en ${z.archivo.cajas.length} cajas` : ''].filter(Boolean).join(' · ');
  $('#archivo').hidden = !z.archivo;
  if (z.archivo) {
    $('#archivo-dep').textContent = 'Depósito del archivo · ' + z.archivo.nombre;
    $('#archivo-cajas').innerHTML = z.archivo.cajas.length ? `<div class="tabla"><table><thead><tr><th>Caja</th><th>Legajos</th></tr></thead><tbody>${
      z.archivo.cajas.map(c => `<tr><td class="mono">${esc(c.caja)}</td><td>${c.legajos.length ? c.legajos.map(l => `<span class="mono">${esc(l)}</span>`).join(' · ') : '<span class="gp-meta">vacía</span>'}</td></tr>`).join('')}</tbody></table></div>` : '<p class="vacio">Este depósito aún no tiene cajas.</p>';
  }
  $('#g-h').innerHTML = grafica(z.serie, ev && ev.banda, 'humedad', 'hMin', 'hMax');
  $('#g-t').innerHTML = grafica(z.serie, ev && ev.banda, 'temperatura', 'tMin', 'tMax');
  $('#eval').innerHTML = ev ? `<dt>Método</dt><dd>${ev.metodo === 'en15757' ? 'EN 15757:2010 (media de 30 días, P7–P93, ±10 % HR)' : 'simplificado (v1.0)'}</dd>
    <dt>Datos</dt><dd>${esc(ORIGEN[ev.origenDatos] || ev.origenDatos)} · ${NUM.format(ev.periodo.calibracionDias)} días de calibración</dd>
    <dt>Objetivo HR</dt><dd>${banda(ev.humedad.objetivo)} % (media ${NUM.format(ev.humedad.media)} %)</dd>
    <dt>Objetivo T</dt><dd>${banda(ev.temperatura.objetivo)} °C (media ${NUM.format(ev.temperatura.media)} °C)</dd>
    <dt>Fuera de banda</dt><dd>HR ${NUM.format(ev.humedad.fuera30d)} % del tiempo (histórico ${NUM.format(ev.humedad.lineaBase)} %) · T ${NUM.format(ev.temperatura.fuera30d)} % (${NUM.format(ev.temperatura.lineaBase)} %)</dd>
    <dt>Desviación</dt><dd>${NUM.format(ev.desviacion30d)} puntos sobre su clima histórico</dd>
    <dt>Mayor salto de HR</dt><dd>${NUM.format(ev.fluctuacionMaxHR2h)} puntos en 2 horas</dd>
    <dt>Calculada</dt><dd>${fechaCorta(ev.calculadaEn)} · con la capacidad <span class="mono">evaluacion-en15757</span></dd>` : '<dd>Sin evaluación todavía.</dd>';
  $('#sens').innerHTML = z.sensores.map(s => `<tr><td>${esc(s.nombre)} <span class="mono" style="color:var(--muted)">${esc(s.codigo)}</span></td>
    <td><span class="pill ${s.estado === 'OK' ? 'ok' : 'pendiente'}">${esc(s.estado || '—')}</span></td>
    <td>${s.ahora ? `${NUM.format(s.ahora.temperatura)} °C · ${NUM.format(s.ahora.humedad)} % <span class="gp-meta">${fechaCorta(s.ahora.observadoEn)}</span>` : '—'}</td></tr>`).join('') || '<tr><td colspan="3">Sin sensores.</td></tr>';
  $('#elems').innerHTML = z.elementos.map(e => `<li>${esc(e.nombre)} · ${esc(e.material)} · <em>${esc(e.estado)}</em> (inspección ${esc(e.inspeccion)})</li>`).join('') || '<li>Ninguno registrado.</li>';
  $('#alertas-z').innerHTML = z.alertas.length ? `<div class="tabla"><table><thead><tr><th>Alerta</th><th>Nivel</th><th>Estado</th><th>Detectada</th><th>Causa</th></tr></thead><tbody>${
    z.alertas.sort((a, b) => (b.detectada || '').localeCompare(a.detectada || '')).map(a => `<tr><td class="mono">${esc(a.codigo)}</td><td>${pillNivel(a.nivel)}</td><td>${esc(a.estado)}</td><td>${fechaCorta(a.detectada)}</td><td>${esc(a.causa)}${a.causaCierre ? `<div class="gp-meta">cerrada por ${esc(a.cerradaPor)}: ${esc(a.causaCierre)}</div>` : ''}</td></tr>`).join('')}</tbody></table></div>` : '<p class="vacio">Ninguna.</p>';
}
$('#recalcular').hidden = !(CFG.puedeFirmar || CFG.puedeConfigurar);
$('#recalcular').onclick = async () => {
  const b = $('#recalcular'); b.disabled = true; b.textContent = 'Calculando…';
  try { const r = await api(`${BASE}/api/zonas/${encodeURIComponent(COD)}/evaluacion`, {method: 'POST'}); aviso(`Evaluada: riesgo ${r.evaluacion.nivel}${r.acciones.length ? ' · ' + r.acciones.join(', ') : ''}`, true); }
  catch (e) { aviso(e.message); }
  b.disabled = false; b.textContent = 'Recalcular'; cargar();
};
cargar(); setInterval(cargar, 30000);
"""

# ---------- Mapa ----------
MAPA = """<div class="gp-dos" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr))">
<section class="tarjeta"><div class="cab"><h2>Planta del inmueble</h2><span class="eyebrow" id="ed"></span></div>
<div id="plano"><p class="vacio">Cargando…</p></div>
<p class="gp-ley"><span><i style="background:var(--teal)"></i>riesgo bajo</span><span><i style="background:var(--ochre)"></i>medio</span>
<span><i style="background:var(--red)"></i>alto</span><span>● sensor operativo · ○ sin lecturas</span></p></section>
<section class="tarjeta"><div class="cab"><h2>Sensores</h2></div><div class="tabla"><table><thead><tr><th>Sensor</th><th>Zona</th><th>Estado</th><th>Última lectura</th></tr></thead>
<tbody id="sens"></tbody></table></div></section></div>"""

SCRIPT_MAPA = _UTIL + r"""
const COLOR = {bajo: 'var(--teal)', medio: 'var(--ochre)', alto: 'var(--red)'};
async function cargar() {
  let d, ss;
  try { [d, ss] = await Promise.all([api(BASE + '/api/inmueble'), api(BASE + '/api/sensores')]); }
  catch (e) { $('#plano').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  $('#ed').textContent = d.edificio ? d.edificio.nombre : '';
  const zonas = d.zonas.filter(z => z.plano);
  if (!zonas.length) { $('#plano').innerHTML = '<p class="vacio">Sin zonas con posición en la planta.</p>'; }
  else {
    let g = zonas.map(z => { const p = z.plano, c = COLOR[z.nivel] || 'var(--muted)';
      return `<a href="${BASE}/zona?z=${encodeURIComponent(z.codigo)}"><title>${esc(z.nombre)} · ${esc(NIVEL[z.nivel] || 'sin evaluar')}</title>
      <rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="1" fill="${c}" fill-opacity=".16" stroke="${c}" stroke-width=".4"/>
      <text x="${p.x + 1.5}" y="${p.y + 3.5}" style="font-weight:600">${esc(z.nombre)}</text>
      <text x="${p.x + 1.5}" y="${p.y + 6.6}">${z.humedad == null ? '' : NUM.format(z.humedad) + ' % · ' + NUM.format(z.temperatura) + ' °C'}</text></a>`; }).join('');
    g += ss.filter(s => s.posicion).map(s => { const ok = s.estado === 'OK' && s.ahora;
      return `<g><title>${esc(s.nombre)} (${esc(s.codigo)}) · ${s.ahora ? NUM.format(s.ahora.humedad) + ' % · ' + NUM.format(s.ahora.temperatura) + ' °C' : 'sin lecturas'}</title>
      <circle cx="${s.posicion.x}" cy="${s.posicion.y}" r="1.4" fill="${ok ? 'var(--ink)' : 'var(--card)'}" stroke="var(--ink)" stroke-width=".4"/>
      <text x="${s.posicion.x + 2}" y="${s.posicion.y + .8}" style="font-size:1.8px">${esc(s.codigo)}</text></g>`; }).join('');
    const W = Math.max(100, ...zonas.map(z => z.plano.x + z.plano.w + 4)), H = Math.max(60, ...zonas.map(z => z.plano.y + z.plano.h + 4));
    $('#plano').innerHTML = `<svg class="gp-plano" viewBox="0 0 ${W} ${H}" role="img" aria-label="Planta con zonas y sensores">${g}</svg>`;
  }
  $('#sens').innerHTML = ss.map(s => `<tr><td>${esc(s.nombre)} <span class="mono" style="color:var(--muted)">${esc(s.codigo)}</span></td><td>${esc(s.zonaNombre || s.zona)}</td>
    <td><span class="pill ${s.estado === 'OK' ? 'ok' : 'pendiente'}">${esc(s.estado || '—')}</span></td>
    <td>${s.ahora ? `${NUM.format(s.ahora.temperatura)} °C · ${NUM.format(s.ahora.humedad)} % · ${fechaCorta(s.ahora.observadoEn)}` : '—'}</td></tr>`).join('') || '<tr><td colspan="4">Sin sensores.</td></tr>';
}
cargar(); setInterval(cargar, 30000);
"""

# ---------- Alertas ----------
ALERTAS = """<section class="tarjeta"><div class="cab"><h2>Alertas de conservación</h2>
<label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="todas"> ver también las cerradas</label></div>
<div id="lista"><p class="vacio">Cargando…</p></div>
<p class="gp-nota">Cada alerta remite a la evaluación EN 15757 que la originó. Cerrarla exige escribir la causa: la firma queda en
el proceso de la alerta (Temporal) y en el notario, también en el libro de los legajos de un depósito afectado.</p></section>"""

SCRIPT_ALERTAS = _UTIL + r"""
async function cargar() {
  let xs;
  try { xs = await api(`${BASE}/api/alertas?estado=${$('#todas').checked ? 'todas' : 'abiertas'}`); }
  catch (e) { $('#lista').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  if (!xs.length) { $('#lista').innerHTML = '<p class="vacio">No hay alertas abiertas. Todas las zonas están dentro de su microclima.</p>'; return; }
  $('#lista').innerHTML = `<div class="tabla"><table><thead><tr><th>Alerta</th><th>Zona</th><th>Nivel</th><th>Estado</th><th>Detectada</th><th>Causa</th><th></th></tr></thead><tbody>${xs.map(a => `
    <tr><td class="mono">${esc(a.codigo)}</td><td><a href="${BASE}/zona?z=${encodeURIComponent(a.zonaCodigo)}">${esc(a.zonaNombre || a.zonaCodigo)}</a></td>
    <td>${pillNivel(a.nivel)}</td><td>${esc(a.estado)}${a.propuestaCierre && a.estado !== 'cerrada' ? '<div class="gp-meta">se propone cerrarla</div>' : ''}${a.reconocidaPor ? `<div class="gp-meta">reconocida por ${esc(a.reconocidaPor)}</div>` : ''}</td>
    <td>${fechaCorta(a.detectada)}</td><td>${esc(a.causa)}${a.causaCierre ? `<div class="gp-meta">cerrada por ${esc(a.cerradaPor)}: ${esc(a.causaCierre)}</div>` : ''}<div id="actas-${esc(a.codigo)}"></div></td>
    <td><div class="gp-acc">${CFG.puedeFirmar && a.estado === 'activa' ? `<button class="btn sec" data-rec="${esc(a.codigo)}">Reconocer</button>` : ''}
      ${CFG.puedeFirmar && a.estado !== 'cerrada' ? `<button class="btn" data-cerrar="${esc(a.codigo)}">Cerrar…</button>` : ''}
      <button class="btn sec" data-actas="${esc(a.codigo)}">Notario</button></div></td></tr>`).join('')}</tbody></table></div>`;
  document.querySelectorAll('[data-rec]').forEach(b => b.onclick = async () => {
    try { await api(`${BASE}/api/alertas/${b.dataset.rec}/reconocer`, {method: 'POST'}); aviso('Alerta reconocida', true); } catch (e) { aviso(e.message); }
    setTimeout(cargar, 800);
  });
  document.querySelectorAll('[data-cerrar]').forEach(b => b.onclick = async () => {
    const causa = prompt(`Causa del cierre de ${b.dataset.cerrar} (queda firmada con tu nombre):`);
    if (!causa) return;
    try { await api(`${BASE}/api/alertas/${b.dataset.cerrar}/cerrar`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({causa})}); aviso('Alerta cerrada y firmada', true); }
    catch (e) { aviso(e.message); }
    setTimeout(cargar, 800);
  });
  document.querySelectorAll('[data-actas]').forEach(b => b.onclick = async () => {
    const caja = $('#actas-' + b.dataset.actas);
    try { const xs = await api(`${BASE}/api/alertas/${b.dataset.actas}/actas`);
      caja.innerHTML = `<ol class="gp-actas">${xs.map(x => `<li>${fechaCorta(x.tiempo)} · ${esc(x.tipo)}${x.detalle ? ' · ' + esc(x.detalle) : ''}</li>`).join('') || '<li>Sin actas todavía.</li>'}</ol>`; }
    catch (e) { caja.innerHTML = `<p class="aviso">${esc(e.message)}</p>`; }
  });
}
$('#todas').onchange = cargar;
cargar(); setInterval(() => { if (!document.querySelector('.gp-actas')) cargar(); }, 20000);
"""

# ---------- Configuración ----------
CONFIGURACION = """<p id="solo-lectura" class="aviso" hidden>Solo quien administra la institución (o la archivera) puede cambiar el inmueble.</p>
<div class="gp-dos">
<section class="tarjeta"><div class="cab"><h2>Inmueble de ejemplo</h2></div>
<p style="margin:0 0 12px">Un edificio histórico con 4 zonas (sala, dos depósitos y capilla), 3 elementos y 6 sensores simulados, con un
año de histórico sintético para calibrar el microclima. Si tu institución tiene depósitos, las zonas de depósito se enlazan con
ellos y heredan sus cajas y legajos.</p><button class="btn" id="semilla" type="button">Crear el inmueble de ejemplo</button>
<p class="gp-nota" id="semilla-r"></p></section>
<section class="tarjeta"><div class="cab"><h2>Simular para la demo</h2></div>
<form class="gp-form" id="f-sim"><label>Zona<select id="sim-zona"></select></label>
<label>Perfil<select id="sim-perfil"><option value="desviacion">Desviación sostenida (fuga, avería)</option>
<option value="fluctuacion">Fluctuación rápida</option><option value="estable">Volver a su clima</option></select></label>
<label>Días<input type="number" id="sim-dias" min="1" max="30" value="8"></label><button class="btn" type="submit">Simular</button></form>
<p class="gp-nota">Reescribe los últimos días de la zona con datos sintéticos (marcados así en la evaluación) y la evalúa al momento;
los sensores siguen en vivo con ese perfil. Lo que en la realidad tardaría días en verse, en un minuto.</p>
<div class="tabla" style="margin-top:8px"><table><thead><tr><th>Zona</th><th>Perfil en vivo</th></tr></thead><tbody id="perfiles"></tbody></table></div></section>
<section class="tarjeta"><div class="cab"><h2>Nueva zona</h2></div>
<form class="gp-form" id="f-zona"><label>Código<input name="codigo" required placeholder="Z05"></label><label>Nombre<input name="nombre" required></label>
<label>Tipo<select name="tipo" id="zona-tipo"><option>sala</option><option>depósito</option><option>capilla</option><option>cubierta</option><option>fachada</option><option>otro</option></select></label>
<label>Materiales<input name="materiales" placeholder="madera, papel"></label><label>Área (m²)<input name="area" type="number" step="any"></label>
<label>T habitual (°C)<input name="temperatura" type="number" step="any" value="18"></label><label>HR habitual (%)<input name="humedad" type="number" step="any" value="55"></label>
<label id="zona-dep-l" hidden>Depósito del archivo<select name="deposito" id="zona-dep"></select></label>
<label>Planta x,y,ancho,alto<input name="plano" placeholder="vacío = primer hueco libre"></label><button class="btn" type="submit">Añadir zona</button></form>
<p class="gp-nota">Sin posición, la zona se coloca en el primer hueco libre de la planta (el Mapa crece si hace falta). Una zona de tipo
depósito enlazada con un depósito del archivo enseña sus cajas y legajos.</p></section>
<section class="tarjeta"><div class="cab"><h2>Recolocar una zona</h2></div>
<form class="gp-form" id="f-plano"><label>Zona<select name="zona" id="plano-zona"></select></label>
<label>Planta x,y,ancho,alto<input name="plano" placeholder="vacío = primer hueco libre"></label>
<button class="btn" type="submit">Recolocar</button></form>
<p class="gp-nota">Para las zonas que quedaron encima de otra en el Mapa. La planta de ejemplo mide 100 × 60; cada zona del ejemplo,
44 × 22–26.</p><div class="tabla" style="margin-top:8px"><table><thead><tr><th>Zona</th><th>Posición</th><th>Depósito</th></tr></thead>
<tbody id="posiciones"></tbody></table></div></section>
<section class="tarjeta"><div class="cab"><h2>Nuevo sensor</h2></div>
<form class="gp-form" id="f-sensor"><label>Código<input name="codigo" required placeholder="S07"></label><label>Nombre<input name="nombre" required></label>
<label>Zona<select name="zona" id="sensor-zona"></select></label><label>Posición x<input name="x" type="number" step="any" placeholder="centro de la zona"></label>
<label>Posición y<input name="y" type="number" step="any" placeholder="centro de la zona"></label><button class="btn" type="submit">Añadir sensor</button></form>
<p class="gp-nota">Se inscribe en el catastro como EnvironmentalSensor con su IndoorEnvironmentObserved; el simulador lo lee en su
siguiente vuelta. Para sensores reales, un sistema de tu institución puede enviar lecturas a
<span class="mono">POST /api/v1/gemelo/ingesta/observacion</span> con una credencial de API de «Mi institución».
Vocabulario: <a href="/contexts/v1/gdp.jsonld">/contexts/v1/gdp.jsonld</a>.</p></section>
</div>"""

SCRIPT_CONFIGURACION = _UTIL + r"""
const JSONH = {'Content-Type': 'application/json'};
const post = (url, cuerpo) => api(BASE + url, {method: 'POST', headers: JSONH, body: JSON.stringify(cuerpo || {})});
if (!CFG.puedeConfigurar) { $('#solo-lectura').hidden = false; document.querySelectorAll('form button, #semilla').forEach(b => b.disabled = true); }
async function cargar() {
  try {
    const [d, ps] = await Promise.all([api(BASE + '/api/inmueble'), api(BASE + '/api/perfiles')]);
    const opts = d.zonas.map(z => `<option value="${esc(z.codigo)}">${esc(z.codigo)} · ${esc(z.nombre)}</option>`).join('');
    const sel = $('#sim-zona').value; $('#sim-zona').innerHTML = opts; if (sel) $('#sim-zona').value = sel;
    $('#sensor-zona').innerHTML = opts;
    const pz = $('#plano-zona').value; $('#plano-zona').innerHTML = opts; if (pz) $('#plano-zona').value = pz;
    const pl = p => p ? `${p.x}, ${p.y} · ${p.w} × ${p.h}` : '—';
    $('#posiciones').innerHTML = d.zonas.slice().sort((a, b) => a.codigo.localeCompare(b.codigo)).map(z => `<tr><td>${esc(z.codigo)} · ${esc(z.nombre)}</td>
      <td class="mono">${pl(z.plano)}</td><td>${esc(((d.depositosArchivo || []).find(x => x.id === z.deposito) || {}).nombre || '—')}</td></tr>`).join('');
    $('#zona-dep').innerHTML = '<option value="">— sin enlazar —</option>' + (d.depositosArchivo || []).map(x =>
      `<option value="${esc(x.codigo)}"${x.zona ? ' disabled' : ''}>${esc(x.nombre)}${x.zona ? ' (ya en ' + esc(x.zona) + ')' : ''}</option>`).join('');
    $('#semilla').textContent = d.edificio ? 'El inmueble ya está (volver a comprobar)' : 'Crear el inmueble de ejemplo';
    $('#perfiles').innerHTML = ps.map(p => `<tr><td>${esc(p.zona)}</td><td>${esc(p.perfil)}</td></tr>`).join('') || '<tr><td colspan="2">Sin sensores simulados.</td></tr>';
  } catch (e) { aviso(e.message); }
}
$('#semilla').onclick = async () => {
  const b = $('#semilla'); b.disabled = true; b.textContent = 'Creando… (calcula un año de histórico por zona)';
  try { const r = await post('/api/semilla'); $('#semilla-r').textContent = `${r.creadas} entidades nuevas · ${r.sensores} sensores simulados · ${r.evaluadas.length} zonas evaluadas.`; aviso('Inmueble listo', true); }
  catch (e) { aviso(e.message); }
  b.disabled = false; cargar();
};
$('#f-sim').onsubmit = async ev => {
  ev.preventDefault(); const b = ev.target.querySelector('button'); b.disabled = true;
  try { const r = await post('/api/simular', {zona: $('#sim-zona').value, perfil: $('#sim-perfil').value, dias: +$('#sim-dias').value});
    aviso(`${$('#sim-zona').value}: riesgo ${r.evaluacion.nivel}${r.acciones.length ? ' · ' + r.acciones.join(', ') : ''}`, r.evaluacion.nivel === 'bajo'); }
  catch (e) { aviso(e.message); }
  b.disabled = false; cargar();
};
const planoDe = txt => { const [x, y, w, h] = (txt || '').split(',').map(Number); return w && h ? {x: x || 0, y: y || 0, w, h} : {}; };
$('#zona-tipo').onchange = () => { $('#zona-dep-l').hidden = $('#zona-tipo').value !== 'depósito'; };
$('#f-zona').onsubmit = async ev => {
  ev.preventDefault(); const f = Object.fromEntries(new FormData(ev.target)); const plano = planoDe(f.plano); delete f.plano;
  if (f.tipo !== 'depósito') delete f.deposito;
  try { const r = await post('/api/zonas', {...f, ...plano});
    aviso(`Zona ${r.codigo} añadida en la planta (${r.plano.x}, ${r.plano.y}). Ponle un sensor para que reciba lecturas.`, true);
    ev.target.reset(); $('#zona-dep-l').hidden = true; $('#sensor-zona').dataset.elegir = r.codigo; }
  catch (e) { aviso(e.message); }
  await cargar(); if ($('#sensor-zona').dataset.elegir) { $('#sensor-zona').value = $('#sensor-zona').dataset.elegir; delete $('#sensor-zona').dataset.elegir; }
};
$('#f-plano').onsubmit = async ev => {
  ev.preventDefault(); const f = Object.fromEntries(new FormData(ev.target));
  try { const r = await post(`/api/zonas/${encodeURIComponent(f.zona)}/plano`, planoDe(f.plano));
    aviso(`${f.zona} recolocada en (${r.plano.x}, ${r.plano.y}) · ${r.plano.w} × ${r.plano.h}`, true); ev.target.querySelector('input').value = ''; }
  catch (e) { aviso(e.message); }
  cargar();
};
$('#f-sensor').onsubmit = async ev => {
  ev.preventDefault();
  try { await post('/api/sensores', Object.fromEntries(new FormData(ev.target))); aviso('Sensor añadido; el simulador lo leerá en su próxima vuelta', true); ev.target.reset(); }
  catch (e) { aviso(e.message); }
  cargar();
};
cargar();
"""
