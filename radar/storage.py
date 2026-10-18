"""Guarda data/ y out/ en un dataset privado de Hugging Face para que sobrevivan a los reinicios.

En Hugging Face Spaces el disco se borra cada vez que el Space se reinicia o se duerme. Si están
definidas RADAR_DATASET (p. ej. "usuario/creativia-datos") y HF_TOKEN, la app baja esos archivos al
arrancar y los sube después de cada actualización, aporte o cambio en la cuenta. En local no hace nada.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

log = logging.getLogger("radar")

PATTERNS = ["data/comunidad.csv", "data/cuenta.json", "data/cuenta_metricas.csv", "data/cache/*",
            "out/*.json", "out/*.jsonl", "out/*.md", "out/*.html"]
_lock = threading.Lock()


def enabled() -> bool:
    return bool(os.environ.get("RADAR_DATASET") and os.environ.get("HF_TOKEN"))


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=os.environ["HF_TOKEN"])


def pull() -> None:
    """Baja lo guardado (o crea el dataset privado si aún no existe)."""
    if not enabled():
        return
    from huggingface_hub import snapshot_download
    repo = os.environ["RADAR_DATASET"]
    try:
        _api().create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
        snapshot_download(repo, repo_type="dataset", local_dir=".", allow_patterns=PATTERNS, token=os.environ["HF_TOKEN"])
        log.info("Datos recuperados de %s", repo)
    except Exception as e:
        log.warning("No se pudieron recuperar los datos guardados (%s)", e)


def _push(message: str) -> None:
    with _lock:
        try:
            _api().upload_folder(repo_id=os.environ["RADAR_DATASET"], repo_type="dataset", folder_path=".",
                                 allow_patterns=PATTERNS, commit_message=message)
        except Exception as e:
            log.warning("No se pudieron guardar los datos (%s)", e)


def push(message: str) -> None:
    """Sube data/ y out/ en segundo plano; solo se suben los archivos que cambiaron."""
    if enabled():
        threading.Thread(target=_push, args=(message,), daemon=True).start()
