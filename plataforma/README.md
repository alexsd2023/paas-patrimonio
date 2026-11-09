# Plataforma · walking skeleton

Código del walking skeleton. No se publica en la web (ver `.vercelignore`).

- `platform/` → servicios, se ejecutan con Docker en el servidor Ubuntu
- `scripts/`  → comprobaciones, se ejecutan desde el Mac con el venv

## Parte 1 · Kafka

**Servidor** (copia `platform/` al servidor, p. ej. `scp -r platform usuario@servidor:~/paas/`):

    cd ~/paas/platform
    cp .env.example .env        # edita KAFKA_HOST
    docker compose up -d
    docker compose logs kafka-init    # debe listar: activos, htr

**Mac:**

    cd plataforma
    cp .env.example .env        # edita KAFKA_BOOTSTRAP
    source ../.venv/bin/activate
    pip install -r requirements.txt
    python scripts/kafka_check.py

## Desplegar en el servidor (desde la parte 4)

El servidor necesita ya toda la carpeta (sdk, contracts, services), no solo `platform/`.
Desde el Mac, en `plataforma/`:

    rsync -av --inplace --chmod=Du=rwx,go=rx,Fu=rw,go=r --exclude .venv --exclude .env --exclude __pycache__ ./ usuario@192.168.1.30:~/paas/

`--exclude .env` conserva el `platform/.env` que ya tienes en el servidor. `--inplace` y `--chmod` hacen que APISIX y Keycloak (que no corren como root) puedan leer sus ficheros y los recarguen. Después, en el servidor:

    cd ~/paas/platform
    docker compose up -d --build
    docker compose ps               # kafka y puente "healthy"; kafka-init "exited (0)"

## Comprobaciones

