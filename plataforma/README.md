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

    rsync -av --exclude .venv --exclude .env --exclude __pycache__ ./ usuario@192.168.1.30:~/paas/

`--exclude .env` conserva el `platform/.env` que ya tienes en el servidor. Después, en el servidor:

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
