# Contenedor de la prueba de punta a punta: recorre la plataforma desde dentro de la red de docker.
# Se construye desde plataforma/ (ver platform/ci.override.yml).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
# lo mismo que el Mac, salvo MLflow completo (basta el cliente) y DVC (la prueba usa su propio ground truth)
RUN grep -vE "^(mlflow|dvc)" /tmp/requirements.txt > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt "mlflow-skinny==3.17.2" pillow
COPY . .
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
EXPOSE 8000
CMD ["python", "tests_e2e/ejecutar.py"]
