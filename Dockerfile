# Base image with NVIDIA container toolkit (if not on host)
FROM nvidia/cuda:12.0.1-base-ubuntu20.04

WORKDIR /app

# Install additional dependencies (optional)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev

COPY requirements.txt .

RUN pip install -r requirements.txt

# Copy your Flask application and Python script
COPY nvidia-endpoint-server.py .
COPY nvidia-endpoint-server.conf .

# Expose Flask application port (replace if needed)
EXPOSE 5000

ENV PATH="${PATH}:/usr/bin/nvidia-smi"

# Command to run Flask application
CMD ["python3", "nvidia-endpoint-server.py"]

