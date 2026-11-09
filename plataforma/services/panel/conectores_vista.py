"""Vista de la capa Conectores: configurar cada conector para mi institución, ejecutarlo y ver qué ha traído."""

ESTILO = r"""
.con{display:grid;gap:14px}
.con .cab-c{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
.con .meta-s{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--muted);font-size:13px}
.campos{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.campos label span.ayuda{color:var(--muted);font-size:12px}
.acciones{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.num-c{display:flex;gap:18px;flex-wrap:wrap}
.num-c div{display:flex;flex-direction:column}
.num-c b{font:600 26px/1 var(--display);font-variant-numeric:tabular-nums}
.num-c span{font-size:12px;color:var(--muted)}
"""

CUERPO = """
<div id="conectores" style="display:grid;gap:20px"><p class="vacio">Cargando…</p></div>
<section class="tarjeta" id="escribir" aria-labelledby="t-escribir"><div class="cab"><h2 id="t-escribir">Escribir un conector</h2></div>
<div class="rejilla" style="--min:320px"><ol class="pasos-c">
<li>Crea <span class="mono">conectores/&lt;id&gt;/conector.yaml</span>: nombre, sentido (entrada o salida), los campos que pedirá a cada institución y qué tipos escribe en el catastro.</li>
<li>Escribe <span class="mono">conector.py</span> con <span class="mono">ejecutar(config, ctx)</span>. <span class="mono">ctx.inscribir(entidad)</span> crea o actualiza en el catastro de esa institución; <span class="mono">ctx.http</span> llama al sistema de origen.</li>
<li>Reconstruye el catálogo. Aparece aquí con su formulario, sin tocar el núcleo.</li></ol>
<pre class="manifiesto">id: inventario-csv
nombre: Inventario en CSV
sentido: entrada
version: 0.1.0
configuracion:
  url: {tipo: url, obligatorio: true}
  separador: {tipo: texto, defecto: ";"}
escribe: [ActivoPatrimonial]
acceso: [rol:archivera]</pre></div></section>"""

