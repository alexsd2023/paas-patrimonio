"""Registro de modelos (MLflow): qué modelo está «en producción» y de qué datos sale.

Cualquier servicio que use un modelo (el HTR hoy; el NER o un modernizador mañana) pregunta aquí
en vez de llevar la versión escrita en una variable de entorno:

    reg = RegistroModelos("http://mlflow:5000", "htr-paleografico")
    m = reg.actual()        # o None si no hay ninguno con el alias «produccion»
    m["etiqueta"]           # htr-paleografico@3     ← lo que se escribe en la copia y en el acta
    m["datos"]              # versión DVC de los datos con que se entrenó (md5 del .dvc)
    m["run"], m["cer"], m["commit"], m["artefacto"]   # el run de MLflow, su métrica, el código, el modelo

Se guarda en memoria `ttl` segundos: cambiar el alias en MLflow cambia el modelo sin reiniciar nada.
"""
import json
import logging
import os
import time
from typing import Any, Dict, Optional

log = logging.getLogger("modelos")
ALIAS = "produccion"


class RegistroModelos:
    def __init__(self, tracking_uri: str, nombre: str, alias: str = ALIAS, ttl: float = 60.0):
        self.tracking_uri, self.nombre, self.alias, self.ttl = tracking_uri, nombre, alias, ttl
        self._cache: Optional[Dict[str, Any]] = None
        self._cuando = 0.0
        self._artefactos: Dict[str, dict] = {}

    def _cliente(self):
        # si MLflow no responde, el taller no puede quedarse esperando: un intento corto y seguir
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR", "1")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
        from mlflow.tracking import MlflowClient
        return MlflowClient(tracking_uri=self.tracking_uri, registry_uri=self.tracking_uri)

    def actual(self) -> Optional[Dict[str, Any]]:
        if self._cuando and time.monotonic() - self._cuando < self.ttl:
            return self._cache
        try:
            self._cache = self._leer()
        except Exception as e:  # noqa: BLE001  sin registro (o sin modelo) se sigue con lo que hubiera
            log.warning("no se pudo leer el modelo %s@%s de %s: %s", self.nombre, self.alias, self.tracking_uri, e)
        self._cuando = time.monotonic()  # también tras un fallo: no se vuelve a preguntar hasta pasado el ttl
        return self._cache

    def _leer(self) -> Dict[str, Any]:
        cli = self._cliente()
        v = cli.get_model_version_by_alias(self.nombre, self.alias)
        etiquetas = dict(v.tags or {})
        clave = f"{self.nombre}/{v.version}"
        if clave not in self._artefactos:
            from mlflow.artifacts import download_artifacts
            os.environ.setdefault("MLFLOW_TRACKING_URI", self.tracking_uri)
            carpeta = download_artifacts(artifact_uri=f"runs:/{v.run_id}/modelo", tracking_uri=self.tracking_uri)
            with open(os.path.join(carpeta, "modelo.json"), encoding="utf-8") as f:
                self._artefactos[clave] = json.load(f)
        cer = etiquetas.get("cer")
        return {"nombre": self.nombre, "version": int(v.version), "etiqueta": f"{self.nombre}@{v.version}",
                "run": v.run_id, "datos": etiquetas.get("datos.version"), "commit": etiquetas.get("git.commit"),
                "cer": float(cer) if cer not in (None, "") else None, "simulado": etiquetas.get("simulado") == "true",
                "artefacto": self._artefactos[clave]}
