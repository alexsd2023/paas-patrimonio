#!/usr/bin/env bash
# Visitas a la demo pública: IP, hora de acceso y país, a partir del registro de accesos de Caddy.
# Una visita = peticiones seguidas de una misma IP sin más de 30 minutos de pausa.
# Uso, en el VPS:
#   ~/paas-patrimonio/plataforma/platform/visitas.sh          → últimos 7 días
#   ~/paas-patrimonio/plataforma/platform/visitas.sh 30       → últimos 30 días
#   ~/paas-patrimonio/plataforma/platform/visitas.sh 7 csv    → en CSV (para Excel): ... > visitas.csv
# País: base gratuita de DB-IP (CC BY 4.0), que se baja sola una vez al mes.
set -euo pipefail

DIAS=${1:-7}
FORMATO=${2:-tabla}
REGISTROS=/var/log/caddy
GEO=/var/lib/geoip/dbip-country-lite.mmdb

if ! sudo sh -c "ls $REGISTROS/accesos*.log*" >/dev/null 2>&1; then
  echo "No hay registro de accesos en $REGISTROS. Recrea Caddy: dc up -d --force-recreate caddy" >&2
  exit 1
fi

command -v mmdblookup >/dev/null || sudo apt-get -qq install -y mmdb-bin >/dev/null

if ! sudo test -s "$GEO" || [ -n "$(sudo find "$GEO" -mtime +30 2>/dev/null)" ]; then
  sudo mkdir -p "$(dirname "$GEO")"
  echo "Bajando la base de países de DB-IP…" >&2
  for MES in "$(date +%Y-%m)" "$(date -d 'last month' +%Y-%m)"; do
    if curl -fsSL -o /tmp/dbip.mmdb.gz "https://download.db-ip.com/free/dbip-country-lite-$MES.mmdb.gz"; then
      gunzip -c /tmp/dbip.mmdb.gz | sudo tee "$GEO" >/dev/null; rm -f /tmp/dbip.mmdb.gz; break
    fi
  done
  sudo test -s "$GEO" || { echo "No se pudo bajar la base de países" >&2; exit 1; }
fi

sudo sh -c "for f in $REGISTROS/accesos*.log*; do case \$f in *.gz) zcat \$f;; *) cat \$f;; esac; done" \
| python3 "$(dirname "$0")/visitas.py" "$DIAS" "$FORMATO" "$GEO"
