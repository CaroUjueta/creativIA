# Versión liviana para Render gratis (512 MB): sin el clasificador local, que necesita ~780 MB.
# Al actualizar en línea se clasifica por palabras clave; el reporte de demo/ viene del clasificador local.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0
WORKDIR /app
COPY requirements.txt .
RUN grep -v fastembed requirements.txt > req.txt && pip install --no-cache-dir -r req.txt
COPY radar radar
COPY demo demo
CMD ["python", "-m", "radar.web", "--no-open", "--sin-clave"]
