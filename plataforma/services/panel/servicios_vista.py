"""Vistas del núcleo para el catálogo de servicios y los flujos (HTML y JS de la consola)."""

ESTILO = r"""
:root{--azul:#2F5DA8;--azul-t:#E3EBF8}
@media (prefers-color-scheme:dark){:root{--azul:#8AAEE8;--azul-t:#1B2A40}}
.modo-c{font:600 12.5px/1 var(--sans);padding:5px 10px;border-radius:999px;border:1px solid;white-space:nowrap}
.modo-c.integrada{background:var(--teal-t);border-color:var(--teal);color:var(--teal)}
.modo-c.alojada{background:var(--azul-t);border-color:var(--azul);color:var(--azul)}
.modo-c.externa{background:var(--ochre-t);border-color:var(--ochre);color:var(--ochre)}
.fuera-c{margin:0;font-size:13px;color:var(--ochre)}
.srv{display:flex;flex-direction:column;gap:10px}
.srv .tipos{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font:12px var(--mono)}
.srv .tipos span.t{padding:3px 8px;border-radius:6px;background:var(--bg);border:1px solid var(--line)}
.srv .meta-s{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--muted);font-size:13px}
.srv .pie-s{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-top:auto}
textarea{font:13px/1.5 var(--mono);border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--bg);color:var(--ink);width:100%;min-height:120px;resize:vertical}
textarea.prosa{font:15px/1.6 var(--sans)}
.form-s{display:grid;gap:12px}
.params{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.resultado{border-top:1px solid var(--line);padding-top:14px;display:grid;gap:10px}
.anotado{font:16px/1.8 var(--display);white-space:pre-wrap}
.anotado mark{background:color-mix(in srgb,var(--teal) 18%,transparent);color:inherit;border-radius:4px;padding:1px 2px}
.anotado mark small{font:500 10px var(--mono);color:var(--teal);margin-left:3px;vertical-align:super}
.anotado ins{text-decoration:none;background:var(--ochre-t);border-radius:3px}
pre.json{margin:0;font:12px/1.5 var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;overflow-x:auto;max-height:320px}
.dos{display:grid;grid-template-columns:minmax(320px,1fr) minmax(320px,1.2fr);gap:20px;align-items:start}
@media (max-width:1100px){.dos{grid-template-columns:1fr}}
.plan{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.plan li{display:grid;grid-template-columns:28px 1fr auto;gap:10px;align-items:center;padding:8px 10px;border:1px solid var(--line-2);border-radius:8px}
.plan li.firma{border-style:dashed}
.plan .n{font:12px var(--mono);color:var(--muted)}
.fila-f{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:10px 12px;border-bottom:1px solid var(--line-2);cursor:pointer}
.fila-f:hover{background:var(--bg)} .fila-f[aria-current="true"]{background:var(--teal-t)}
.fila-f .sub{grid-column:1/-1;color:var(--muted);font-size:13px}
.radio{display:flex;gap:16px;flex-wrap:wrap;font-size:14px} .radio label{display:flex;gap:6px;align-items:center}
"""

# Común: pinta cualquier documento de la plataforma según su tipo.
SCRIPT_DOC = r"""
function pintarDoc(doc) {
  if (!doc) return '';
  if (Array.isArray(doc.entidades)) {
    const t = doc.texto || ''; let out = '', i = 0;
    [...doc.entidades].sort((a, b) => a.inicio - b.inicio).forEach(e => {
      if (e.inicio < i) return;
      out += esc(t.slice(i, e.inicio)) + `<mark title="${esc(e.tipo)}${e.rasgos ? ' · ' + esc(e.rasgos.join(', ')) : ''}">${esc(t.slice(e.inicio, e.fin))}<small>${esc(e.tipo)}</small></mark>`;
      i = e.fin;
    });
    return `<div class="anotado">${out + esc(t.slice(i))}</div><p class="eyebrow" style="margin:0">${doc.entidades.length} entidades</p>`;
  }
  if (Array.isArray(doc.cambios)) {
    const t = doc.texto || '';
    return `<div class="anotado">${esc(t)}</div><p class="eyebrow" style="margin:0">${doc.cambios.length} cambios de grafía</p>
      <details><summary>Ver cambios</summary><p class="mono" style="font-size:13px">${doc.cambios.map(c => esc(c.original) + ' → ' + esc(c.moderno)).join(' · ')}</p></details>`;
  }
  if (doc.respuesta) return `<p>${esc(doc.respuesta)}</p>`;
  if (doc.texto) return `<div class="anotado">${esc(doc.texto)}</div>`;
  return `<pre class="json">${esc(JSON.stringify(doc, null, 2))}</pre>`;
}
const CAT = '/panel/api/catalogo';
"""

