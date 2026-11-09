"""Entrena (o simula) el modelo HTR, lo evalúa y lo registra en MLflow con la versión exacta de sus datos.

    python modelos/htr/entrenar.py                       # registra una versión nueva
    python modelos/htr/entrenar.py --produccion          # y la pone en producción (alias «produccion»)

Lo que queda en MLflow por cada entrenamiento:
    parámetros   tasa_error, lineas_entrenamiento, lineas_evaluacion
    métricas     cer, wer  (sobre las líneas de evaluación, que nunca se usan para entrenar)
    etiquetas    datos.version (md5 de datos/gt.dvc) · git.commit · simulado
    artefacto    modelo/modelo.json  → lo que carga el servicio HTR
    registro     htr-paleografico, versión N (con las mismas etiquetas) y, si se pide, alias «produccion»

HOY EL MODELO ES SIMULADO: la «predicción» es la línea correcta con errores introducidos a una tasa fija,
para que CER y WER sean números reales calculados igual que con un modelo de verdad. Para Kraken, sustituye
`entrenar()` y `predecir()` (p. ej. `ketos train` y `kraken ... ocr`) y deja igual el registro.
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

RAIZ = Path(__file__).resolve().parents[2]
NOMBRE = "htr-paleografico"


# ---------------- datos ----------------

def leer_lineas(carpeta: Path) -> List[Dict[str, Any]]:
    with open(Path(carpeta) / "lineas.jsonl", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def partir(lineas: List[dict], cada: int = 5) -> Tuple[List[dict], List[dict]]:
    """Evaluación = una de cada `cada` líneas (siempre las mismas: comparable entre versiones)."""
    ev = [x for i, x in enumerate(lineas) if i % cada == cada - 1]
    return [x for i, x in enumerate(lineas) if i % cada != cada - 1], ev


def version_datos(carpeta: Path) -> Tuple[str, str]:
    """(versión, origen). Con DVC: el md5 que fija datos/gt.dvc. Sin DVC: md5 calculado aquí (y se avisa)."""
    dvc = Path(str(carpeta).rstrip("/") + ".dvc")
    if dvc.exists():
        import yaml
        outs = (yaml.safe_load(dvc.read_text()) or {}).get("outs") or [{}]
        md5 = str(outs[0].get("md5", "")).replace(".dir", "")
        if md5:
            return md5, "dvc"
    h = hashlib.md5()
    for p in sorted(Path(carpeta).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(carpeta).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest(), "calculado"


def commit_git() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout.strip()
        sucio = subprocess.run(["git", "status", "--porcelain", "--", "modelos", "datos"], cwd=RAIZ,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-con-cambios" if sucio else "")
    except (OSError, subprocess.CalledProcessError):
        return "sin-git"


# ---------------- métricas ----------------

def distancia(a, b) -> int:
    """Levenshtein (sirve para cadenas de caracteres y para listas de palabras)."""
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def cer(refs: List[str], hyps: List[str]) -> float:
    return sum(distancia(r, h) for r, h in zip(refs, hyps)) / max(1, sum(len(r) for r in refs))


def wer(refs: List[str], hyps: List[str]) -> float:
    return sum(distancia(r.split(), h.split()) for r, h in zip(refs, hyps)) / max(1, sum(len(r.split()) for r in refs))


# ---------------- modelo (simulado) ----------------

def entrenar(train: List[dict]) -> Dict[str, Any]:
    palabras: Dict[str, int] = {}
    for x in train:
        for p in x["texto"].split():
            palabras[p] = palabras.get(p, 0) + 1
    primero = train[0]["documento"] if train else ""
    return {"tipo": "simulado", "caracteres": sorted({c for x in train for c in x["texto"]}),
            "lexico": sorted(palabras, key=lambda p: -palabras[p])[:300],
            "muestra": " ".join(x["texto"] for x in train if x["documento"] == primero)}


def predecir(modelo: Dict[str, Any], texto_real: str, tasa: float, semilla: int) -> str:
    """Simulación de un HTR: la línea real con sustituciones, borrados e inserciones a `tasa` por carácter."""
    rnd, out = random.Random(semilla), []
    alfabeto = modelo["caracteres"] or list("abcdefghijklmnopqrstuvwxyz")
    for c in texto_real:
        r = rnd.random()
        if r < tasa / 3:
            continue
        if r < 2 * tasa / 3:
            out.append(rnd.choice(alfabeto))
        elif r < tasa:
            out += [c, rnd.choice(alfabeto)]
        else:
            out.append(c)
    return "".join(out)


def evaluar(modelo, ev: List[dict], tasa: float) -> Dict[str, float]:
    refs = [x["texto"] for x in ev]
    hyps = [predecir(modelo, t, tasa, i) for i, t in enumerate(refs)]
    return {"cer": round(cer(refs, hyps), 4), "wer": round(wer(refs, hyps), 4)}


# ---------------- registro en MLflow ----------------

def registrar(tracking_uri: str, modelo: Dict[str, Any], metricas: Dict[str, float], params: Dict[str, Any],
              etiquetas: Dict[str, str], produccion: bool, nombre: str = NOMBRE) -> Dict[str, Any]:
    import mlflow
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("htr")
    cli = MlflowClient(tracking_uri=tracking_uri, registry_uri=tracking_uri)
    with mlflow.start_run(run_name=f"{nombre} · datos {etiquetas['datos.version'][:8]}") as run:
        mlflow.log_params(params)
        mlflow.log_metrics(metricas)
        mlflow.set_tags(etiquetas)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "modelo.json"
            p.write_text(json.dumps(modelo, ensure_ascii=False, indent=1), encoding="utf-8")
            mlflow.log_artifact(str(p), artifact_path="modelo")
        run_id, uri = run.info.run_id, run.info.artifact_uri
    try:
        cli.create_registered_model(nombre, description="HTR paleográfico del PaaS. Cada versión dice de qué datos sale.")
    except MlflowException:
        pass  # ya existía
    v = cli.create_model_version(nombre, source=f"{uri}/modelo", run_id=run_id,
                                 tags={**etiquetas, "cer": str(metricas["cer"]), "wer": str(metricas["wer"])})
    if produccion:
        cli.set_registered_model_alias(nombre, "produccion", v.version)
    return {"run": run_id, "version": int(v.version), "etiqueta": f"{nombre}@{v.version}", "produccion": produccion}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--datos", default=str(RAIZ / "datos" / "gt"))
    ap.add_argument("--tasa-error", type=float, default=0.06, help="solo para el modelo simulado")
    ap.add_argument("--produccion", action="store_true", help="poner esta versión en producción")
    ap.add_argument("--mlflow", default=None, help="por defecto MLFLOW_URL del .env")
    a = ap.parse_args(argv)
    if a.mlflow is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(RAIZ / ".env")
        except ImportError:
            pass
        a.mlflow = os.environ.get("MLFLOW_URL") or sys.exit("Falta MLFLOW_URL en plataforma/.env (p. ej. http://servidor:5000)")
    carpeta = Path(a.datos)
    lineas = leer_lineas(carpeta)
    train, ev = partir(lineas)
    datos, origen = version_datos(carpeta)
    if origen != "dvc":
        print(f"! {carpeta} no está bajo DVC: uso un md5 calculado ({datos[:10]}). Ejecuta «dvc add {carpeta}».")
    modelo = entrenar(train)
    metricas = evaluar(modelo, ev, a.tasa_error)
    etiquetas = {"datos.version": datos, "datos.origen": origen, "datos.ruta": os.path.relpath(carpeta, RAIZ),
                 "git.commit": commit_git(), "simulado": "true"}
    r = registrar(a.mlflow, modelo, metricas,
                  {"tasa_error": a.tasa_error, "lineas_entrenamiento": len(train), "lineas_evaluacion": len(ev)},
                  etiquetas, a.produccion)
    print(f"✓ {r['etiqueta']} · CER {metricas['cer']:.3f} · WER {metricas['wer']:.3f} · datos {datos[:10]} ({origen})"
          f" · run {r['run'][:8]}{' · EN PRODUCCIÓN' if r['produccion'] else ''}")
    return r


if __name__ == "__main__":
    main()
