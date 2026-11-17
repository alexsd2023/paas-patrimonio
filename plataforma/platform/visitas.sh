#!/usr/bin/env bash
# Visitas a la demo pública: IP, hora de llegada, tiempo dentro, sitio, país, región y ciudad,
# a partir del registro de accesos de Caddy.
# Una visita = peticiones seguidas de una misma IP sin más de 30 minutos de pausa.
# Uso, en el VPS (los argumentos van en cualquier orden):
#   visitas.sh               → últimos 7 días, todos los países
#   visitas.sh 30            → últimos 30 días
#   visitas.sh 30 MX         → solo México (código de país de 2 letras: ES, MX, US…)
#   visitas.sh 30 csv > ~/visitas.csv   → en CSV (para Excel)
# Ubicación: base gratuita «IP to City Lite» de DB-IP (CC BY 4.0), que se baja sola una vez al mes.
# Es aproximada: la ciudad puede ser la del proveedor de internet, no la de la persona.
set -euo pipefail

REGISTROS=/var/log/caddy
GEO=/var/lib/geoip/dbip-city-lite.mmdb

if ! sudo sh -c "ls $REGISTROS/accesos*.log*" >/dev/null 2>&1; then
  echo "No hay registro de accesos en $REGISTROS. Recrea Caddy: dc up -d --force-recreate caddy" >&2
  exit 1
fi

command -v mmdblookup >/dev/null || sudo apt-get -qq install -y mmdb-bin >/dev/null

if ! sudo test -s "$GEO" || [ -n "$(sudo find "$GEO" -mtime +30 2>/dev/null)" ]; then
  sudo mkdir -p "$(dirname "$GEO")"
  echo "Bajando la base de ubicaciones de DB-IP (unos 130 MB)…" >&2
  for MES in "$(date +%Y-%m)" "$(date -d 'last month' +%Y-%m)"; do
    if curl -fsSL -o /tmp/dbip.mmdb.gz "https://download.db-ip.com/free/dbip-city-lite-$MES.mmdb.gz"; then
      gunzip -c /tmp/dbip.mmdb.gz | sudo tee "$GEO" >/dev/null; rm -f /tmp/dbip.mmdb.gz; break
    fi
  done
  sudo test -s "$GEO" || { echo "No se pudo bajar la base de ubicaciones" >&2; exit 1; }
fi

sudo sh -c "for f in $REGISTROS/accesos*.log*; do case \$f in *.gz) zcat \$f;; *) cat \$f;; esac; done" \
| python3 "$(dirname "$0")/visitas.py" "$GEO" "$@"
