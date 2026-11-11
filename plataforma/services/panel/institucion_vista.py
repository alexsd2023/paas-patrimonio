"""Vistas de autoservicio de una institución: el alta (sin sesión) y «Mi institución» (su administradora).

Todo lo que se hace aquí lo hace el servicio de instituciones (services/instituciones) y el catálogo
(secretos), siempre con el token de quien está dentro y solo sobre su propia institución.
"""
from services.panel.pagina import ESTILO, FUENTES, e


def alta_html(error: str = "", datos: dict = None, cerrado: bool = False) -> str:
    d = {k: e(str(v)) for k, v in (datos or {}).items() if k != "clave"}
    err = f'<p class="aviso" role="alert">{e(error)}</p>' if error else ""
    if cerrado:
        form = ('<p class="aviso">El alta de instituciones está cerrada en esta plataforma. '
                'Escribe al equipo del PaaS para que os den de alta.</p>')
    else:
        form = f"""<form method="post" action="/panel/alta">
<fieldset><legend>La institución</legend>
<label>Nombre<input name="nombre" required maxlength="120" value="{d.get('nombre', '')}" placeholder="Museo Naval de Cartagena"></label>
<label>Identificador <span class="ayuda">minúsculas, cifras y guiones; no se puede cambiar</span>
<input name="institucion" required pattern="[a-z][a-z0-9\\-]{{2,39}}" value="{d.get('institucion', '')}" placeholder="museo-naval-cartagena"></label>
</fieldset>
<fieldset><legend>Quien la administra</legend>
<label>Nombre y apellidos<input name="persona" maxlength="120" value="{d.get('persona', '')}" autocomplete="name"></label>
<label>Email<input type="email" name="email" required value="{d.get('email', '')}" autocomplete="email"></label>
<label>Usuario<input name="usuario" required pattern="[a-z0-9][a-z0-9._\\-]{{2,39}}" value="{d.get('usuario', '')}" autocomplete="username"></label>
<label>Contraseña <span class="ayuda">al menos 10 caracteres</span><input type="password" name="clave" required minlength="10" autocomplete="new-password"></label>
</fieldset>
<button class="btn" type="submit">Dar de alta la institución</button></form>"""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Alta de institución · PaaS Patrimonio</title>{FUENTES}
<style>{ESTILO}
.entrar{{max-width:520px;margin:8vh auto;padding:0 16px;display:grid;gap:14px}}
.entrar form{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;display:grid;gap:16px}}
fieldset{{border:0;padding:0;margin:0;display:grid;gap:10px}}
legend{{font-weight:600;margin-bottom:6px}}
.ayuda,.pista{{color:var(--muted);font-size:13px}}
.pista{{margin:0}}
</style></head><body><div class="entrar">
<div><p class="eyebrow" style="margin:0">PaaS Patrimonio</p><h1>Alta de institución</h1></div>
<p class="pista">Tu institución tendrá su propio espacio aislado: su catastro, su notario, sus cartas y sus personas.
Al terminar entrarás como su administradora y podrás activar productos, invitar a tu equipo y crear credenciales de API.</p>
{err}{form}
<p class="pista">¿Ya tenéis cuenta? <a href="/panel">Entrar</a></p></div></body></html>"""


ESTILO_INST = r"""
.inst{display:grid;gap:20px}
.prod-a{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
.prod-a:first-of-type{border-top:0}
.prod-a .punto{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:8px}
.form-l{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));align-items:end}
.form-l input{width:100%;min-width:0;box-sizing:border-box}
.roles-c{display:flex;gap:10px;flex-wrap:wrap}
.roles-c label{display:flex;gap:6px;align-items:center;font-size:14px}
.secreto-n{background:var(--teal-t);border:1px solid var(--teal);border-radius:8px;padding:12px;display:grid;gap:6px}
.secreto-n code{word-break:break-all;font-size:14px}
.sec-fila{display:grid;gap:8px;grid-template-columns:minmax(160px,1fr) minmax(200px,2fr) auto;align-items:center;padding:10px 0;border-top:1px solid var(--line)}
.sec-fila:first-of-type{border-top:0}
@media (max-width:640px){.sec-fila{grid-template-columns:1fr}}
"""

CUERPO_INST = """
<div class="inst">
<section class="tarjeta" aria-labelledby="t-prod"><div class="cab"><h2 id="t-prod">Productos</h2></div>
<p class="sub" style="margin:0 0 8px">Lo que tu institución ve en la consola. Activar un producto no mueve datos: solo lo abre a tu equipo.</p>
<div id="productos"><p class="vacio">Cargando…</p></div></section>

