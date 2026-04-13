#!/usr/bin/env python3
"""
Endpoints:
  GET /health    - lightweight status & config
  GET /docs/     - Swagger UI (FastAPI auto)
  GET /nvidia/   - run `nvidia-smi -q` now, parse, and return sanitized raw subtree for the first GPU
"""

import logging
import math
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Tuple, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ------------------------- Config & logging -------------------------

API_KEY = os.getenv("NVIDIA_API_KEY")
ALLOWED_ORIGINS = os.getenv("NVIDIA_CORS", "")
NVIDIA_SMI_PATH_ENV = os.getenv("NVIDIA_SMI_PATH")  # e.g., Windows: C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe
LOG_LEVEL = os.getenv("NVIDIA_LOG_LEVEL", "INFO").upper()
LOCALE = os.getenv("NVIDIA_LOCALE", "C")            # Linux only (nvidia-smi labels)
RUN_TIMEOUT_SEC = float(os.getenv("NVIDIA_RUN_TIMEOUT_SEC", "3"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("nvidia_endpoint")

# ------------------------- FastAPI app -------------------------

app = FastAPI(title="NVIDIA GPU Endpoint API", version="4.7.1", openapi_url="/openapi.json")

origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()] if ALLOWED_ORIGINS.strip() else ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])

# ------------------------- Auth -------------------------

def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# ------------------------- Common helpers -------------------------

def run_command(cmd: List[str], timeout: float = RUN_TIMEOUT_SEC) -> str:
    """Run a command and return decoded stdout; return empty string on error."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout).decode(errors="ignore")
    except Exception:
        return ""

def sanitize_json(obj: Any, *, max_depth: int = 40) -> Any:
    """Ensure the structure is JSON-serializable and safe."""
    def _s(x: Any, d: int) -> Any:
        if d > max_depth:
            return None
        if x is None or isinstance(x, (str, bool, int)):
            return x
        if isinstance(x, float):
            return None if (math.isnan(x) or math.isinf(x)) else x
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="replace")
        if isinstance(x, dict):
            out: Dict[str, Any] = {}
            for k, v in x.items():
                out[str(k)] = _s(v, d + 1)
            return out
        if isinstance(x, (list, tuple)):
            return [_s(v, d + 1) for v in x]
        return str(x)
    return _s(obj, 0)

# ------------------------- NVIDIA helpers -------------------------

def find_nvidia_smi() -> Optional[str]:
    """Find nvidia-smi path from env or PATH (Linux/Windows)."""
    if NVIDIA_SMI_PATH_ENV and os.path.isfile(NVIDIA_SMI_PATH_ENV):
        return NVIDIA_SMI_PATH_ENV
    return shutil.which("nvidia-smi")

GPU_ADDR_RE = re.compile(r'^GPU\s+[0-9A-Fa-f]{8}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.\d+$')
KV_RE       = re.compile(r'^\s*([^:]+?)\s*:\s*(.*)$')

def parse_nvsmilog(text: str) -> Dict[str, Any]:
    """Build nested dict from `nvidia-smi -q` with all values kept as printed (including 'N/A', units, etc.)."""
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = []
    current = root

    def push(indent: int, name: str) -> Dict[str, Any]:
        nonlocal current
        dest = current
        if name in dest:
            if isinstance(dest[name], list):
                new = {}
                dest[name].append(new)
                stack.append((indent, new))
                current = new
                return new
            else:
                first = dest[name]
                dest[name] = [first, {}]
                stack.append((indent, dest[name][-1]))
                current = dest[name][-1]
                return current
        else:
            dest[name] = {}
            stack.append((indent, dest[name]))
            current = dest[name]
            return current

    for raw in lines:
        if not raw or raw.strip().startswith('===='):
            continue

        indent = len(raw) - len(raw.lstrip(' '))
        s = raw.strip()

        # unwind to this indent
        while stack and stack[-1][0] >= indent:
            stack.pop()
            current = stack[-1][1] if stack else root

        # Strict device header
        if GPU_ADDR_RE.match(s):
            current = root
            push(indent, s)
            continue

        # key : value → keep EXACT value
        m = KV_RE.match(raw)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            current[key] = val
            continue

        # section header (no colon)
        if ':' not in s:
            push(indent, s)
            continue

    return root

def is_probable_gpu_section(name: str, subtree: Dict[str, Any]) -> bool:
    """Prefer strict header; fallback only when PCI/Bus Id exists and GPU-ish sections present."""
    if GPU_ADDR_RE.match(name):
        return True
    if not isinstance(subtree, dict):
        return False
    pci = subtree.get("PCI")
    if isinstance(pci, dict) and isinstance(pci.get("Bus Id"), str):
        return any(k in subtree for k in ("FB Memory Usage", "Temperature", "Utilization"))
    return False

def split_gpu_subtrees(root: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    return [(k, v) for k, v in root.items() if isinstance(k, str) and is_probable_gpu_section(k, v) and isinstance(v, dict)]

def run_nvidia_smi_q() -> str:
    smi = find_nvidia_smi()
    if not smi:
        raise RuntimeError("nvidia-smi not found; install NVIDIA drivers or set NVIDIA_SMI_PATH.")
    env = os.environ.copy()
    if os.name == "posix":
        env["LC_ALL"] = LOCALE or "C"  # force English labels on Linux
    proc = subprocess.run([smi, "-q"], capture_output=True, text=True, env=env, timeout=RUN_TIMEOUT_SEC, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "nvidia-smi failed")
    return proc.stdout

# ------------------------- Endpoints -------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    smi = find_nvidia_smi()
    return {
        "status": "ok" if smi else "degraded",
        "nvidia_smi_path": smi,
        "timeout_sec": RUN_TIMEOUT_SEC,
        "endpoints": ["/health", "/docs/", "/nvidia/"],
    }

@app.get("/nvidia/", dependencies=[Depends(require_api_key)], summary="On-demand parse of `nvidia-smi -q` (sanitized raw subtree)")
def nvidia_latest() -> Dict[str, Any]:
    """
    Run `nvidia-smi -q` NOW, parse output, return the FULL RAW SUBTREE for the first GPU (single-GPU-first),
    sanitized to guarantee valid JSON serialization. Values like 'N/A' are preserved as strings.
    """
    try:
        text = run_nvidia_smi_q()
        root = parse_nvsmilog(text)
        gpus = split_gpu_subtrees(root)
        if not gpus:
            raise HTTPException(status_code=502, detail="No GPU devices found in nvidia-smi output")
        _, first_tree = gpus[0]
        return sanitize_json(first_tree)
    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="nvidia-smi timed out")
    except Exception as e:
        logger.exception("nvidia endpoint failed: %s", e)
        raise HTTPException(status_code=502, detail=f"nvidia query failed: {e}")
