# Imagen común de los servicios Python. Se construye desde plataforma/:
#   docker build -f services/Dockerfile --build-arg SERVICIO=procedencia .
#   docker build -f services/Dockerfile --build-arg CARPETA=capacidades --build-arg SERVICIO=modernizador_demo .
FROM python:3.12-slim
ARG SERVICIO
ARG CARPETA=services
WORKDIR /app
COPY ${CARPETA}/${SERVICIO}/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && mkdir -p /data
COPY sdk ./sdk
COPY contracts ./contracts
COPY services ./services
# las capas que no son núcleo: productos, capacidades, conectores; y las plantillas de flujo
COPY productos ./productos
COPY capacidades ./capacidades
COPY conectores ./conectores
COPY flujos ./flujos
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 SERVICIO=${SERVICIO} MODULO=${CARPETA}.${SERVICIO}.app
EXPOSE 8080
CMD uvicorn ${MODULO}:app --host 0.0.0.0 --port 8080