<section class="tarjeta" aria-labelledby="t-pers"><div class="cab"><h2 id="t-pers">Personas</h2></div>
<div id="personas"><p class="vacio">Cargando…</p></div>
<details style="margin-top:12px"><summary>Añadir una persona</summary>
<form id="f-persona" class="form-l" style="margin-top:12px">
<label>Usuario<input name="usuario" required pattern="[a-z0-9][a-z0-9._\\-]{2,39}"></label>
<label>Nombre<input name="nombre"></label>
<label>Email<input type="email" name="email" required></label>
<label>Contraseña inicial<input type="password" name="clave" required minlength="10" autocomplete="new-password"></label>
<div class="roles-c" data-roles></div>
<button class="btn" type="submit">Añadir</button></form></details></section>

<section class="tarjeta" aria-labelledby="t-cred"><div class="cab"><h2 id="t-cred">Credenciales de API</h2></div>
<p class="sub" style="margin:0 0 8px">Para que un sistema de tu institución (vuestra web, un script) use la API sin una persona delante.
Obtiene su token con <span class="mono">client_credentials</span> y actúa con los roles que le des, siempre dentro de tu institución.</p>
<div id="nueva-cred"></div><div id="credenciales"><p class="vacio">Cargando…</p></div>
<form id="f-cred" class="form-l" style="margin-top:12px">
<label>Nombre<input name="nombre" required maxlength="60" placeholder="Catálogo web"></label>
<div class="roles-c" data-roles data-sin-admin></div>
<button class="btn sec" type="submit">Crear credencial</button></form></section>

<section class="tarjeta" aria-labelledby="t-sec"><div class="cab"><h2 id="t-sec">Secretos de las capacidades</h2></div>
<p class="sub" style="margin:0 0 8px">Tokens y claves que algunas capacidades necesitan para llamar a servicios externos. Se guardan cifrados
y nadie puede volver a leerlos, ni desde aquí. Si tu institución no pone el suyo, se usa el de la plataforma (cuando lo hay).</p>
<div id="secretos"><p class="vacio">Cargando…</p></div></section>

</div>"""

SCRIPT_INST = r"""
const INS = '/panel/api/instituciones', CAT = '/panel/api/catalogo';
const ROLES = {archivera: 'archivera', paleografa: 'paleógrafa', 'admin-institucion': 'administra'};
const JSONH = {'Content-Type': 'application/json'};
const esAdmin = CFG.roles.includes('admin-institucion'), esOperador = CFG.roles.includes('admin-paas');
const enviar = (url, metodo, cuerpo) => api(url, {method: metodo, headers: JSONH, body: JSON.stringify(cuerpo || {})});
document.querySelectorAll('[data-roles]').forEach(d => d.innerHTML = Object.entries(ROLES)
  .filter(([r]) => !(d.dataset.sinAdmin !== undefined && r === 'admin-institucion'))
  .map(([r, n]) => `<label><input type="checkbox" value="${r}" ${r === 'archivera' ? 'checked' : ''}> ${n}</label>`).join(''));
const rolesDe = f => [...f.querySelectorAll('[data-roles] input:checked')].map(i => i.value);

async function productos() {
  const yo = await api(`${INS}/yo`);
  $('#productos').innerHTML = yo.productos.map(p => {
    const on = yo.activos.includes(p.id);
    return `<div class="prod-a"><div><b>${esc(p.nombre)}</b> <span class="mono" style="color:var(--muted)">${esc(p.id)}</span></div>
      <div style="display:flex;gap:10px;align-items:center"><span class="pill ${on ? 'ok' : 'pendiente'}">${on ? 'activado' : 'sin activar'}</span>
      ${esAdmin ? `<button class="btn ${on ? 'sec' : ''}" data-act="${esc(p.id)}" data-on="${on ? '' : '1'}">${on ? 'Desactivar' : 'Activar'}</button>` : ''}</div></div>`;
  }).join('') || '<p class="vacio">No hay productos en la plataforma.</p>';
  document.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
    try { await enviar(`${INS}/activaciones/${b.dataset.act}`, 'PUT', {activo: !!b.dataset.on}); location.reload(); }
    catch (e) { aviso(e.message); }
  });
}

