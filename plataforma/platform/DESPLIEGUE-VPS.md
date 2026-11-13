# Despliegue de la demo pública en un VPS (Contabo)

Perfil aparte: `docker-compose.publico.yml` se monta encima del compose normal. Turing y la red local no cambian.

```
Internet ──► 80/443  Caddy (HTTPS automático)
                      ├─ paas.‹dominio›       → APISIX → consola y API
                      └─ auth.paas.‹dominio›  → Keycloak (su /admin, bloqueado)
             el resto (Kafka, Scorpio, Postgres, Fuseki, MLflow, Jaeger…) sin puertos publicados
```

Ficheros del perfil, todos en `plataforma/platform/`:

| Fichero | Para qué |
|---|---|
| `docker-compose.publico.yml` | Añade Caddy, quita los puertos del resto y pone a Keycloak detrás del proxy |
| `caddy/Caddyfile` | Los dos dominios, HTTPS, cookie `Secure` y bloqueo de `/admin` de Keycloak |
| `.env.publico.example` | Plantilla del `.env` del VPS |
| `copia-publico.sh` | Copia diaria (Postgres, volúmenes y `.env`), conserva 7 días |

En los comandos, `‹dominio›` es tu dominio y `‹IP›` la IP del VPS.

---

## 0 · En el Mac: subir el código a GitHub

El VPS se instala con `git clone`. Todo lo que no esté en GitHub no llega.

```bash
cd ~/venvs/paas-patrimonio
git status --short            # revisa que no haya nada que no quieras subir
git add plataforma
git commit -m "Perfil público para el VPS y cambios pendientes"
git push
```

## 1 · Contratar el VPS en Contabo

- **Producto:** Cloud VPS con **16 GB de RAM o más**. La plataforma tiene unos 20 contenedores y varios son Java.
- **Región:** Unión Europea (Alemania).
- **Imagen:** **Ubuntu 24.04**.
- **Acceso:** pega tu **clave SSH pública** si el formulario lo permite. En el Mac: `cat ~/.ssh/id_ed25519.pub`, o créala antes con `ssh-keygen -t ed25519`. Si no lo permite, pon una contraseña de root larga.
- Sin extras: ni panel de control (Plesk/cPanel) ni almacenamiento adicional.

Contabo tarda desde unos minutos hasta algunas horas en activarlo. Te manda la **IP** por correo.

## 2 · DNS

En el proveedor de tu dominio, crea dos registros **A** que apunten a la IP del VPS:

| Nombre | Tipo | Valor |
|---|---|---|
| `paas` | A | ‹IP› |
| `auth.paas` | A | ‹IP› |

Comprueba desde el Mac que ya resuelven (puede tardar unos minutos): `dig +short paas.‹dominio›` y `dig +short auth.paas.‹dominio›` deben devolver la IP. **Sin esto, Caddy no consigue los certificados en el paso 7.**

## 3 · Primer acceso y seguridad básica

```bash
ssh root@‹IP›

apt update && apt -y full-upgrade
timedatectl set-timezone Europe/Madrid

# usuario de trabajo, con tu clave SSH
adduser --disabled-password --gecos "" paas
usermod -aG sudo paas
echo "paas ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/paas
mkdir -p /home/paas/.ssh && cp ~/.ssh/authorized_keys /home/paas/.ssh/
chown -R paas:paas /home/paas/.ssh && chmod 700 /home/paas/.ssh

# cortafuegos: solo SSH, HTTP y HTTPS
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443 && ufw --force enable

# 4 GB de swap: colchón para los picos de Java
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# actualizaciones de seguridad automáticas
apt -y install unattended-upgrades fail2ban
```

**Antes de cerrar esta sesión**, abre otra terminal y comprueba que entras con `ssh paas@‹IP›`. Si funciona, desactiva el acceso por contraseña y el de root:

```bash
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh
```

Si Contabo no te dejó poner la clave SSH al contratar, cópiala desde el Mac antes de este paso: `ssh-copy-id root@‹IP›`.

## 4 · Docker

Desde aquí, todo como `paas` (`ssh paas@‹IP›`):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker paas
exit        # sal y vuelve a entrar para que valga el grupo docker
```

```bash
ssh paas@‹IP›
docker run --rm hello-world
```

> **Ojo con ufw:** Docker abre en el cortafuegos todos los puertos que publica un contenedor, aunque ufw diga otra cosa. Por eso el perfil público quita todos los `ports:` salvo los de Caddy. No añadas `ports:` a ningún servicio en el VPS.

## 5 · Clonar el repositorio con una clave de solo lectura

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/github_paas -C "vps-paas"
cat ~/.ssh/github_paas.pub
```

