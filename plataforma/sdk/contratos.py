"""Valida eventos contra contracts/eventos/ (sobre común + esquema de su tipo)."""
import json
from pathlib import Path
from typing import Dict, List

from jsonschema import Draft202012Validator, FormatChecker

ESQUEMAS = Path(__file__).resolve().parents[1] / "contracts" / "eventos"


def _cargar(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


_base = Draft202012Validator(_cargar(ESQUEMAS / "_base.schema.json"), format_checker=FormatChecker())
_por_tipo: Dict[str, Draft202012Validator] = {
    p.name.replace(".schema.json", ""): Draft202012Validator(_cargar(p), format_checker=FormatChecker())
    for p in ESQUEMAS.glob("*.schema.json")
    if not p.name.startswith("_")
}

TIPOS = sorted(_por_tipo)


class ContratoInvalido(ValueError):
    def __init__(self, errores: List[str]):
        super().__init__("; ".join(errores))
        self.errores = errores


def errores(evento: dict) -> List[str]:
    """Lista de errores; vacía si el evento cumple su contrato."""
    tipo = evento.get("type")
    if tipo not in _por_tipo:
        return [f"tipo desconocido: {tipo!r}"]
    errs = list(_base.iter_errors(evento)) + list(_por_tipo[tipo].iter_errors(evento))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(raíz)'}: {e.message}" for e in errs]


def validar(evento: dict) -> dict:
    """Devuelve el evento si es válido; si no, lanza ContratoInvalido."""
    errs = errores(evento)
    if errs:
        raise ContratoInvalido(errs)
    return evento
