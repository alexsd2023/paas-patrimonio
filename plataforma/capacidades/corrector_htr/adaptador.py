"""Adaptador del corrector de HTR de Ameyalli: transcripción ⇄ /reviewer/{motor} o /rag/correct.

Respuesta de Ameyalli (CorrectionResult): {engine, text, changes: [{original, proposed, type, reason, …}], details, latency_ms}
"""
from typing import Any, Dict, List, Optional

from capacidades._ameyalli import ErrorAmeyalli, llamar, trocear


def ejecutar(manifiesto, entrada: dict, parametros: dict, http, secretos: Optional[dict] = None) -> dict:
    motor = parametros.get("motor") or "agent"
    texto = entrada["texto"]
    partes: List[str] = []
    cambios: List[Dict[str, Any]] = []
    for desde, trozo in trocear(texto, int((manifiesto.externo or {}).get("max_caracteres", 18000))):
        if not trozo.strip():
            partes.append(trozo)
            continue
        try:
            if motor == "rag":
                r = llamar(manifiesto, "/rag/correct", {"text": trozo, "model": parametros.get("modelo_rag") or
                                                        "llama-3.3-70b-versatile",
                                                        "top_k": int(parametros.get("ejemplos_rag") or 5)}, http, secretos)
            else:
                r = llamar(manifiesto, f"/reviewer/{motor}", {"text": trozo}, http, secretos)
        except ErrorAmeyalli as e:
            if e.codigo == 409:
                raise RuntimeError("el agente ha detectado que su propia corrección modernizaba el texto y la ha "
                                   "rechazado: prueba con otro motor (mt5, latamgpt o rag)") from e
            raise
        corregido = str(r.get("text") or "")
        if trozo.endswith("\n") and not corregido.endswith("\n"):
            corregido += "\n"   # los servicios suelen comerse el salto final de cada trozo
        partes.append(corregido)
        for c in r.get("changes") or []:
            cambios.append({"original": c.get("original") or "", "corregido": c.get("proposed") or "",
                            "motivo": c.get("reason") or c.get("type") or ""})
    salida = {"texto": "".join(partes),
              "correccion": {"motor": motor, "cambios": cambios, "texto_htr": texto}}
    for k in ("activo", "idioma"):
        if entrada.get(k):
            salida[k] = entrada[k]
    return salida
