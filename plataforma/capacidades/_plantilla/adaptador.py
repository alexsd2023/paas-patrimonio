"""Servicio EXTERNO: traduce el documento común a la API que ya existe y de vuelta."""
import os


def ejecutar(manifiesto, entrada: dict, parametros: dict, http) -> dict:
    cfg = manifiesto.externo or {}
    cab = {"Authorization": f"Bearer {os.environ[cfg['token_env']]}"} if cfg.get("token_env") else {}
    r = http.post(f"{manifiesto.url}{cfg.get('ruta', '/')}", json={"text": entrada["texto"]}, headers=cab,
                  timeout=cfg.get("espera_s", 60))
    r.raise_for_status()
    return {"texto": entrada["texto"]}   # ← convierte aquí r.json() al tipo «salida»
