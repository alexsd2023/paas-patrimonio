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
| Gemelo patrimonial (EN 15757) | `python scripts/gemelo_patrimonial_check.py` · antes, una vez: `python scripts/scorpio_temporal_check.py` |
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
  `gemelo` (Gemelo patrimonial): Inicio · Zona · Mapa · Alertas · Configuración. Una zona de tipo depósito enseña sus cajas y legajos.
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


## Instituciones sin intermediarios (autoservicio)

Una institución entra y trabaja sola, sin que el equipo del PaaS toque Keycloak ni ficheros:

1. **Alta** en `/panel/alta` (enlace en la pantalla de entrada): crea su grupo en Keycloak y su primera
   administradora (rol `admin-institucion`), y entra directamente. Con `REGISTRO=cerrado` el alta se cierra.
2. **Mi institución** (`/panel/institucion`), para quien la administra:
   - *Productos*: activa los que quiera. Una institución nueva empieza sin ninguno; las que ya existían lo
     tienen todo. Un producto sin activar no sale en la barra y su URL responde 403.
   - *Personas*: invita a su equipo con roles `archivera`, `paleografa` o `admin-institucion` (nunca `admin-paas`).
   - *Credenciales de API*: crea un cliente `app-<institución>-<nombre>` para que un sistema use la API con
     `client_credentials`, siempre con la identidad de la institución. El secreto se muestra una vez.
   - *Secretos*: los tokens que piden las capacidades (p. ej. `NER_TOKEN`), cifrados; nunca se vuelven a leer.
     Los de la plataforma los pone `admin.paas` (contraseña inicial `admin-paas`: cámbiala).
3. Por API, lo mismo en `/api/v1/institucion/{yo,activaciones,usuarios,credenciales}` y `/api/v1/secretos`.

Al darse de alta, el **catastro de la institución se conecta al bus** (sus suscripciones de Scorpio hacia el
puente), así sus productos reaccionan a lo que inscriba. Si en ese momento Scorpio no responde, el alta vale igual
y se repara sola al volver a arrancar `instituciones`, o a mano: `POST /instituciones/<id>/catastro` (admin-paas).

Piezas: `services/instituciones` (usa la API de administración de Keycloak con el cliente confidencial
`paas-gestion`, que solo puede gestionar usuarios, grupos y clientes del realm `paas`) y
`services/catalogo/secretos.py`. Comprobación: `python scripts/institucion_check.py` (también en la e2e).

**Al desplegar por primera vez** (en `platform/.env` del servidor):

```bash
echo "PAAS_GESTION_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
echo "CATALOGO_CLAVE=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >> .env
echo "CATALOGO_INTERNO_CLAVE=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
echo "REGISTRO=abierto" >> .env
```

Keycloak guarda ahora sus datos en el volumen `keycloak-data`: las instituciones dadas de alta sobreviven a
recrear el contenedor. El realm se importa solo si no existe, así que **los cambios futuros en
`realm-paas.json` ya no se aplican solos**: se hacen en Keycloak o borrando el volumen (se pierden las altas).

## Scriptorium en el PaaS: la receta «Edición anotada»

Tres herramientas de Ameyalli (Scriptorium · New Spain Fleets) publicadas como **capacidades externas**:

| Capacidad | Entra → sale | Llama a |
|---|---|---|
| `corrector-htr` | transcripción → transcripción | `/reviewer/{agent,mt5,latamgpt}` o `/rag/correct` (parámetro `motor`) |
| `modernizador-paleografico` | transcripción → texto modernizado (con el original y cada cambio) | `/modernizer/modernize` |
| `entidades-en-el-original` | texto modernizado → **edición anotada** | `/paleo-ner/map` |

La receta `flujos/edicion-anotada.yaml` las encadena y termina con la firma de una paleógrafa. Como el texto
modernizado lleva su original, el último paso recibe un solo documento: reconoce las entidades en la versión
moderna (donde el NER acierta más) y las marca sobre la grafía antigua (*Johan Peres* ↔ *Juan Pérez*).

Claves, en la consola (Mi institución → Secretos): `SCRIPTORIUM_API_KEY` si el despliegue de Ameyalli la
exige, y opcionalmente `GROQ_API_KEY`/`OPENROUTER_API_KEY` propias de cada institución para el modernizador.
Comprobación contra la API real: `python scripts/edicion_anotada_check.py --motor mt5`.

## Gemelo patrimonial: el microclima objetivo EN 15757

Especificación: «Gemelo Digital Patrimonial · especificación adaptada al PaaS» (v1.1). Reparto en las capas:

| Capa | Pieza | Qué hace |
|---|---|---|
| Capacidad | `capacidades/evaluacion_en15757` (`srv-evaluacion-en15757`) | `serie-ambiental` → `evaluacion-climatica`. Pura: no lee ni escribe el catastro. Cualquier institución la usa por API con sus propias series |
| Producto | `productos/gemelo` (v2.0) | Vistas, API `/api/v1/gemelo/…` y sus servicios `sensores` (simulador) y `conservacion` (series, evaluación, alertas) |
| Núcleo | contratos | `contracts/contextos/gdp-v1.jsonld` (público en `/contexts/v1/gdp.jsonld`), tipos `serie-ambiental` y `evaluacion-climatica`, eventos `zona.medicion`, `conservacion.evaluada` y `conservacion.riesgo` |
| Núcleo | identidad | Roles `gestor`, `conservador` y `tecnico` (asignables desde «Mi institución») |
| Núcleo | catálogo | `POST /interno/servicios/<id>/ejecutar`: un servicio de un producto usa una capacidad para una institución, con `CATALOGO_INTERNO_CLAVE` (no lo publica la puerta). Cuenta en el consumo de la institución |