SERVICIOS_CUERPO = """
<section class="rejilla" style="--min:320px" id="servicios" aria-label="Servicios"><p class="vacio">Cargando el catálogo…</p></section>
<section class="tarjeta" id="probar" hidden aria-labelledby="t-probar">
<div class="cab"><h2 id="t-probar">Probar</h2><button class="btn sec" type="button" id="cerrar">Cerrar</button></div>
<form class="form-s" id="form-probar"></form>
<div class="resultado" id="resultado" hidden></div>
</section>
<section class="tarjeta" id="publicar" aria-labelledby="t-pub"><div class="cab"><h2 id="t-pub">Publicar un servicio</h2></div>
<div class="rejilla" style="--min:320px"><ol class="pasos-c">
<li><span class="mono">python scripts/nuevo_servicio.py &lt;id&gt; "&lt;nombre&gt;" --modo integrada|alojada|externa</span> copia la plantilla en <span class="mono">capacidades/&lt;id&gt;/</span>.
<b>Integrada</b>: del equipo del PaaS, dentro. <b>Alojada</b>: tuya, dentro de la plataforma en su propio contenedor. <b>Externa</b>: en tus servidores; el texto sale de la plataforma.</li>
<li>En <span class="mono">servicio.yaml</span>: qué recibe y qué entrega (tipos comunes), versión, parámetros, acceso y cuota.</li>
<li><b>Integrada o alojada</b>: escribe <span class="mono">procesar(entrada, parametros)</span> y añade su contenedor. <b>Externa</b>: escribe el <span class="mono">adaptador.py</span> que traduce a la API que ya existe.</li>
<li>Reconstruye el catálogo. Aparece aquí y en las recetas, sin tocar el núcleo.</li></ol>
<pre class="manifiesto">id: rag-colonial
nombre: Preguntas al corpus colonial
tipo: consulta
entrada: pregunta
salida: respuesta
version: 0.1.0
modo: integrada
acceso: [registrado]
cuota: {trabajos_dia: 300}</pre></div></section>
<section class="tarjeta" aria-labelledby="t-api"><div class="cab"><h2 id="t-api">Usarlo desde tu aplicación</h2></div>
<p style="margin:0 0 10px;color:var(--muted)">La misma API que usa la consola, por la puerta y con tu token de Keycloak.</p>
<pre class="json" id="curl"></pre></section>"""

