FROM python:3.12-slim

# Legacy image — used for host-only API dev. Production deploy uses the root Dockerfile.

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir hatchling

COPY pyproject.toml .
COPY app ./app
COPY worker_main.py .

RUN pip install --no-cache-dir ".[cursor]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
