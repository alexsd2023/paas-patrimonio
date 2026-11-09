# Registro de modelos del PaaS (núcleo). Versión fijada: la misma que usan el HTR (mlflow-skinny) y los scripts del Mac.
FROM python:3.12-slim
RUN pip install --no-cache-dir "mlflow==3.17.2" && mkdir -p /mlflow
ENV MLFLOW_DISABLE_AGENT_HINT=1
EXPOSE 5000