async function personas() {
  if (!esAdmin) { $('#personas').innerHTML = '<p class="vacio">Solo quien administra la institución gestiona las personas.</p>'; return; }
  const us = await api(`${INS}/usuarios`);
  $('#personas').innerHTML = `<div class="tabla"><table><thead><tr><th>Usuario</th><th>Email</th><th>Roles</th><th>Estado</th><th></th></tr></thead><tbody>${
    us.map(u => `<tr data-u="${esc(u.id)}"><td><b>${esc(u.usuario)}</b>${u.nombre ? `<br><span style="color:var(--muted);font-size:13px">${esc(u.nombre)}</span>` : ''}</td>
      <td>${esc(u.email || '')}</td>
      <td><div class="roles-c">${Object.entries(ROLES).map(([r, n]) => `<label><input type="checkbox" value="${r}" ${u.roles.includes(r) ? 'checked' : ''} ${u.usuario === CFG.usuario && r === 'admin-institucion' ? 'disabled' : ''}> ${n}</label>`).join('')}</div></td>
      <td><span class="pill ${u.activo ? 'ok' : 'pendiente'}">${u.activo ? 'activa' : 'desactivada'}</span></td>
      <td style="white-space:nowrap"><button class="btn sec" data-guardar>Guardar roles</button>
      ${u.usuario === CFG.usuario ? '' : `<button class="btn sec" data-activo="${u.activo ? '' : '1'}">${u.activo ? 'Desactivar' : 'Activar'}</button>`}</td></tr>`).join('')}</tbody></table></div>`;
  document.querySelectorAll('[data-u]').forEach(tr => {
    const id = tr.dataset.u;
    tr.querySelector('[data-guardar]').onclick = async () => {
      const roles = [...tr.querySelectorAll('.roles-c input:checked')].map(i => i.value);
      try { await enviar(`${INS}/usuarios/${id}`, 'PUT', {roles}); aviso('Roles guardados. Se aplican en su próxima sesión.', true); } catch (e) { aviso(e.message); }
      personas();
    };
    const b = tr.querySelector('[data-activo]');
    if (b) b.onclick = async () => { try { await enviar(`${INS}/usuarios/${id}`, 'PUT', {activo: !!b.dataset.activo}); } catch (e) { aviso(e.message); } personas(); };
  });
}
$('#f-persona').onsubmit = async ev => {
  ev.preventDefault();
  const f = ev.target, v = Object.fromEntries(new FormData(f));
  try { await enviar(`${INS}/usuarios`, 'POST', {...v, roles: rolesDe(f)}); f.reset(); aviso(`${v.usuario} ya puede entrar.`, true); }
  catch (e) { aviso(e.message); }
  personas();
};