SERVICIOS_SCRIPT = r"""
let SERV = [], USO = {};
function campoParam(nombre, d) {
  const id = 'p-' + nombre, ayuda = d.descripcion ? `<span style="color:var(--muted);font-size:12px">${esc(d.descripcion)}</span>` : '';
  if (d.valores && d.tipo !== 'lista') return `<label>${esc(nombre)} ${ayuda}<select id="${id}" data-p="${esc(nombre)}">${d.valores.map(v => `<option ${v === d.defecto ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  if (d.tipo === 'booleano') return `<label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="${id}" data-p="${esc(nombre)}" data-bool="1" ${d.defecto ? 'checked' : ''}> ${esc(nombre)}</label>`;
  return `<label>${esc(nombre)} ${ayuda}<input type="text" id="${id}" data-p="${esc(nombre)}" ${d.tipo === 'lista' ? 'data-lista="1" placeholder="separadas por comas"' : ''} value="${esc(d.defecto ?? '')}"></label>`;
}
function abrir(s) {
  $('#probar').hidden = false; $('#t-probar').textContent = 'Probar · ' + s.nombre; $('#resultado').hidden = true;
  const campo = s.entrada === 'pregunta'
    ? '<label>Pregunta<input type="text" id="entrada" required></label>'
    : `<label>Texto (${esc(s.entrada)})<textarea class="prosa" id="entrada" required placeholder="Pega aquí una transcripción"></textarea></label>`;
  const ps = Object.entries(s.parametros || {});
  $('#form-probar').innerHTML = campo + (ps.length ? `<div class="params">${ps.map(([n, d]) => campoParam(n, d)).join('')}</div>` : '')
    + '<div><button class="btn" type="submit">Ejecutar</button></div>';
  $('#form-probar').onsubmit = ev => { ev.preventDefault(); ejecutar(s); };
  $('#entrada').focus();
  $('#curl').textContent = curl(s);
  $('#probar').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function params() {
  const p = {};
  document.querySelectorAll('[data-p]').forEach(el => {
    if (el.dataset.bool) p[el.dataset.p] = el.checked;
    else if (el.dataset.lista) { const v = el.value.split(',').map(x => x.trim()).filter(Boolean); p[el.dataset.p] = v.length ? v : null; }
    else if (el.value !== '') p[el.dataset.p] = el.value;
  });
  return p;
}
async function ejecutar(s) {
  const b = $('#form-probar button[type=submit]'); b.disabled = true; b.textContent = 'Ejecutando…';
  const v = $('#entrada').value, entrada = s.entrada === 'pregunta' ? {pregunta: v} : {texto: v};
  const res = $('#resultado'); res.hidden = false; res.innerHTML = '<p class="vacio">En cola…</p>';
  try {
    const t = await api(`${CAT}/servicios/${encodeURIComponent(s.id)}/trabajos`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({entrada, parametros: params()})});
    for (let i = 0; i < 600; i++) {
      const e = await api(`${CAT}/trabajos/${t.id}`);
      if (e.estado === 'terminado') { res.innerHTML = `<p class="eyebrow" style="margin:0">${esc(s.id)} ${esc(e.version)} · ${NUM.format(e.ms / 1000)} s</p>` + pintarDoc(e.salida); break; }
      if (e.estado === 'error') { res.innerHTML = `<p class="aviso">${esc(e.error)}</p>`; break; }
      res.innerHTML = `<p class="vacio">${e.estado === 'en-curso' ? 'Procesando… (un servicio externo puede tardar en despertar)' : 'En cola…'}</p>`;
      await new Promise(r => setTimeout(r, 1000));
    }
  } catch (e) { res.innerHTML = `<p class="aviso">${esc(e.message)}</p>`; }
  b.disabled = false; b.textContent = 'Ejecutar'; cargarUso();
}
function curl(s) {
  const base = CFG.api || 'http://servidor:9080';
  const ej = s.entrada === 'pregunta' ? '{"pregunta": "..."}' : '{"texto": "..."}';
  return `TOKEN=...   # token de Keycloak de tu usuario
curl -X POST ${base}/api/v1/servicios/${s.id}/trabajos \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"entrada": ${ej}, "parametros": {}}'
# → {"id": "..."}; luego GET ${base}/api/v1/trabajos/<id>`;
}
async function cargarUso() { try { USO = await api(`${CAT}/uso`); pintar(); } catch (e) {} }
function pintar() {
  $('#servicios').innerHTML = SERV.map(s => `<article class="tarjeta srv">
    <div class="cab" style="margin:0"><h2>${esc(s.nombre)}</h2><span class="modo-c ${esc(s.modo)}">${esc(s.modo_nombre || s.modo)}</span></div>
    ${s.datos_salen ? '<p class="fuera-c">El texto sale de la plataforma hacia los servidores de su autor.</p>' : ''}
    <p style="margin:0;color:var(--muted)">${esc(s.resumen)}</p>
    <div class="tipos"><span class="t">${esc(s.entrada)}</span><span aria-hidden="true">→</span><span class="t">${esc(s.salida)}</span></div>
    <div class="meta-s"><span class="mono">${esc(s.id)} ${esc(s.version)}</span><span>${esc(s.autor)}</span><span>${esc(s.tipo)}</span></div>
    <div class="pie-s"><span style="font-size:13px;color:var(--muted)">hoy: ${USO[s.id] || 0}${s.cuota && s.cuota.trabajos_dia ? ' de ' + s.cuota.trabajos_dia : ''} trabajos</span>
    <button class="btn" type="button" data-s="${esc(s.id)}">Probar</button></div></article>`).join('') || '<p class="vacio">No hay servicios disponibles para tu institución.</p>';
  document.querySelectorAll('[data-s]').forEach(b => b.onclick = () => abrir(SERV.find(s => s.id === b.dataset.s)));
}
$('#cerrar').onclick = () => { $('#probar').hidden = true; };
(async () => {
  try { SERV = await api(`${CAT}/servicios`); } catch (e) { $('#servicios').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  pintar(); cargarUso();
  if (SERV[0]) $('#curl').textContent = curl(SERV[0]);
})();
"""

