"""Adaptador del modernizador paleográfico de Ameyalli: transcripción → texto-modernizado (/modernizer/modernize).

Respuesta (CorrectionResult): {engine, text, changes: [{original, proposed, type, reason, confidence, position}], …}
La clave del proveedor (Groq/OpenRouter) es un secreto opcional: si la institución pone la suya, paga ella
y no comparte el límite de uso; si no, Ameyalli usa la de su servidor.
"""
from typing import Any, Dict, List, Optional

from capacidades._ameyalli import llamar, trocear

CLAVES = {"groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


def _regla(r: Dict[str, Any]) -> Dict[str, Any]:
    """Acepta las reglas en castellano o en el formato de Ameyalli (reglas_custom.json)."""
    return {"pattern": r.get("patron", r.get("pattern", "")), "replacement": r.get("reemplazo", r.get("replacement", "")),
            "criterion": r.get("criterio", r.get("criterion")), "is_regex": bool(r.get("regex", r.get("is_regex", False))),
            "active": bool(r.get("activa", r.get("active", True)))}


def ejecutar(manifiesto, entrada: dict, parametros: dict, http, secretos: Optional[dict] = None) -> dict:
    proveedor = parametros.get("proveedor") or "groq"
    base = {"provider": proveedor, "model": parametros.get("modelo") or "",
            "instructions": parametros.get("instrucciones") or "",
            "rules": [_regla(r) for r in (parametros.get("reglas") or []) if isinstance(r, dict)]}
    clave = (secretos or {}).get(CLAVES[proveedor])
    if clave:
        base["api_key"] = clave
    texto = entrada["texto"]
    partes: List[str] = []
    cambios: List[Dict[str, Any]] = []
    for desde, trozo in trocear(texto, int((manifiesto.externo or {}).get("max_caracteres", 9000))):
        if not trozo.strip():
            partes.append(trozo)
            continue
        r = llamar(manifiesto, "/modernizer/modernize", {**base, "text": trozo}, http, secretos)
        moderno = str(r.get("text") or "")
        if trozo.endswith("\n") and not moderno.endswith("\n"):
            moderno += "\n"
        partes.append(moderno)
        for c in r.get("changes") or []:
            cambio = {"original": c.get("original") or "", "moderno": c.get("proposed") or ""}
            if isinstance(c.get("position"), int):
                cambio["inicio"] = c["position"] + desde
            if c.get("reason") or c.get("type"):
                cambio["motivo"] = c.get("reason") or c.get("type")
            if isinstance(c.get("confidence"), (int, float)):
                cambio["confianza"] = c["confidence"]
            cambios.append(cambio)
    salida = {"texto": "".join(partes), "original": texto, "cambios": cambios}
    if entrada.get("activo"):
        salida["activo"] = entrada["activo"]
    return salida
