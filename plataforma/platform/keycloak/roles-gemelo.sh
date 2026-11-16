#!/usr/bin/env sh
# Añade al Keycloak EN MARCHA lo que el gemelo patrimonial necesita y realm-paas.json ya trae para instalaciones
# nuevas (el realm solo se importa si no existe, porque Keycloak guarda las altas en su volumen):
#   · los roles gestor, conservador y tecnico;
#   · con --usuarios-prueba, los usuarios conservador-test, tecnico-test y gestor-test en archivo-villanueva
#     (contraseña = su rol). No lo uses en la demo pública.
# Uso, en el servidor, desde plataforma/platform:   sh keycloak/roles-gemelo.sh [--usuarios-prueba]
set -e
. ./.env 2>/dev/null || true
KC="docker compose exec -T keycloak /opt/keycloak/bin/kcadm.sh"
$KC config credentials --server http://localhost:8080 --realm master --user admin \
    --password "${KEYCLOAK_ADMIN_PASSWORD:-admin}" >/dev/null
for r in gestor conservador tecnico; do
  if $KC get "roles/$r" -r paas >/dev/null 2>&1; then echo "· rol $r ya existe"
  else $KC create roles -r paas -s name=$r >/dev/null && echo "✓ rol $r creado"; fi
done
if [ "$1" = "--usuarios-prueba" ]; then
  for r in conservador tecnico gestor; do
    u="$r-test"
    if [ -n "$($KC get users -r paas -q username=$u --fields id 2>/dev/null | grep id)" ]; then echo "· $u ya existe"; continue; fi
    $KC create users -r paas -s username=$u -s enabled=true -s emailVerified=true -s email=$r@archivo-villanueva.example \
        -s firstName=Prueba -s lastName=$r >/dev/null
    $KC set-password -r paas --username $u --new-password $r >/dev/null
    $KC add-roles -r paas --uusername $u --rolename $r >/dev/null
    gid=$($KC get groups -r paas -q search=archivo-villanueva --fields id,name | grep -B1 '"archivo-villanueva"' | grep id | sed 's/.*: "\(.*\)".*/\1/')
    uid=$($KC get users -r paas -q username=$u --fields id | grep id | sed 's/.*: "\(.*\)".*/\1/')
    $KC update users/$uid/groups/$gid -r paas -s realm=paas -s userId=$uid -s groupId=$gid -n >/dev/null
    echo "✓ $u (rol $r, archivo-villanueva)"
  done
fi