async function credenciales() {
  if (!esAdmin) { $('#credenciales').innerHTML = ''; $('#f-cred').hidden = true; return; }
  const cs = await api(`${INS}/credenciales`);
  $('#credenciales').innerHTML = cs.length ? `<div class="tabla"><table><thead><tr><th>Nombre</th><th>client_id</th><th>Roles</th><th>Creada</th><th></th></tr></thead><tbody>${
    cs.map(c => `<tr><td>${esc(c.nombre)}</td><td class="mono">${esc(c.client_id)}</td><td>${c.roles.map(r => esc(ROLES[r] || r)).join(', ')}</td>
      <td>${esc(c.por)} · ${fecha(new Date(c.cuando * 1000).toISOString())}</td><td><button class="btn sec" data-revocar="${esc(c.client_id)}">Revocar</button></td></tr>`).join('')}</tbody></table></div>`
    : '<p class="vacio">Aún no hay credenciales.</p>';
  document.querySelectorAll('[data-revocar]').forEach(b => b.onclick = async () => {
    if (!confirm(`¿Revocar ${b.dataset.revocar}? Lo que la use dejará de funcionar.`)) return;
    try { await api(`${INS}/credenciales/${b.dataset.revocar}`, {method: 'DELETE'}); } catch (e) { aviso(e.message); }
    credenciales();
  });
}
$('#f-cred').onsubmit = async ev => {
  ev.preventDefault();
  const f = ev.target;
  try {
    const r = await enviar(`${INS}/credenciales`, 'POST', {nombre: f.nombre.value, roles: rolesDe(f)});
    $('#nueva-cred').innerHTML = `<div class="secreto-n" role="status"><b>Guarda el secreto ahora: no se vuelve a mostrar.</b>
      <span>client_id: <code class="mono">${esc(r.client_id)}</code></span><span>secreto: <code class="mono">${esc(r.secreto)}</code></span>
      <span style="font-size:13px">Token: <code class="mono">POST ${esc(CFG.enlaces.keycloak || '<keycloak>')}/realms/paas/protocol/openid-connect/token</code> con
      <code class="mono">grant_type=client_credentials</code>, <code class="mono">client_id</code> y <code class="mono">client_secret</code>.
      Luego llama a <code class="mono">${esc(CFG.api)}/api/v1/…</code> con <code class="mono">Authorization: Bearer &lt;token&gt;</code>.</span></div>`;
    f.reset();
  } catch (e) { aviso(e.message); }
  credenciales();
};

async function secretos() {
  const ss = await api(`${CAT}/secretos`);
  if (!ss.length) { $('#secretos').innerHTML = '<p class="vacio">Ninguna de las capacidades que usas necesita secretos.</p>'; return; }
  const filas = [];
  for (const s of ss) for (const x of s.secretos) {
    const puedo = (x.ambito !== 'plataforma' && esAdmin) || (x.ambito !== 'institucion' && esOperador);
    const de = x.institucion ? `el de tu institución (${esc(x.institucion.por)})` : x.plataforma ? 'el de la plataforma' : x.entorno ? 'el de la plataforma (platform/.env)' : null;
    filas.push(`<div class="sec-fila"><div><b>${esc(s.nombre)}</b><br><span class="mono">${esc(x.nombre)}</span>
      <br><span style="color:var(--muted);font-size:13px">${esc(x.descripcion)}</span></div>
      <div><span class="pill ${de ? 'ok' : x.opcional ? 'pendiente' : 'alerta'}">${de ? 'en uso: ' + de : x.opcional ? 'opcional: sin poner' : 'sin poner: la capacidad fallará'}</span></div>
      ${puedo ? `<form class="form-l" data-sec="${esc(s.servicio)}" data-nombre="${esc(x.nombre)}" style="grid-template-columns:1fr auto">
        <input type="password" name="valor" placeholder="nuevo valor" autocomplete="off" aria-label="Valor de ${esc(x.nombre)}">
        <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${x.ambito !== 'plataforma' && esAdmin ? '<button class="btn sec" value="institucion">Guardar para mi institución</button>' : ''}
        ${x.ambito !== 'institucion' && esOperador ? '<button class="btn sec" value="plataforma">Guardar para la plataforma</button>' : ''}
        ${x.institucion && esAdmin ? '<button class="btn sec" type="button" data-quitar="institucion">Quitar el mío</button>' : ''}</div></form>` : '<span></span>'}</div>`);
  }
  $('#secretos').innerHTML = filas.join('');
  document.querySelectorAll('[data-sec]').forEach(f => {
    const url = `${CAT}/secretos/${f.dataset.sec}/${f.dataset.nombre}`;
    f.onsubmit = async ev => {
      ev.preventDefault();
      try { await enviar(url, 'PUT', {valor: f.valor.value, ambito: ev.submitter.value}); aviso('Secreto guardado.', true); } catch (e) { aviso(e.message); }
      secretos();
    };
    const q = f.querySelector('[data-quitar]');
    if (q) q.onclick = async () => { try { await api(`${url}?ambito=${q.dataset.quitar}`, {method: 'DELETE'}); } catch (e) { aviso(e.message); } secretos(); };
  });
}