SCRIPT = r"""
const CAT = '/panel/api/catalogo';
const ETQ = {'en-curso': ['en curso', 'pendiente'], terminada: ['terminada', 'ok'], error: ['error', 'alerta'], interrumpida: ['interrumpida', 'alerta']};
function campo(cid, n, d, v) {
  const id = `c-${cid}-${n}`, val = v ?? d.defecto ?? '';
  const ayuda = d.descripcion ? `<span class="ayuda">${esc(d.descripcion)}</span>` : '';
  if (d.valores) return `<label>${esc(n)}${d.obligatorio ? ' *' : ''} ${ayuda}<select id="${id}" data-c="${esc(n)}">${d.valores.map(x => `<option ${x === val ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>`;
  if (d.tipo === 'booleano') return `<label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="${id}" data-c="${esc(n)}" data-bool="1" ${val ? 'checked' : ''}> ${esc(n)} ${ayuda}</label>`;
  const tipo = d.tipo === 'entero' ? 'number' : d.tipo === 'url' ? 'url' : 'text';
  return `<label>${esc(n)}${d.obligatorio ? ' *' : ''} ${ayuda}<input type="${tipo}" id="${id}" data-c="${esc(n)}" value="${esc(Array.isArray(val) ? val.join(', ') : val)}"></label>`;
}
function filaEjec(e) {
  const [t, c] = ETQ[e.estado] || [e.estado, ''];
  const r = e.resumen || {};
  const cifras = ['nuevos', 'actualizados', 'borrados'].filter(k => typeof r[k] === 'number').map(k => `${r[k]} ${k}`).join(' · ');
  return `<tr><td class="mono">${fecha(new Date(e.inicio * 1000).toISOString())}</td><td>${esc(e.usuario)}</td>
    <td><span class="pill ${c}">${t}</span></td><td>${e.error ? `<span style="color:var(--red)">${esc(e.error)}</span>` : esc(cifras || e.avance || '')}${r.incompleta ? ' · <i>quedan más; vuelve a ejecutar</i>' : ''}</td></tr>`;
}
async function pintar() {
  let cs;
  try { cs = await api(`${CAT}/conectores`); } catch (e) { $('#conectores').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  if (!cs.length) { $('#conectores').innerHTML = '<p class="vacio">No tienes acceso a ningún conector (los de entrada suelen ser de la archivera).</p>'; return; }
  const detalles = await Promise.all(cs.map(c => api(`${CAT}/conectores/${c.id}`)));
  $('#conectores').innerHTML = detalles.map(c => {
    const actual = (c.configuracion_actual || {}).valores || {};
    const ult = c.ejecuciones[0], r = (ult && ult.resumen) || {};
    return `<section class="tarjeta con" aria-labelledby="t-${esc(c.id)}">
      <div class="cab-c"><div><h2 id="t-${esc(c.id)}">${esc(c.nombre)}</h2><p style="margin:4px 0 0;color:var(--muted)">${esc(c.resumen)}</p></div>
        <span class="pill ${c.configuracion_actual ? 'ok' : 'pendiente'}">${c.configuracion_actual ? 'configurado' : 'sin configurar'}</span></div>
      <div class="meta-s"><span class="mono">${esc(c.id)} ${esc(c.version)}</span><span>sentido: ${esc(c.sentido)}</span><span>escribe: <span class="mono">${esc(c.escribe.join(', '))}</span></span><span>${esc(c.autor)}</span>
        ${c.configuracion_actual ? `<span>configurado por ${esc(c.configuracion_actual.por)} · ${fecha(new Date(c.configuracion_actual.cuando * 1000).toISOString())}</span>` : ''}</div>
      <form class="form-s" data-form="${esc(c.id)}"><div class="campos">${Object.entries(c.configuracion).map(([n, d]) => campo(c.id, n, d, actual[n])).join('')}</div>
        <div class="acciones"><button class="btn sec" type="submit">Guardar configuración</button>
        <button class="btn" type="button" data-run="${esc(c.id)}" ${c.configuracion_actual ? '' : 'disabled'}>Ejecutar ahora</button>
        ${ult && ult.estado === 'en-curso' ? `<button class="btn sec" type="button" data-stop="${esc(ult.id)}">Parar</button><span class="mono" style="font-size:13px">${esc(ult.avance || '')}</span>` : ''}</div></form>
      ${ult && ult.resumen ? `<div class="num-c">${['nuevos', 'actualizados', 'borrados', 'paginas'].filter(k => typeof r[k] === 'number').map(k => `<div><b>${r[k]}</b><span>${k}</span></div>`).join('')}${r.total_en_origen ? `<div><b>${r.total_en_origen}</b><span>en el origen</span></div>` : ''}</div>` : ''}
      ${c.ejecuciones.length ? `<details ${ult && ult.estado !== 'terminada' ? 'open' : ''}><summary>Ejecuciones (${c.ejecuciones.length})</summary><div class="tabla"><table><thead><tr><th>Cuándo</th><th>Quién</th><th>Estado</th><th>Resultado</th></tr></thead><tbody>${c.ejecuciones.map(filaEjec).join('')}</tbody></table></div></details>` : ''}
      ${c.escribe.map(t => `<div data-reg="${esc(t)}" data-con="${esc(c.id)}"></div>`).join('')}
    </section>`;
  }).join('');
  document.querySelectorAll('[data-form]').forEach(f => f.onsubmit = async ev => {
    ev.preventDefault();
    const v = {};
    f.querySelectorAll('[data-c]').forEach(el => { if (el.dataset.bool) v[el.dataset.c] = el.checked; else if (el.value !== '') v[el.dataset.c] = el.value; });
    try { await api(`${CAT}/conectores/${f.dataset.form}/configuracion`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(v)}); aviso('Configuración guardada.', true); }
    catch (e) { aviso(e.message); }
    pintar();
  });
  document.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
    try { await api(`${CAT}/conectores/${b.dataset.run}/ejecuciones`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}); aviso('Ejecución en marcha.', true); }
    catch (e) { aviso(e.message); }
    pintar();
  });
  document.querySelectorAll('[data-stop]').forEach(b => b.onclick = async () => {
    try { await api(`${CAT}/ejecuciones/${b.dataset.stop}/parar`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}); } catch (e) { aviso(e.message); }
    pintar();
  });
  document.querySelectorAll('[data-reg]').forEach(async el => {
    try {
      const rs = await api(`${CAT}/registros/${el.dataset.reg}?limite=12`);
      if (!rs.length) return;
      el.innerHTML = `<p class="eyebrow" style="margin:0 0 6px">En el catastro · ${esc(el.dataset.reg)} (últimos ${rs.length})</p><div class="tabla"><table><thead><tr><th>Título</th><th>Autoría</th><th>Fecha</th><th>Identificador</th></tr></thead><tbody>${
        rs.map(r => `<tr><td>${esc(r.titulo)}</td><td>${esc((r.creadores || '').split(' | ').slice(0, 2).join('; '))}</td><td class="mono">${esc((r.fechas || '').split(' | ')[0])}</td><td class="mono" style="font-size:12px;word-break:break-all">${esc(r.identificadorOai || '')}</td></tr>`).join('')}</tbody></table></div>`;
    } catch (e) {}
  });
}
pintar();
setInterval(() => { if (document.querySelector('[data-stop]')) pintar(); }, 3000);
"""
