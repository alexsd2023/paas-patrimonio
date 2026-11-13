#!/usr/bin/env bash
# Copia diaria de la demo pública. Se ejecuta en el VPS desde cron (ver DESPLIEGUE-VPS.md, paso 10).
#   · volcado de Postgres (catastro de Scorpio)
#   · un .tgz por volumen de datos
#   · conserva los últimos 7 días
# Es una copia «en caliente»: suficiente para una demo. Las bases SQLite/H2 pueden quedar a medio escribir;
# si una restauración falla, usa la del día anterior.
set -euo pipefail

PROYECTO=paas
DESTINO=${DESTINO:-/var/backups/paas}
HOY=$(date +%F)
DIR="$DESTINO/$HOY"
VOLUMENES="keycloak-data instituciones-data catalogo-data mlflow-data kafka-data procedencia-data gestoria-data temporal-data iiif-data fuseki-data caddy-data"

mkdir -p "$DIR"

# 1 · Postgres (Scorpio)
docker exec "${PROYECTO}-postgres-1" pg_dump -U ngb -d ngb -Fc > "$DIR/scorpio.pgdump"

# 2 · Volúmenes
for v in $VOLUMENES; do
  if docker volume inspect "${PROYECTO}_${v}" >/dev/null 2>&1; then
    docker run --rm -v "${PROYECTO}_${v}:/v:ro" -v "$DIR:/b" busybox:1.36 tar czf "/b/${v}.tgz" -C /v .
  fi
done

# 3 · El .env (contiene la clave del catálogo: sin ella los secretos guardados no se pueden leer)
cp "$(dirname "$0")/.env" "$DIR/env" && chmod 600 "$DIR/env"

# 4 · Borrar las de hace más de 7 días
find "$DESTINO" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

echo "copia $DIR: $(du -sh "$DIR" | cut -f1)"
