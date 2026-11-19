"""El pasaporte público de cada activo: identidad, procedencia, derechos y uso por IA, verificables por cualquiera.

Sin sesión ni cuenta (la puerta lo publica en /pasaporte):

    GET  /pasaporte/<urn>                     la página
    GET  /pasaporte/api/<urn>                 el pasaporte en JSON, con la verificación del texto actual
    POST /pasaporte/api/<urn>/verificar       {texto} → ¿este texto es el que se certificó?
    GET  /pasaporte/<urn>/evidencia.json      la evidencia completa (huella y pruebas)
    GET  /pasaporte/<urn>/certificado.ots     la prueba de Bitcoin, para verificarla en opentimestamps.org
    GET  /pasaporte/<urn>/texto.txt           el texto certificado, tal cual se calculó la huella
                                              (solo si PASAPORTE_TEXTO_PUBLICO=si)

No publica nombres de usuario: en el libro, las personas aparecen como «una persona de la institución».
Por ahora, solo transcripciones (urn:ngsi-ld:Transcripcion:…). Derechos y uso por IA: «sin declarar» hasta
que la institución fije su política.
"""
import base64
import json
import unicodedata
from typing import Any, Callable, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from sdk import pasaporte as PS
from services.panel import pagina as P


def _normalizar(texto: str) -> str:
    """La misma normalización que la capacidad («nfc-lf-strip»): el archivo descargado da la misma huella."""
    t = texto.replace("\r\n", "\n").replace("\r", "\n").strip()
    return unicodedata.normalize("NFC", t)


