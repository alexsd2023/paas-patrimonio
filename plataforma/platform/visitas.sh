#!/usr/bin/env bash
# Visitas por país de la demo pública, a partir del registro de accesos de Caddy.
# Uso, en el VPS:
#   ~/paas-patrimonio/plataforma/platform/visitas.sh     → informe HTML en ~/visitas.html
# Usa GoAccess (en Docker) y la base de países gratuita de DB-IP (CC BY 4.0), que se baja una vez al mes.
set -euo pipefail

REGISTROS=/var/log/caddy
GEO_DIR=/var/lib/geoip
GEO="$GEO_DIR/dbip-country-lite.mmdb"
SALIDA="$HOME/visitas.html"

if ! ls "$REGISTROS"/accesos*.log* >/dev/null 2>&1; then
  echo "No hay registro de accesos en $REGISTROS: ¿has recreado Caddy con el Caddyfile nuevo? (dc up -d --force-recreate caddy)"
  exit 1
fi

# Base de países: se renueva si no existe o tiene más de 30 días
if [ ! -s "$GEO" ] || [ -n "$(find "$GEO" -mtime +30 2>/dev/null)" ]; then
  sudo mkdir -p "$GEO_DIR"
  echo "Bajando la base de países de DB-IP…"
  for MES in "$(date +%Y-%m)" "$(date -d 'last month' +%Y-%m)"; do
    if curl -fsSL -o /tmp/dbip.mmdb.gz "https://download.db-ip.com/free/dbip-country-lite-$MES.mmdb.gz"; then
      gunzip -c /tmp/dbip.mmdb.gz | sudo tee "$GEO" >/dev/null && rm -f /tmp/dbip.mmdb.gz
      break
    fi
  done
  [ -s "$GEO" ] || { echo "No se pudo bajar la base de países"; exit 1; }
fi

# Todos los registros, también los rotados (.gz)
leer() { sudo sh -c "for f in $REGISTROS/accesos*.log*; do case \$f in *.gz) zcat \$f;; *) cat \$f;; esac; done"; }

leer | docker run --rm -i -e LANG=es_ES.UTF-8 -v "$GEO_DIR:/geo:ro" allinurl/goaccess - --log-format=CADDY \
      --geoip-database=/geo/dbip-country-lite.mmdb --anonymize-ip -o html > "$SALIDA"
echo "Informe: $SALIDA"
echo "Bájalo al Mac y ábrelo:  scp paas@$(hostname -I | awk '{print $1}'):$SALIDA ~/Downloads/ && open ~/Downloads/visitas.html"
