# syntax=docker/dockerfile:1.7
# Base image includes nvidia-smi (requires NVIDIA Container Toolkit on host)
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS base

ARG PYTHON_VERSION=3.10
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000 \
    UVICORN_WORKERS=1 \
    NVIDIA_LOCALE=C \
    NVIDIA_RUN_TIMEOUT_SEC=3 \
    NVIDIA_LOG_LEVEL=INFO \
    NVIDIA_API_KEY_FILE=/run/secrets/nvidia_api_key

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    python${PYTHON_VERSION} python3-pip python3-venv python3-distutils \
    ca-certificates curl tini && \
    ln -s /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python && \
    python -m pip install --upgrade pip && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 appuser
WORKDIR /app

# Optional: quick sanity check that nvidia-smi exists in the image
# RUN which nvidia-smi && nvidia-smi -h >/dev/null || true

FROM base AS build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM base
COPY --from=build /wheels /wheels
RUN pip install --no-cache /wheels/* && rm -rf /wheels
COPY app/ ./app/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]

USER appuser
