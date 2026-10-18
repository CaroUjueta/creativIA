"""Publica la app completa en Hugging Face Spaces: .venv/bin/python scripts/publicar_hf.py

Lee HF_TOKEN, RADAR_PASSWORD y OPENROUTER_API_KEY del .env, crea (o actualiza) el Space con Docker,
guarda las claves como secretos del Space y sube data/ y out/ a un dataset privado para que la app
arranque con el último reporte. Volver a correrlo publica los cambios del código.
"""

import os
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar import pipeline, storage  # noqa: E402

SPACE_README = """---
title: CreativIA
emoji: 📡
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: Radar de contenido sobre IA para el Reto 30X
---

CreativIA · Radar de contenido. Código: https://github.com/CaroUjueta/creativIA
"""


def main() -> None:
    os.chdir(Path(__file__).resolve().parent.parent)
    pipeline.load_dotenv()
    for key in ("HF_TOKEN", "RADAR_PASSWORD"):
        if not os.environ.get(key):
            sys.exit(f"Falta {key} en el .env")
    api = HfApi(token=os.environ["HF_TOKEN"])
    user = api.whoami()["name"]
    space = os.environ.get("RADAR_SPACE", f"{user}/creativia")
    dataset = os.environ.setdefault("RADAR_DATASET", f"{user}/creativia-datos")

    print(f"1/3 Creando el Space {space} y guardando las claves como secretos…")
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    for key in ("RADAR_PASSWORD", "HF_TOKEN", "OPENROUTER_API_KEY", "YOUTUBE_API_KEY", "RADAR_HASH_SALT"):
        if os.environ.get(key):
            api.add_space_secret(space, key, os.environ[key])
    api.add_space_variable(space, "RADAR_DATASET", dataset)

    print(f"2/3 Subiendo los reportes y datos al dataset privado {dataset}…")
    api.create_repo(dataset, repo_type="dataset", private=True, exist_ok=True)
    storage._push("Datos iniciales desde el computador del equipo")

    print("3/3 Subiendo el código…")
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        readme.write_text(SPACE_README, encoding="utf-8")
        api.upload_file(path_or_fileobj=str(readme), path_in_repo="README.md", repo_id=space, repo_type="space")
    api.upload_folder(repo_id=space, repo_type="space", folder_path=".", commit_message="Publicar CreativIA",
                      allow_patterns=["Dockerfile", "requirements.txt", "radar/*.py", "radar/assets/logo.png"])
    print(f"Listo: https://huggingface.co/spaces/{space}")
    print(f"App:   https://{space.replace('/', '-').lower()}.hf.space  (tarda unos minutos en construirse)")


if __name__ == "__main__":
    main()