| Parte | Comando (Mac, en plataforma/, venv activo) |
|---|---|
| 1 · Kafka | `python scripts/kafka_check.py` |
| 2 · Contratos | `python scripts/validar_contratos.py` |
| 3 · Librería | `python -m pytest tests` y `python scripts/eventos_check.py` |
| 4 · Puente | `python scripts/puente_check.py` |
| 5 · Consumidores | `python scripts/consumidores_check.py` |
| 6 · Catastro | `python scripts/registro_check.py` |
| 7 · Procesos | `python scripts/proceso_check.py` (procesos visibles en http://servidor:8233) |
| 8 · Puerta | `python scripts/puerta_check.py` |
| 9 · Sala de lectura (IIIF) | `python scripts/ingesta_check.py` |
| Gemelo digital | `python scripts/gemelo_check.py` |
| Servicios y flujos | `python scripts/catalogo_check.py` |
| 10 · Notario en Fuseki | `python scripts/fuseki_check.py` |
| 11 · Trazas | `python scripts/traza_check.py` (Jaeger en http://servidor:16686) |
| 12 · Datos y modelos | `python scripts/modelo_check.py` (MLflow en http://servidor:5000) |
| Vistas | Consola: http://servidor:9080/panel · Kafka UI: http://servidor:8095 · Temporal: http://servidor:8233 |

## La plataforma en cuatro capas

| Capa | Carpeta | Qué es | Cómo se añade algo |
|---|---|---|---|
| **Núcleo** | `services/`, `sdk/`, `contracts/`, `platform/` | Lo común a todos: identidad, puerta, bus, catastro, procesos, notario, trazas, consola y catálogo | Solo el equipo del PaaS |
| **Capacidades** | `capacidades/<id>/servicio.yaml` | Servicios reutilizables (NER, modernizador, RAG…) que se usan sueltos, por API o en flujos (`flujos/*.yaml`) | `python scripts/nuevo_servicio.py <id> "<nombre>" --modo interno\|externo` |
| **Productos** | `productos/<id>/producto.yaml` | Lo que activa una institución para un trabajo concreto, con sus propias vistas (legajo, gemelo) | Carpeta con `producto.yaml` y `montar(nucleo, producto)` |
| **Conectores** | `conectores/<id>/conector.yaml` | Puentes con los sistemas que la institución ya tiene (cosecha OAI-PMH) | Carpeta con `conector.yaml` y `ejecutar(config, ctx)` |

La consola (`/panel`) tiene un grupo por capa en la barra lateral. Ninguna capa toca el código de otra:
un producto declara qué capacidades `requiere` y qué `contenedores` son suyos; un conector declara qué
tipos `escribe` en el catastro; una capacidad declara qué tipo de documento recibe y entrega.

- **Capacidades** · `ner-historico` es el NER de Lancaster en Hugging Face (externo; su token en `NER_TOKEN` del
  `platform/.env`). El catálogo (`services/catalogo`) los publica, controla acceso y cuotas, y ejecuta los flujos
  con un único workflow de Temporal (`FlujoReceta`). API: `/api/v1/servicios`, `/api/v1/trabajos/<id>`, `/api/v1/flujos`.
- **Productos** · se montan en `/panel/productos/<id>`. `legajo`: Legajos · Entregar · Validar · Tramos.
  `gemelo`: Depósitos · Cajas y legajos.
- **Conectores** · cada institución rellena en la consola el formulario que pide su `conector.yaml` y lo ejecuta.
  `oai-pmh` cosecha Dublin Core y lo inscribe como `RegistroCatalografico` (cosechar dos veces actualiza, no
  duplica). Al terminar sale la carta `conector.ejecutado`. API: `/api/v1/conectores`, `/api/v1/ejecuciones/<id>`,
  `/api/v1/registros/<tipo>`.

## Parte 12 · Datos versionados (DVC) y registro de modelos (MLflow)

La copia del taller dice de dónde sale: **copia → modelo (versión) → run de entrenamiento → datos (versión DVC) → commit**.

- `datos/gt/` es el ground truth (hoy una muestra sintética de 35 líneas). Git guarda `datos/gt.dvc`; los ficheros
  van al remoto de DVC, una carpeta del servidor por SSH.
- `modelos/htr/entrenar.py` entrena (hoy, simulado), evalúa CER/WER con líneas que nunca usa para entrenar y
  registra el modelo en MLflow con la versión de los datos y el commit. `--produccion` le pone el alias.
- **MLflow** (núcleo, `http://servidor:5000`) decide qué modelo usa el taller: el que tiene el alias `produccion`.
  Cambiarlo cambia el modelo sin reiniciar nada (`sdk/modelos.py`, caché de 60 s).
- La copia en el catastro, la carta `htr.completado` y el acta del notario citan modelo, run y datos.

Una vez, en el Mac (en `plataforma/`, venv activo; la raíz de git es la carpeta de arriba):

    pip install -r requirements.txt
    dvc init --subdir
    ssh alexander@192.168.1.30 mkdir -p paas-dvc
    dvc remote add -d servidor ssh://alexander@192.168.1.30/home/alexander/paas-dvc
    dvc add datos/gt
    git add datos/gt.dvc datos/.gitignore .dvc/config .dvcignore
    git commit -m "Parte 12: ground truth bajo DVC"
    dvc push

Cada vez que entrenes:

    python modelos/htr/entrenar.py --produccion
    python scripts/modelo_check.py

## Consolas técnicas dentro de la consola

Temporal, Kafka UI, Jaeger, Fuseki y MLflow se abren **dentro de la consola** (`/panel/nucleo/<herramienta>`), servidas
por la puerta en `/panel/temporal`, `/panel/kafka`, `/panel/jaeger`, `/panel/fuseki` y `/panel/mlflow`. Antes de dejar
pasar, APISIX pregunta a la consola (`forward-auth` → `/panel/api/autorizar`): hace falta sesión o un token de Keycloak.
Kafka UI y la interfaz de Temporal ya no tienen puerto propio. Jaeger, Fuseki y MLflow lo conservan para los scripts
del Mac (`JAEGER_URL` pasa a ser `http://servidor:16686/panel/jaeger`). Keycloak sigue abriéndose en otra pestaña.

## Parte 13 · Prueba de punta a punta e integración continua

`tests_e2e/ejecutar.py` recorre la plataforma entera desde dentro de la red de docker: espera a todas las piezas,
entrena y pone en producción un modelo de prueba, sirve un repositorio OAI-PMH de prueba y ejecuta en orden las
comprobaciones de todas las partes (las mismas `scripts/*_check.py`). Sale con 0 solo si todo pasa.

Corre en un proyecto aislado (`paas-ci`, sin puertos publicados), así que no choca con la plataforma de desarrollo:

    docker compose -p paas-ci --env-file platform/ci.env -f platform/docker-compose.yml -f platform/ci.override.yml up -d --build
    docker compose -p paas-ci --env-file platform/ci.env -f platform/docker-compose.yml -f platform/ci.override.yml --profile e2e up --build --exit-code-from e2e e2e
    docker compose -p paas-ci --env-file platform/ci.env -f platform/docker-compose.yml -f platform/ci.override.yml --profile e2e down -v

En GitHub (`.github/workflows/ci.yml`, en la raíz del repositorio): en cada push a `main` y en cada pull request,
las pruebas rápidas corren en GitHub y, si pasan, la de punta a punta en **Turing** (runner propio, etiqueta `turing`).
Nunca corre con código de forks.

Runner en Turing (una vez): en GitHub, *Settings → Actions → Runners → New self-hosted runner → Linux x64*, y en
el servidor los comandos que muestra, con `--labels turing` en `config.sh`; después `sudo ./svc.sh install` y
`sudo ./svc.sh start`. El usuario del runner tiene que poder usar docker (grupo `docker`). Hace falta
Docker Compose 2.24 o posterior (`docker compose version`).