# ---------- Recetas: plantillas · nueva receta · ejecuciones ----------
RECETAS_CUERPO = """
<section class="rejilla" style="--min:340px" id="plantillas" aria-label="Recetas"><p class="vacio">Cargando…</p></section>
<section class="tarjeta" style="margin-top:20px" aria-labelledby="t-que"><div class="cab"><h2 id="t-que">Qué es una receta</h2></div>
<p style="margin:0">Una receta encadena capacidades y firmas de personas para ir de un documento a otro. La escribe
el equipo del PaaS (las de esta página), tu institución o cualquier persona registrada. Antes de lanzarla, la
plataforma comprueba que cada paso acepta lo que entrega el anterior; al ejecutarla, cada paso queda en el notario.</p></section>"""

NUEVA_CUERPO = """
<section class="tarjeta" aria-labelledby="t-nuevo" style="max-width:900px"><div class="cab"><h2 id="t-nuevo">Nueva receta</h2></div>
<form class="form-s" id="form-flujo">
<label>Empezar desde una receta<select id="plantilla"><option value="">— elige —</option></select></label>
<label>Receta (YAML)<textarea id="receta" style="min-height:260px" spellcheck="false"></textarea></label>
<div class="radio" role="radiogroup" aria-label="Documento de entrada">
<label><input type="radio" name="origen" value="activo" checked> Un legajo del catastro</label>
<label><input type="radio" name="origen" value="texto"> Pegar un texto</label></div>
<label id="campo-activo">URN del legajo<input type="text" id="activo" placeholder="urn:ngsi-ld:ActivoPatrimonial:…"></label>
<label id="campo-texto" hidden>Texto<textarea class="prosa" id="texto"></textarea></label>
<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sec" type="button" id="comprobar">Comprobar</button><button class="btn" type="submit">Lanzar</button></div>
<div id="plan"></div>
</form></section>"""

EJECUCIONES_CUERPO = """
<div class="dos">
<section aria-labelledby="t-mis"><div class="tarjeta" style="padding:0;overflow:hidden">
<div class="cab" style="padding:16px 16px 0"><h2 id="t-mis">Recetas lanzadas en tu institución</h2></div>
<div id="flujos"><p class="vacio">Cargando…</p></div></div></section>
<section class="tarjeta" id="detalle" hidden aria-live="polite"></section>
</div>"""

RECETAS_COMUN = r"""
const PARAMS = new URLSearchParams(location.search);
function pintarPlan(plan) {
  return `<ol class="plan">${plan.pasos.map(p => p.clase === 'servicio'
    ? `<li><span class="n">${p.n}</span><span><b>${esc(p.servicio)}</b> <span class="mono" style="font-size:12px;color:var(--muted)">${esc(p.version)} · ${esc(p.recibe)} → ${esc(p.entrega)}</span></span><span class="pill">capacidad</span></li>`
    : `<li class="firma"><span class="n">${p.n}</span><span>Firma de <b>${esc(p.rol)}</b>${p.instrucciones ? ' · <span style="color:var(--muted)">' + esc(p.instrucciones) + '</span>' : ''}</span><span class="pill pendiente">persona</span></li>`).join('')}</ol>
    <p style="margin:6px 0 0;font-size:13px;color:var(--muted)">Termina en <span class="mono">${esc(plan.salida)}</span>${plan.publicar ? ' y se publica en el catastro' : ''}.</p>`;
}
function errores(e) {
  try { const d = JSON.parse(e.message); if (d.errores) return d.errores; } catch (x) {}
  return [e.message];
}
const ETQ = {'en-curso': ['en curso', ''], 'esperando-firma': ['esperando firma', 'pendiente'], 'terminado': ['terminado', 'ok'], 'rechazado': ['rechazado', 'alerta'], 'error': ['error', 'alerta']};
"""

