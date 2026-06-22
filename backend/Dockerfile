# Sense Platform API — portable container (no AWS).
# Serves the ingest API, the read endpoints, the optional /ask RAG endpoint,
# and the static dashboard, all on one port.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRONTEND_DIR=/srv/frontend

WORKDIR /srv

# Dependencies first for layer caching.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code and the static dashboard.
COPY backend/app ./app
COPY frontend ./frontend

EXPOSE 8000

# Simple container healthcheck against the API.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
