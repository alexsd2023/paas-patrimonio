"""Crea un servicio nuevo a partir de la plantilla única (capacidades/_plantilla).

    python scripts/nuevo_servicio.py rag-colonial "Preguntas al corpus colonial" --modo interno
    python scripts/nuevo_servicio.py modernizador "Modernizador paleográfico" --modo externo

Después: edita capacidades/<id>/servicio.yaml, escribe procesar (interno) o el adaptador (externo),
y, si es interno, añade su contenedor al docker-compose (como srv-modernizador-demo).
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
p.add_argument("--modo", choices=["interno", "externo"], default="interno")
a = p.parse_args()
if not re.match(r"^[a-z][a-z0-9-]{1,40}$", a.id):
    sys.exit("id: minúsculas, cifras y guiones (p. ej. rag-colonial)")
destino = RAIZ / "capacidades" / a.id.replace("-", "_")
if destino.exists():
    sys.exit(f"ya existe {destino}")
shutil.copytree(RAIZ / "capacidades" / "_plantilla", destino)
(destino / ("adaptador.py" if a.modo == "interno" else "app.py")).unlink()
if a.modo == "externo":
    (destino / "requirements.txt").unlink()
(destino / "__init__.py").write_text("")
yml = destino / "servicio.yaml"
texto = yml.read_text(encoding="utf-8").replace("__ID__", a.id).replace("__NOMBRE__", a.nombre).replace("__MODO__", a.modo)
yml.write_text("\n".join(texto.splitlines()[2:]) + "\n", encoding="utf-8")  # sin la cabecera de plantilla
print(f"✓ {destino.relative_to(RAIZ)} creado ({a.modo}). Edita servicio.yaml y "
      f"{'app.py (procesar)' if a.modo == 'interno' else 'adaptador.py (ejecutar)'}.")
if a.modo == "interno":
    print(f"  Contenedor: copia el bloque srv-modernizador-demo del docker-compose con SERVICIO: {destino.name}")
