"""Crea un servicio nuevo a partir de la plantilla única (capacidades/_plantilla).

    python scripts/nuevo_servicio.py rag-colonial "Preguntas al corpus colonial" --modo integrada
    python scripts/nuevo_servicio.py catalogador "Catalogador del museo" --modo alojada
    python scripts/nuevo_servicio.py modernizador "Modernizador paleográfico" --modo externa

Después: edita capacidades/<id>/servicio.yaml, escribe procesar (integrada/alojada) o el adaptador (externa),
y, si corre dentro, añade su contenedor al docker-compose (como srv-modernizador-demo).
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("id")
p.add_argument("nombre")
p.add_argument("--modo", choices=["integrada", "alojada", "externa"], default="integrada")
a = p.parse_args()
if not re.match(r"^[a-z][a-z0-9-]{1,40}$", a.id):
    sys.exit("id: minúsculas, cifras y guiones (p. ej. rag-colonial)")
destino = RAIZ / "capacidades" / a.id.replace("-", "_")
if destino.exists():
    sys.exit(f"ya existe {destino}")
shutil.copytree(RAIZ / "capacidades" / "_plantilla", destino)
dentro = a.modo != "externa"
(destino / ("adaptador.py" if dentro else "app.py")).unlink()
if not dentro:
    (destino / "requirements.txt").unlink()
(destino / "__init__.py").write_text("")
yml = destino / "servicio.yaml"
texto = yml.read_text(encoding="utf-8").replace("__ID__", a.id).replace("__NOMBRE__", a.nombre).replace("__MODO__", a.modo)
yml.write_text("\n".join(texto.splitlines()[2:]) + "\n", encoding="utf-8")  # sin la cabecera de plantilla
print(f"✓ {destino.relative_to(RAIZ)} creado ({a.modo}). Edita servicio.yaml y "
      f"{'app.py (procesar)' if dentro else 'adaptador.py (ejecutar)'}.")
if dentro:
    print(f"  Contenedor: copia el bloque srv-modernizador-demo del docker-compose con SERVICIO: {destino.name}")
