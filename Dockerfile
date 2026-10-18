# App completa de CreativIA para Hugging Face Spaces (o cualquier hosting con Docker).
FROM python:3.12-slim

# Hugging Face corre el contenedor con el usuario 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/home/user/models HOST=0.0.0.0 PORT=7860
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt huggingface_hub

# El modelo del clasificador local (~220 MB) queda dentro de la imagen: no se baja en cada arranque.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY --chown=user radar radar
EXPOSE 7860
CMD ["python", "-m", "radar.web", "--no-open"]