RECETAS_SCRIPT = r"""
(async () => {
  let ps;
  try { ps = await api(`${CAT}/plantillas`); } catch (e) { $('#plantillas').innerHTML = `<p class="aviso">${esc(e.message)}</p>`; return; }
  if (!ps.length) { $('#plantillas').innerHTML = '<p class="vacio">No hay recetas en flujos/.</p>'; return; }
  const planes = await Promise.all(ps.map(p => api('/panel/api/flujos/validar', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({yaml: p.yaml})}).catch(e => ({error: errores(e)}))));
  $('#plantillas').innerHTML = ps.map((p, i) => { const pl = planes[i];
    return `<article class="tarjeta"><div class="cab" style="margin:0 0 8px"><h2>${esc(p.receta.nombre || p.id)}</h2>
      ${pl.error ? '<span class="pill alerta">no disponible</span>' : `<span class="pill">${esc(p.receta.entrada)} → ${esc(pl.salida)}</span>`}</div>
      ${pl.error ? `<p class="aviso">${pl.error.map(esc).join('<br>')}</p>` : pintarPlan(pl)}
      <div style="display:flex;gap:8px;margin-top:12px"><a class="btn" href="/panel/recetas/nueva?plantilla=${encodeURIComponent(p.id)}">Usar esta receta</a>
      <details><summary class="btn sec" style="list-style:none">Ver YAML</summary><pre class="json" style="margin-top:8px">${esc(p.yaml)}</pre></details></div></article>`;
  }).join('');
})();
"""

