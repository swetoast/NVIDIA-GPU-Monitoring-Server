# NVIDIA GPU Endpoint API

A small FastAPI service that runs `nvidia-smi -q` on demand and exposes JSON over HTTP.

- `GET /health` – lightweight status (no auth)
- `GET /nvidia/` – sanitized raw subtree for the first GPU from `nvidia-smi -q` (optionally API‑key protected)

This project is intended for simple monitoring and Home Assistant integrations.

---

## Endpoints

### `GET /health`
Basic status and configuration preview.

**Example**
```bash
curl -s http://127.0.0.1:8030/health | jq
````

**Sample response**

```json
{
  "status": "ok",
  "nvidia_smi_path": "/usr/bin/nvidia-smi",
  "timeout_sec": 3.0,
  "endpoints": ["/health", "/docs/", "/nvidia/"]
}
```

### `GET /nvidia/`

Runs `nvidia-smi -q` immediately and returns a sanitized JSON structure of the first GPU’s section.

**Auth header (if enabled)**

    X-API-Key: <your_api_key>

**Example**

```bash
curl -s -H "X-API-Key: <key>" http://127.0.0.1:8030/nvidia/ | jq
```

Notes:

*   Values such as `"N/A"` are preserved as strings.
*   Key names reflect `nvidia-smi -q` output (e.g., `Power Readings.Power Draw`, `Temperature.GPU Current Temp`, `FB Memory Usage.Used`, `Fan Speed`, `Utilization.Gpu`). Driver/toolkit versions can slightly vary field names.

***

## Requirements

*   Linux host with an NVIDIA GPU and a compatible NVIDIA driver
*   `nvidia-smi` available
*   Docker with NVIDIA Container Toolkit (for containerized deployment), or Python 3.10+ for local runs

***

## Configuration (environment variables)

All are optional.

| Variable                 | Purpose                                                 | Default |
| ------------------------ | ------------------------------------------------------- | ------- |
| `NVIDIA_API_KEY`         | If set, `/nvidia/` requires `X-API-Key` header          | unset   |
| `NVIDIA_CORS`            | Comma‑separated origins for CORS (e.g., `*` or domains) | unset   |
| `NVIDIA_LOCALE`          | Linux only, sets `LC_ALL` for `nvidia-smi` labels       | `C`     |
| `NVIDIA_RUN_TIMEOUT_SEC` | Subprocess timeout for `nvidia-smi`                     | `3`     |
| `NVIDIA_SMI_PATH`        | Full path to `nvidia-smi` if not on `PATH`              | auto    |
| `NVIDIA_LOG_LEVEL`       | `DEBUG`, `INFO`, `WARNING`, `ERROR`                     | `INFO`  |

***

## Docker

### Dockerfile

Uses a newer CUDA base and runs uvicorn. Adjust as needed.

```dockerfile
FROM nvidia/cuda:12.9.0-base-ubuntu24.04

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Map the source into a valid Python module name for uvicorn import
COPY nvidia-endpoint-server.py /app/nvidia_endpoint.py

EXPOSE 5050

CMD ["python3", "-m", "uvicorn", "nvidia_endpoint:app", "--host", "0.0.0.0", "--port", "5050", "--workers", "1"]
```

`requirements.txt` minimum:

    fastapi
    uvicorn[standard]

### docker-compose.yml

Binds container port 5050 to host 5051 and exposes GPU 0. Adjust as needed.

```yaml
version: "3.8"

services:
  nvidia-endpoint:
    build: .
    working_dir: /app
    command: >
      python3 -m uvicorn nvidia_endpoint:app
      --host 0.0.0.0 --port 5050 --workers 1
    ports:
      - "5051:5050"
    volumes:
      - ./nvidia-endpoint-server.py:/app/nvidia_endpoint.py:ro
    environment:
      # NVIDIA_API_KEY: "change-me"   # uncomment to require X-API-Key for /nvidia/
    restart: unless-stopped
    gpus:
      - "device=0"
```

### Run

```bash
docker compose up --build -d
curl -s http://127.0.0.1:5051/health | jq
```

***

## systemd (example)

Minimal unit exposing the app on all interfaces. Replace paths and module name if your layout differs.

```ini
# /etc/systemd/system/nvidia-endpoint.service
[Unit]
Description=NVIDIA endpoint server (Uvicorn, public bind)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/nvidia-endpoint

