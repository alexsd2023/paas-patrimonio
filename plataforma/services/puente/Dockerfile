# Se construye desde plataforma/ (necesita sdk/ y contracts/)
FROM python:3.12-slim
WORKDIR /app
COPY services/puente/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY sdk ./sdk
COPY contracts ./contracts
COPY services ./services
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "services.puente.app:app", "--host", "0.0.0.0", "--port", "8080"]