**El cálculo (EN 15757:2010).** Media móvil centrada de 30 días; fluctuaciones = lectura − media; banda objetivo =
media + [P7, P93] de las fluctuaciones, con al menos ±10 puntos de humedad relativa. Se calibra con todo menos los
últimos 30 días, que se evalúan contra la media del clima histórico (la del mismo momento del año anterior, si hay
un año). Nivel: «medio» si el tiempo fuera de banda supera en 5 puntos al de su clima histórico, «alto» si lo supera
en 15 o si la humedad cambia más de 8 puntos en 2 horas. Todo son parámetros de la capacidad; el método simplificado
de la especificación v1.0 (media de 7 días, P10–P90) sigue disponible con `metodo: simplificado`.

**El recorrido.** El simulador escribe cada 30 s la lectura de cada sensor en su `IndoorEnvironmentObserved` →
la suscripción avisa al puente → `zona.medicion` → conservación la guarda. Cada hora (programación
`evaluacion-en15757` de Temporal, `EVALUACION_CRON`) conservación evalúa cada zona con la capacidad, escribe
`ClimateAssessment` y abre, agrava o propone cerrar `ConservationAlert`. Conservación reconoce y cierra cada alerta
con su causa: la firma va al proceso `AlertaConservacion` de Temporal y el notario la anota (también en el libro de
los legajos, si la zona es un depósito enlazado con su `Deposito`).

**Series.** Por defecto (`SERIES_ORIGEN=local`) conservación guarda las lecturas en su volumen (SQLite) y las de más
de 48 h las resume por horas. Si `python scripts/scorpio_temporal_check.py` pasa en tu servidor, `SERIES_ORIGEN=scorpio`
lee las lecturas reales del historial de Scorpio (API temporal NGSI-LD). El histórico sintético para calibrar
(13 meses, marcado `sintetico`) siempre está en conservación.

**La demo.** Al arrancar, el simulador inscribe el inmueble de ejemplo en `GEMELO_SEMILLA_TENANT`
(archivo-villanueva) y conservación genera su histórico y lo evalúa. Para otra institución: Gemelo patrimonial →
Configuración → «Crear el inmueble de ejemplo». En Configuración → «Simular para la demo», una desviación de 8 días
en el sótano abre una alerta alta en un momento.

**Al desplegarlo en un servidor que ya tenía la plataforma:**
1. `CATALOGO_INTERNO_CLAVE` en `platform/.env` (ver arriba cómo generarla).
2. Los roles en el Keycloak en marcha: `sh keycloak/roles-gemelo.sh` (desde `platform/`; con `--usuarios-prueba`
   crea también `conservador-test`, `tecnico-test` y `gestor-test`, contraseña = su rol).
3. `docker compose up -d --build srv-evaluacion-en15757 catalogo conservacion sensores puente procedencia panel instituciones`,
   y `docker compose up -d --force-recreate apisix` (rutas nuevas) y `docker compose run --rm suscripciones`
   (la suscripción de las observaciones; las instituciones dadas de alta después ya la reciben al registrarse,
   y las anteriores en el siguiente arranque de instituciones).

## Certificación documental (capacidad `certificacion-documental`)

Prueba que un texto existía en una fecha y que no se ha alterado. Entra un `texto`, sale una `evidencia`
(`contracts/tipos/evidencia.schema.json`): la huella SHA-256 del texto normalizado (`nfc-lf-strip`) y sus
anclajes fuera de la plataforma. Pura, como `evaluacion-en15757`: no guarda nada ni toca el catastro.

| Anclaje | Qué es | Modo en esta instalación |
|---|---|---|
| `blockchain` | Bitcoin vía OpenTimestamps: gratuito, verificable por cualquiera (p. ej. en opentimestamps.org) | **real** |
| `eidas` | Sello de tiempo RFC 3161, el protocolo de los prestadores cualificados europeos | **demo**: FreeTSA, sin valor legal. Producción: `EIDAS_TSA_URL`, `EIDAS_TSA_CERT`, `EIDAS_CUALIFICADO=si` |
| `nom151` | Constancia de conservación (México) | **simulado**: no la emite un PSC acreditado. Producción: conector con la API de un PSC |

- `operacion: certificar` (por defecto) con `anclajes: [blockchain, eidas, nom151]`.
- `operacion: actualizar`: entrada `{texto, evidencia}`; completa los anclajes pendientes (Bitcoin tarda unas horas).
- `POST /verificar` `{texto, evidencia}` → veredicto por anclaje. Sin cuota ni cuenta. `GET /anclajes`: qué ofrece.
- Un proveedor nuevo = una clase en `capacidades/certificacion_documental/proveedores/` (`anclar`, `actualizar`,
  `verificar`) registrada en su `__init__.py`.
- El contenedor `srv-certificacion-documental` necesita salida a internet (calendarios, TSA, explorador de bloques).