Environment=PYTHONUNBUFFERED=1
# Optional runtime config:
# Environment=NVIDIA_API_KEY=changeme
# Environment=NVIDIA_CORS=*
# Environment=NVIDIA_LOCALE=C
# Environment=NVIDIA_RUN_TIMEOUT_SEC=3
# Environment=NVIDIA_LOG_LEVEL=INFO
# Environment=NVIDIA_SMI_PATH=/usr/bin/nvidia-smi

ExecStart=/usr/bin/python3 -m uvicorn nvidia_endpoint:app --host 0.0.0.0 --port 8030 --workers 1

Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nvidia-endpoint.service
```

***

## Home Assistant

### Example provided (as-is)

The following is included as-is, per request:

```yaml
- platform: rest
    name: "NVIDIA GPU (TITAN X)"
    unique_id: nvidia_gpu_titanx
    resource: http://127.0.0.1:8030/nvidia/
    icon: "phu:nvidia-geforce"
    scan_interval: 30
    timeout: 10
    verify_ssl: false
    value_template: >
      {% set t = value_json.get('Temperature', {}).get('GPU Current Temp') %}
      {{ (t.split(' ')[0] | float(0)) if t else 0 }}
    unit_of_measurement: "°C"
    device_class: temperature
    json_attributes:
      - Product Name
      - Product Architecture
      - Performance State
      - Fan Speed
      - Compute Mode
      - Utilization
      - Temperature
      - FB Memory Usage
      - BAR1 Memory Usage
      - GPU Power Readings
      - Clocks
      - Max Clocks
      - Applications Clocks
      - PCI
      - Processeshere is an rest api sensor dont forget the watt sensor for energy in homeassssistant also
```

### Watt sensor for energy, plus energy (kWh) integration

Add a power sensor (W) and integrate it to energy. These use `/nvidia/` fields `Power Readings.Power Draw` (or `GPU Power Readings.Power Draw` on some versions).

```yaml
# REST block that exposes multiple sensors from one call (recommended)
rest:
  - resource: http://127.0.0.1:8030/nvidia/
    method: GET
    # headers:
    #   X-API-Key: YOUR_KEY
    scan_interval: 30
    timeout: 10
    verify_ssl: false
    sensor:
      - name: "GPU Power Usage"
        unique_id: gpu_power_usage_w
        device_class: power
        unit_of_measurement: "W"
        state_class: measurement
        value_template: >
          {% set pr = value_json.get('Power Readings') or value_json.get('GPU Power Readings') %}
          {% set draw = pr.get('Power Draw') if pr else None %}
          {{ (draw | regex_findall_index('([0-9.]+)')) | float(0) }}

# Integrate Watts to kWh for Energy
sensor:
  - platform: integration
    source: sensor.gpu_power_usage
    name: "GPU Energy (kWh)"
    unit_prefix: k
    unit_time: h
    method: trapezoidal
    round: 3

utility_meter:
  gpu_energy_daily:
    source: sensor.gpu_energy_kwh
    cycle: daily
  gpu_energy_weekly:
    source: sensor.gpu_energy_kwh
    cycle: weekly
  gpu_energy_monthly:
    source: sensor.gpu_energy_kwh
    cycle: monthly
```

If you prefer to derive power from attributes of your existing single REST sensor, use this instead:

```yaml
sensor:
  - platform: template
    sensors:
      gpu_power_usage:
        friendly_name: "GPU Power Usage"
        unique_id: gpu_power_usage_w
        unit_of_measurement: "W"
        device_class: power
        state_class: measurement
        value_template: >
          {% set pr = state_attr('sensor.nvidia_gpu_titan_x', 'Power Readings')
                       or state_attr('sensor.nvidia_gpu_titan_x', 'GPU Power Readings') %}
          {% set draw = pr.get('Power Draw') if pr else None %}
          {{ (draw | regex_findall_index('([0-9.]+)')) | float(0) }}
```

***

## Testing

```bash
# Health
curl -s http://127.0.0.1:8030/health | jq

# NVIDIA (with key if configured)
curl -s -H "X-API-Key: <key>" http://127.0.0.1:8030/nvidia/ | jq
```

***

## Troubleshooting

*   `nvidia-smi not found`: install the NVIDIA driver or set `NVIDIA_SMI_PATH`.
*   `unsatisfied condition: cuda>=...` inside Docker: host driver is too old for the CUDA tag you chose. Update the driver or use an older `nvidia/cuda` base.
*   `/nvidia/` 502/504: increase `NVIDIA_RUN_TIMEOUT_SEC` and verify GPU availability on the host.

***

## Notes

*   The service currently exposes GPU data only. CPU endpoints are not included.
*   If you run multiple GPUs and need per‑GPU selection, extend the parser to return specific devices or expose additional endpoints.