En GitHub: **alexsd2023/paas-patrimonio → Settings → Deploy keys → Add deploy key**. Pega la clave y **no** marques «Allow write access».

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_paas
EOF
git clone git@github.com:alexsd2023/paas-patrimonio.git ~/paas-patrimonio
cd ~/paas-patrimonio/plataforma
```

## 6 · Configuración: `platform/.env`

```bash
cp platform/.env.publico.example platform/.env
chmod 600 platform/.env
nano platform/.env
```

Rellena todo lo marcado con `‹…›`:
- **Dominios:** `DOMINIO`, `AUTH_DOMINIO`, `KEYCLOAK_PUBLICO`, `API_PUBLICO` y el final de `MLFLOW_HOSTS`.
- **Correo:** `ACME_EMAIL`.
- **Secretos:** uno distinto para cada campo. Genera cada uno con `openssl rand -base64 32 | tr -d '/+=' | cut -c1-32`.
- **`CATALOGO_CLAVE`:** con el comando que aparece en el propio fichero.

**Guarda una copia del `.env` fuera del VPS**, en tu gestor de contraseñas. Sin `CATALOGO_CLAVE` no se pueden leer los secretos que guarden las instituciones.

Un atajo para no escribir el comando largo cada vez:

```bash
cat >> ~/.bashrc <<'EOF'
dc() { docker compose --env-file platform/.env -f platform/docker-compose.yml -f platform/docker-compose.publico.yml "$@"; }
EOF
source ~/.bashrc
```

## 7 · Arrancar

```bash
cd ~/paas-patrimonio/plataforma
dc config --quiet && echo "configuración OK"
dc up -d --build          # la primera vez tarda (construye las imágenes Python y baja las de Java)
dc ps                     # espera a que todo esté running / healthy (Keycloak y Scorpio, 1–3 min)
dc logs -f caddy          # deben salir «certificate obtained successfully» para los dos dominios
```

Si Caddy no consigue los certificados, el DNS aún no apunta a la IP (paso 2), o el 80/443 no están abiertos.

## 8 · Cambiar las contraseñas de los usuarios sembrados

El realm trae usuarios de prueba con contraseñas conocidas. En una demo abierta hay que cambiarlas:

```bash
cd ~/paas-patrimonio/plataforma
set -a; . platform/.env; set +a
KC="dc exec -T keycloak /opt/keycloak/bin/kcadm.sh"
$KC config credentials --server http://localhost:8080 --realm master --user admin --password "$KEYCLOAK_ADMIN_PASSWORD"
for u in admin.paas m.ortega paleografa-test p.otro; do
  p=$(openssl rand -base64 18 | tr -d '/+=')
  $KC set-password -r paas --username "$u" --new-password "$p" && echo "$u  $p"
done
```

Las contraseñas se muestran **solo esta vez**. Apúntalas en tu gestor.

## 9 · Comprobaciones

Desde el Mac:

```bash
# 1. La consola responde por HTTPS
curl -sI https://paas.‹dominio›/panel | head -1                  # HTTP/2 200 (o 302)
# 2. Keycloak publica su realm con el emisor correcto
curl -s https://auth.paas.‹dominio›/realms/paas | python3 -m json.tool | grep issuer   # https://auth.paas.‹dominio›/realms/paas
# 3. La administración de Keycloak, cerrada
curl -s -o /dev/null -w "%{http_code}\n" https://auth.paas.‹dominio›/admin/      # 403
# 4. Nada más expuesto: todos deben fallar
for p in 3030 5000 8180 9080 9090 9092 16686; do nc -z -w 3 ‹IP› $p && echo "ABIERTO $p" || echo "cerrado $p"; done
```

En el navegador:
1. `https://paas.‹dominio›/panel`: entra como `m.ortega` con su nueva contraseña.
2. Abre las consolas técnicas (Temporal, Kafka, Jaeger, MLflow, Fuseki) desde la consola.
3. Da de alta una institución de prueba en `/panel/alta`, activa el Legajo y entrega un legajo. Debe avanzar solo hasta la transcripción.
4. En **Recetas**, lanza «Edición anotada» con una institución que tenga su propia `SCRIPTORIUM_API_KEY`.

Si necesitas la consola de administración de Keycloak: pon tu IP en `ADMIN_IP` (por ejemplo `81.2.3.4/32`; la ves en `curl ifconfig.me`), ejecuta `dc up -d caddy` y entra en `https://auth.paas.‹dominio›/admin`. Al terminar, vuelve a poner `127.0.0.1/32` y repite `dc up -d caddy`.

## 10 · Copias de seguridad diarias

```bash
chmod +x ~/paas-patrimonio/plataforma/platform/copia-publico.sh
sudo mkdir -p /var/backups/paas && sudo chown paas /var/backups/paas
~/paas-patrimonio/plataforma/platform/copia-publico.sh      # prueba manual
( crontab -l 2>/dev/null; echo "30 4 * * * $HOME/paas-patrimonio/plataforma/platform/copia-publico.sh >> $HOME/copia.log 2>&1" ) | crontab -
```

Las copias se guardan en el mismo VPS. Para no perderlas si el VPS cae, bájalas de vez en cuando al Mac: `rsync -av paas@‹IP›:/var/backups/paas/ ~/copias-paas/`. Si tu plan de Contabo incluye **snapshots**, haz también uno desde su panel tras el paso 9.

## 11 · Actualizar

En el Mac, `git push` de los cambios. Después, en el VPS:

```bash
cd ~/paas-patrimonio/plataforma
git pull
dc up -d --build
dc ps
```

---

## Lo que esta demo no cubre todavía

- **Límite de altas.** El alta está abierta sin límite por hora. Si aparecen altas de bots, pon `REGISTRO=cerrado` y ejecuta `dc up -d instituciones`.
- **Usuarios de prueba en la pantalla de entrada.** La consola sigue mostrando los nombres de los usuarios de prueba, aunque sus contraseñas ya no son las de ejemplo. Quitarlos requiere un pequeño cambio de código.
- **Consolas técnicas compartidas.** Enseñan los datos de todas las instituciones. Conviene un aviso de «no subas datos reales» y un reinicio periódico de la demo.
- **Componentes en modo desarrollo.** Keycloak (H2) y Temporal funcionan en modo desarrollo, Kafka tiene un solo nodo y las imágenes no tienen versión fija. No hay monitorización ni alertas. Todo eso es la fase siguiente si la demo pasa a ser un servicio.