def montar(app: FastAPI, *, registro, actas: Callable[[str], List[dict]],
           verificar: Callable[[str, dict], dict], texto_publico: bool = False) -> None:

    def cargar(urn: str):
        if not PS.URN_TRANSCRIPCION.match(urn):
            raise HTTPException(404, "por ahora el pasaporte es de transcripciones (urn:ngsi-ld:Transcripcion:…)")
        tenant = urn.split(":")[3]
        ent = registro.leer(tenant, urn)
        if not ent:
            raise HTTPException(404, "no existe ese activo")
        return tenant, ent, PS.leer_evidencia(ent)

    def datos(urn: str) -> Dict[str, Any]:
        tenant, ent, evid = cargar(urn)
        activo_id = PS.valor(ent, "deActivo")
        activo = registro.leer(tenant, activo_id) if activo_id else None
        try:
            libro = PS.actas_publicas(actas(activo_id)) if activo_id else []
        except OSError:
            libro = None
        verif = None
        if evid:
            try:
                verif = verificar(PS.valor(ent, "texto") or "", evid)
            except Exception as ex:  # noqa: BLE001  la capacidad caída no tumba el pasaporte
                verif = {"error": f"no se pudo verificar ahora: {ex}"}
        hay_ots = any(a.get("proveedor") == "blockchain" and a.get("prueba") for a in (evid or {}).get("anclajes", []))
        base = f"/pasaporte/{urn}"
        return {
            "id": urn, "institucion": tenant, "tipo": "Transcripción",
            "signatura": PS.valor(activo, "signatura"), "activo": activo_id, "ark": PS.valor(activo, "ark"),
            "identidad": ({"huella": evid["huella"], "algoritmo": evid["algoritmo"],
                           "normalizacion": evid["normalizacion"], "certificadaEl": evid["fecha"],
                           "certificacion": PS.estado_certificacion(evid), "anclajes": PS.anclajes_publicos(evid)}
                          if evid else {"certificacion": "sin-certificar"}),
            "procedencia": {"modelo": PS.valor(ent, "modelo"), "estado": PS.valor(ent, "estado"), "libro": libro},
            "derechos": PS.SIN_DECLARAR, "usoIA": PS.SIN_DECLARAR,
            "verificacion": verif,
            "descargas": {k: u for k, u in (("evidencia", f"{base}/evidencia.json" if evid else None),
                                            ("ots", f"{base}/certificado.ots" if hay_ots else None),
                                            ("texto", f"{base}/texto.txt" if evid and texto_publico else None)) if u},
        }

    @app.get("/pasaporte/api/{urn:path}/verificar", include_in_schema=False)
    def no_get(urn: str):
        raise HTTPException(405, "usa POST con {\"texto\": …}")

    @app.post("/pasaporte/api/{urn:path}/verificar")
    def verificar_texto(urn: str, peticion: Dict[str, Any] = Body(...)):
        _, _, evid = cargar(urn)
        if not evid:
            raise HTTPException(409, "este activo aún no está certificado")
        texto = peticion.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            raise HTTPException(422, "falta «texto»")
        return verificar(texto, evid)

    @app.get("/pasaporte/api/{urn:path}")
    def api(urn: str):
        return JSONResponse(datos(urn))

    @app.get("/pasaporte/{urn:path}/evidencia.json")
    def evidencia(urn: str):
        _, _, evid = cargar(urn)
        if not evid:
            raise HTTPException(404, "este activo aún no está certificado")
        return Response(json.dumps(evid, ensure_ascii=False, indent=1), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="evidencia.json"'})

    @app.get("/pasaporte/{urn:path}/certificado.ots")
    def ots(urn: str):
        _, _, evid = cargar(urn)
        a = next((a for a in (evid or {}).get("anclajes", []) if a.get("proveedor") == "blockchain" and a.get("prueba")), None)
        if not a:
            raise HTTPException(404, "este activo no tiene anclaje en blockchain")
        return Response(base64.b64decode(a["prueba"]), media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="texto.txt.ots"'})

    @app.get("/pasaporte/{urn:path}/texto.txt")
    def texto(urn: str):
        if not texto_publico:
            raise HTTPException(404, "esta instalación no publica el texto de las transcripciones")
        _, ent, evid = cargar(urn)
        if not evid:
            raise HTTPException(404, "este activo aún no está certificado")
        return PlainTextResponse(_normalizar(PS.valor(ent, "texto") or ""),
                                 headers={"Content-Disposition": 'attachment; filename="texto.txt"'})

    @app.get("/pasaporte/{urn:path}", response_class=HTMLResponse)
    def pagina(urn: str):
        cargar(urn)                                   # 404 si no existe
        return HTMLResponse(PAGINA.replace("__URN__", json.dumps(urn)))


PAGINA = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pasaporte del activo · PaaS Patrimonio</title>{P.FUENTES}
<style>{P.ESTILO}
.pp{{max-width:920px;margin:0 auto;padding:28px 16px 60px;display:grid;gap:16px}}
.tarjeta{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;display:grid;gap:10px}}
.pilares{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}
.veredicto{{border-radius:12px;padding:16px 20px;font-weight:600;display:grid;gap:6px}}
.veredicto.ok{{background:var(--teal-t);color:var(--teal);border:1px solid var(--teal)}}
.veredicto.mal{{background:var(--red-t);color:var(--red);border:1px solid var(--red)}}
.veredicto.gris{{background:var(--card);color:var(--muted);border:1px dashed var(--line)}}
.veredicto small{{font-weight:400;color:var(--ink)}}
.anc{{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;align-items:baseline;padding:8px 0;border-top:1px solid var(--line-2)}}
.pill{{display:inline-block;border-radius:999px;padding:1px 9px;font:500 12px/1.6 var(--mono);border:1px solid var(--line)}}
.pill.real{{background:var(--teal-t);color:var(--teal);border-color:var(--teal)}}
.pill.demo,.pill.simulado{{background:var(--ochre-t);color:var(--ochre);border-color:var(--ochre)}}
.pill.mal{{background:var(--red-t);color:var(--red);border-color:var(--red)}}
.muted{{color:var(--muted);font-size:13px}}
.huella{{word-break:break-all;font-size:13px}}
ol.libro{{margin:0;padding-left:20px;display:grid;gap:6px}}
textarea{{width:100%;min-height:110px;font:14px/1.45 var(--sans);padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer}}
</style></head><body><main class="pp">
<div><p class="eyebrow" style="margin:0">PaaS Patrimonio · Pasaporte del activo</p><h1 id="titulo">…</h1>
<p class="muted mono" id="ident"></p></div>
<div id="veredicto" class="veredicto gris">Comprobando…</div>
<div class="pilares">
 <section class="tarjeta"><h2>Identidad</h2><div id="identidad"></div></section>
 <section class="tarjeta"><h2>Procedencia</h2><div id="procedencia"></div></section>
 <section class="tarjeta"><h2>Derechos</h2><div id="derechos"></div></section>
 <section class="tarjeta"><h2>Uso por IA</h2><div id="usoia"></div></section>
</div>
<section class="tarjeta"><h2>Verifica tu copia</h2>
<p class="muted">Pega un texto que te hayan dado como esta transcripción. Se compara con la huella certificada; el texto no se guarda.</p>
<textarea id="texto" aria-label="Texto a verificar"></textarea><div><button class="btn" id="comprobar">Comprobar</button></div>
<div id="resultado"></div></section>
<section class="tarjeta"><h2>Compruébalo sin nosotros</h2><div id="descargas"></div></section>
</main>
<script>
const URN = __URN__, $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
const fecha = t => t ? new Date(t).toLocaleString('es-ES', {{dateStyle: 'medium', timeStyle: 'short'}}) : '';
const NOMBRE = {{blockchain: 'Blockchain abierta (Bitcoin)', eidas: 'Sello de tiempo eIDAS', nom151: 'Constancia NOM-151'}};
const MODO = {{real: 'real', demo: 'demo · sin valor legal', simulado: 'simulado · sin valor legal'}};
function veredicto(v, destino) {{
  if (!v) return `<div class="veredicto gris">Este activo aún no está certificado.</div>`;
  if (v.error) return `<div class="veredicto gris">${{esc(v.error)}}</div>`;
  const filas = (v.anclajes || []).map(a => `<small>${{a.valido ? '✓' : '✗'}} ${{esc(NOMBRE[a.proveedor] || a.proveedor)}}: ${{esc(a.detalle || '')}}</small>`).join('');
  return `<div class="veredicto ${{v.integro ? 'ok' : 'mal'}}">${{esc(v.resumen)}}${{filas}}</div>`;
}}
async function cargar() {{
  const r = await fetch('/pasaporte/api/' + URN);
  if (!r.ok) {{ $('#veredicto').textContent = 'No se encuentra este activo.'; return; }}
  const d = await r.json(), id = d.identidad;
  $('#titulo').textContent = `${{d.tipo}} del legajo ${{d.signatura || ''}}`;
  $('#ident').textContent = `${{d.institucion}} · ${{d.id}}${{d.ark ? ' · ' + d.ark : ''}}`;
  $('#veredicto').outerHTML = veredicto(d.verificacion).replace('class="veredicto', 'id="veredicto" class="veredicto');
  $('#identidad').innerHTML = id.huella ? `
    <div class="muted">Huella SHA-256 del texto (normalización ${{esc(id.normalizacion)}})</div>
    <div class="mono huella">${{esc(id.huella)}}</div>
    <div class="muted">Certificada el ${{fecha(id.certificadaEl)}} · estado <b>${{esc(id.certificacion)}}</b></div>
    ${{id.anclajes.map(a => `<div class="anc"><span class="pill ${{a.estado === 'error' ? 'mal' : esc(a.modo)}}">${{esc(MODO[a.modo] || a.modo)}}</span>
      <span><b>${{esc(NOMBRE[a.proveedor] || a.proveedor)}}</b> · ${{esc(a.estado)}}${{a.bloque != null ? ' · bloque ' + a.bloque : ''}}${{a.fecha ? ' · ' + fecha(a.fecha) : ''}}<br>
      <span class="muted">${{esc(a.emisor || '')}}</span></span></div>`).join('')}}`
    : '<p class="muted">Sin certificar todavía.</p>';
  const libro = d.procedencia.libro;
  $('#procedencia').innerHTML = `<div class="muted">Estado: <b>${{esc(d.procedencia.estado || '')}}</b>${{d.procedencia.modelo ? ' · transcrita con ' + esc(d.procedencia.modelo) : ''}}</div>`
    + (libro === null ? '<p class="muted">El libro del notario no responde ahora.</p>'
      : `<ol class="libro">${{libro.map(a => `<li><b>${{esc(a.nombre)}}</b> · <span class="muted">${{fecha(a.tiempo)}}</span>${{a.agentes.length ? '<br><span class="muted">' + esc(a.agentes.join(', ')) + '</span>' : ''}}${{a.detalle ? '<br><span class="muted">' + esc(a.detalle) + '</span>' : ''}}</li>`).join('')}}</ol>`);
  $('#derechos').innerHTML = `<p class="muted">${{esc(d.derechos.texto)}}</p>`;
  $('#usoia').innerHTML = `<p class="muted">${{esc(d.usoIA.texto)}}</p>`;
  const ds = d.descargas;
  $('#descargas').innerHTML = (ds.evidencia ? `<p><a href="${{esc(ds.evidencia)}}">Evidencia completa (JSON)</a>: huella y pruebas de cada anclaje.</p>` : '')
    + (ds.ots ? `<p><a href="${{esc(ds.ots)}}">Prueba de Bitcoin (.ots)</a>${{ds.texto ? ` y <a href="${{esc(ds.texto)}}">el texto certificado</a>` : ''}}: súbelos a <a href="https://opentimestamps.org" target="_blank" rel="noopener">opentimestamps.org</a> para comprobar la fecha sin pasar por esta plataforma.</p>` : '')
    + (!ds.evidencia ? '<p class="muted">Cuando el activo esté certificado, aquí podrás descargar sus pruebas.</p>' : '');
}}
$('#comprobar').addEventListener('click', async () => {{
  const r = await fetch('/pasaporte/api/' + URN + '/verificar', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{texto: $('#texto').value}})}});
  $('#resultado').innerHTML = r.ok ? veredicto(await r.json()) : `<p class="muted">${{esc((await r.json()).detail || r.status)}}</p>`;
}});
cargar();
</script></body></html>"""
