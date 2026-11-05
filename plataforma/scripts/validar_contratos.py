"""Parte 2 · valida los ejemplos de eventos contra sus esquemas.

- Cada ejemplo de contracts/ejemplos/ debe pasar.
- Cada ejemplo de contracts/ejemplos/invalidos/ debe FALLAR.

Uso (desde plataforma/, con el venv activo):  python scripts/validar_contratos.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdk.contratos import TIPOS, errores  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1] / "contracts" / "ejemplos"
cargar = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731

fallos = 0
print("Ejemplos válidos (deben pasar):")
for p in sorted(RAIZ.glob("*.json")):
    errs = errores(cargar(p))
    fallos += bool(errs)
    print(f"  {'✗' if errs else '✓'} {p.name}" + "".join(f"\n      {e}" for e in errs))
print("Ejemplos inválidos (deben fallar):")
for p in sorted((RAIZ / "invalidos").glob("*.json")):
    errs = errores(cargar(p))
    fallos += not errs
    print(f"  ✓ {p.name} → rechazado: {errs[0]}" if errs else f"  ✗ {p.name} → se aceptó y no debería")
for t in sorted(set(TIPOS) - {p.stem for p in RAIZ.glob("*.json")}):
    fallos += 1
    print(f"  ✗ falta el ejemplo contracts/ejemplos/{t}.json")
print()
if fallos:
    sys.exit(f"✗ {fallos} problema(s) en los contratos")
print(f"Parte 2 completada: {len(TIPOS)} tipos de evento con contrato y ejemplos validados ({', '.join(TIPOS)}).")
