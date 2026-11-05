# Imagen común de los servicios Python. Se construye desde plataforma/:
#   docker build -f services/Dockerfile --build-arg SERVICIO=procedencia .
FROM python:3.12-slim
ARG SERVICIO
WORKDIR /app
COPY services/${SERVICIO}/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && mkdir -p /data
COPY sdk ./sdk
COPY contracts ./contracts
COPY services ./services
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 SERVICIO=${SERVICIO}
EXPOSE 8080
CMD uvicorn services.${SERVICIO}.app:app --host 0.0.0.0 --port 8080
