# Newer CUDA base image with Ubuntu 24.04
# (see https://hub.docker.com/r/nvidia/cuda/tags for current tags)
FROM nvidia/cuda:12.9.0-base-ubuntu24.04

WORKDIR /app

# Minimal system deps for Python; keep layers small
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# App dependencies (make sure fastapi + uvicorn are listed)
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Your FastAPI app: copy and rename to a valid Python module name
# so uvicorn can import "nvidia_endpoint:app"
COPY nvidia-endpoint-server.py /app/nvidia_endpoint.py

# The app listens on 5050 in the container
EXPOSE 5050

# Simple default: run uvicorn and bind to all interfaces
CMD ["python3", "-m", "uvicorn", "nvidia_endpoint:app", "--host", "0.0.0.0", "--port", "5050", "--workers", "1"]