for (const f of [productos, personas, credenciales, secretos]) f().catch(e => aviso(e.message));
"""


# ---------- instituciones de la plataforma (equipo del PaaS, admin-paas) ----------
CUERPO_TODAS = """
<div class="inst">
<section class="tarjeta" aria-labelledby="t-alta"><div class="cab"><h2 id="t-alta">Dar de alta una institución</h2></div>
<p class="sub" style="margin:0 0 12px">Crea la institución y su primera administradora. Pásale su usuario y contraseña:
al entrar activará sus productos e invitará a su equipo ella misma. Funciona aunque el alta pública esté cerrada.</p>
<div id="alta-hecha"></div>
<form id="f-alta" class="form-l">
<label>Nombre de la institución<input name="nombre" required maxlength="120" placeholder="Museo Naval de Cartagena"></label>
<label>Identificador<input name="institucion" required pattern="[a-z][a-z0-9\\-]{2,39}" placeholder="museo-naval"></label>
<label>Quien la administra<input name="persona" maxlength="120" placeholder="Nombre y apellidos"></label>
<label>Email<input type="email" name="email" required></label>
<label>Usuario<input name="usuario" required pattern="[a-z0-9][a-z0-9._\\-]{2,39}"></label>
<label>Contraseña inicial<input type="text" name="clave" required minlength="10" autocomplete="off"></label>
<div style="display:flex;gap:8px;align-items:end"><button class="btn sec" type="button" id="generar">Generar contraseña</button>
<button class="btn" type="submit">Dar de alta</button></div>
</form>
<p class="sub" id="alta-publica" style="margin:12px 0 0"></p></section>

<section class="tarjeta" aria-labelledby="t-todas"><div class="cab"><h2 id="t-todas">Todas las instituciones</h2></div>
<div id="instituciones"><p class="vacio">Cargando…</p></div></section>
</div>"""

SCRIPT_TODAS = r"""
const INS = '/panel/api/instituciones';
const f = $('#f-alta');
$('#generar').onclick = () => {
  const a = new Uint8Array(12); crypto.getRandomValues(a);
  f.clave.value = btoa(String.fromCharCode(...a)).replace(/[+/=]/g, '').slice(0, 14);
};
f.nombre.oninput = () => {
  if (f.institucion.dataset.tocado) return;
  f.institucion.value = f.nombre.value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
};
f.institucion.oninput = () => f.institucion.dataset.tocado = '1';
f.onsubmit = async ev => {
  ev.preventDefault();
  const v = Object.fromEntries(new FormData(f));
  try {
    const r = await api(`${INS}/instituciones`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(v)});
    $('#alta-hecha').innerHTML = `<div class="secreto-n" role="status" style="margin-bottom:12px"><b>${esc(r.nombre)} ya está dada de alta.</b>
      <span>Pásale a su administradora: entrar en <code class="mono">${esc(location.origin)}/panel</code> con el usuario
      <code class="mono">${esc(r.usuario)}</code> y la contraseña <code class="mono">${esc(v.clave)}</code>.</span>
      <span style="font-size:13px">La contraseña no se guarda en ningún sitio visible: cópiala ahora.</span></div>`;
    f.reset(); delete f.institucion.dataset.tocado;
  } catch (e) { aviso(e.message); }
  todas();
};
async function todas() {
  const is = await api(`${INS}/instituciones`);
  $('#instituciones').innerHTML = is.length ? `<div class="tabla"><table><thead><tr><th>Institución</th><th>Alta</th><th>Productos activados</th></tr></thead><tbody>${
    is.map(i => `<tr><td><b>${esc(i.nombre)}</b><br><span class="mono">${esc(i.id)}</span></td>
      <td>${i.gestionada ? `${esc(i.por || '')} · ${i.creada ? fecha(new Date(i.creada * 1000).toISOString()) : ''}` : '<span style="color:var(--muted)">anterior al alta autoservicio</span>'}</td>
      <td class="mono">${esc(i.activos.join(', ') || '—')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="vacio">Aún no hay instituciones.</p>';
}
api(`${INS}/salud`).then(s => $('#alta-publica').innerHTML = s.registro === 'abierto'
  ? 'El alta pública también está abierta: cualquier institución puede darse de alta sola en <a href="/panel/alta">/panel/alta</a> (REGISTRO=cerrado en platform/.env para cerrarla).'
  : 'El alta pública está cerrada (REGISTRO=cerrado): solo el equipo del PaaS da altas, desde aquí.').catch(() => null);
todas().catch(e => aviso(e.message));
"""