NUEVA_SCRIPT = r"""
let PLANT = [];
document.querySelectorAll('input[name=origen]').forEach(r => r.onchange = () => {
  const act = document.querySelector('input[name=origen]:checked').value === 'activo';
  $('#campo-activo').hidden = !act; $('#campo-texto').hidden = act;
});
$('#plantilla').onchange = () => { const p = PLANT.find(x => x.id === $('#plantilla').value); if (p) $('#receta').value = p.yaml; $('#plan').innerHTML = ''; };
function entrada() {
  return document.querySelector('input[name=origen]:checked').value === 'activo'
    ? {activo: $('#activo').value.trim()} : {documento: {texto: $('#texto').value}};
}
$('#comprobar').onclick = async () => {
  try { const plan = await api('/panel/api/flujos/validar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({yaml: $('#receta').value})});
    $('#plan').innerHTML = pintarPlan(plan); }
  catch (e) { $('#plan').innerHTML = `<div class="aviso"><b>La receta no es válida</b><ul style="margin:6px 0 0;padding-left:18px">${errores(e).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`; }
};
$('#form-flujo').onsubmit = async ev => {
  ev.preventDefault();
  const b = $('#form-flujo button[type=submit]'); b.disabled = true;
  try { const r = await api('/panel/api/flujos/lanzar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({yaml: $('#receta').value, entrada: entrada()})});
    location.href = `/panel/recetas/ejecuciones?f=${encodeURIComponent(r.id)}`; }
  catch (e) { $('#plan').innerHTML = `<div class="aviso">${errores(e).map(esc).join('<br>')}</div>`; b.disabled = false; }
};
(async () => {
  try { PLANT = await api(`${CAT}/plantillas`); } catch (e) {}
  $('#plantilla').innerHTML = '<option value="">— elige —</option>' + PLANT.map(p => `<option value="${esc(p.id)}">${esc(p.receta.nombre || p.id)}</option>`).join('');
  const p = PLANT.find(x => x.id === PARAMS.get('plantilla')) || PLANT[0];
  if (p) { $('#plantilla').value = p.id; $('#receta').value = p.yaml; $('#comprobar').click(); }
})();
"""
EJECUCIONES_SCRIPT = r"""
let SEL = PARAMS.get("f");
const ROLES = CFG.roles;
async function cargar() {
  let fs;
  try { fs = await api(`${CAT}/flujos`); } catch (e) { $('#flujos').innerHTML = `<p class="aviso" style="margin:16px">${esc(e.message)}</p>`; return; }
  if (!fs.length) { $('#flujos').innerHTML = '<p class="vacio">Aún no se ha lanzado ninguna receta. <a href=\"/panel/recetas\">Elige una receta</a>.</p>'; return; }
  const estados = await Promise.all(fs.slice(0, 15).map(f => api(`${CAT}/flujos/${f.id}`).catch(() => null)));
  $('#flujos').innerHTML = fs.map((f, i) => { const e = estados[i]; const [t, c] = ETQ[e?.estado] || ['—', ''];
    return `<div class="fila-f" role="button" tabindex="0" data-f="${esc(f.id)}" aria-current="${f.id === SEL}"><b>${esc(f.nombre)}</b><span class="pill ${c}">${t}</span>
      <span class="sub">${esc(f.lanzadoPor)} · ${fecha(new Date(f.creado * 1000).toISOString())} · <span class="mono">${esc(f.id)}</span></span></div>`; }).join('');
  document.querySelectorAll('[data-f]').forEach(el => { const ir = () => { SEL = el.dataset.f; cargar(); }; el.onclick = ir; el.onkeydown = e => { if (e.key === 'Enter') ir(); }; });
  if (SEL) detalle(SEL);
}
async function detalle(fid) {
  let e;
  try { e = await api(`${CAT}/flujos/${fid}`); } catch (x) { return; }
  const p = e.pasos && e.pasos[e.paso];
  const puedo = e.estado === 'esperando-firma' && p && ROLES.includes(p.rol);
  const icono = s => ({hecho: 'ok', aprobado: 'ok', 'en-curso': '', 'esperando-firma': 'pendiente', rechazado: 'alerta', error: 'alerta'}[s] || '');
  $('#detalle').hidden = false;
  $('#detalle').innerHTML = `<div class="cab"><h2>${esc(e.nombre)}</h2><span class="pill ${(ETQ[e.estado] || [])[1] || ''}">${esc((ETQ[e.estado] || [e.estado])[0])}</span></div>
    ${e.error ? `<p class="aviso">${esc(e.error)}</p>` : ''}
    <ol class="plan">${(e.pasos || []).map(s => `<li class="${s.clase === 'firma' ? 'firma' : ''}"><span class="n">${s.n}</span>
      <span>${s.clase === 'servicio' ? `<b>${esc(s.servicio)}</b> <span class="mono" style="font-size:12px;color:var(--muted)">${esc(s.version)}${s.ms ? ' · ' + NUM.format(s.ms / 1000) + ' s' : ''}</span>`
        : `Firma de <b>${esc(s.rol)}</b>${s.firmadoPor ? ' · ' + esc(s.firmadoPor) : ''}${s.comentario ? ' · «' + esc(s.comentario) + '»' : ''}`}</span>
      <span class="pill ${icono(s.estado)}">${esc(s.estado)}</span></li>`).join('')}</ol>
    ${puedo ? `<div class="form-s" style="margin-top:14px"><label>Comentario<input type="text" id="comentario" placeholder="opcional"></label>
      ${p.instrucciones ? `<p style="margin:0;color:var(--muted)">${esc(p.instrucciones)}</p>` : ''}
      <div style="display:flex;gap:8px"><button class="btn" id="aprueba">Aprobar</button><button class="btn sec" id="rechaza">Rechazar</button></div></div>`
      : e.estado === 'esperando-firma' ? `<p style="color:var(--muted)">Espera la firma de una persona con rol <b>${esc(p.rol)}</b>.</p>` : ''}
    ${e.resultado ? `<p style="font-size:14px">Publicado en el catastro: <span class="mono">${esc(e.resultado)}</span></p>` : ''}
    <div class="resultado"><p class="eyebrow" style="margin:0">Documento · ${esc(e.tipo || '')}</p>${pintarDoc(e.documento)}</div>`;
  const firmar = async d => {
    try { await api(`${CAT}/flujos/${fid}/firmar`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({decision: d, comentario: $('#comentario').value})}); aviso(d === 'aprueba' ? 'Firmado.' : 'Rechazado.', true); }
    catch (x) { aviso(x.message); }
    setTimeout(cargar, 800);
  };
  if (puedo) { $('#aprueba').onclick = () => firmar('aprueba'); $('#rechaza').onclick = () => firmar('rechaza'); }
}
cargar(); setInterval(cargar, 5000);
"""

