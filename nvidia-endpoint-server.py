#!/usr/bin/env python3
"""
Endpoints:
  GET /health    - lightweight status & config
  GET /docs/     - Swagger UI (FastAPI auto)
  GET /nvidia/   - run `nvidia-smi -q` now, parse, and return sanitized raw subtree for the first GPU
  GET /cpu       - collect CPU telemetry now (cross-platform), normalized and sanitized JSON
"""

import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import platform
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor

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

app = FastAPI(title="NVIDIA GPU + CPU Endpoint API", version="4.7.1", openapi_url="/openapi.json")

origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()] if ALLOWED_ORIGINS.strip() else ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])

# ------------------------- Auth -------------------------

def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# ------------------------- Common helpers -------------------------

def get_timestamp_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def run_command(cmd: List[str], timeout: float = RUN_TIMEOUT_SEC) -> str:
    """Run a command and return decoded stdout; return empty string on error."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout).decode(errors="ignore")
    except Exception:
        return ""

def to_int(val) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None

def to_float(val) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None

def hz_to_mhz(v: Optional[int]) -> Optional[int]:
    return int(v / 1_000_000) if isinstance(v, int) and v > 0 else None

def kb_to_mb(v: Optional[int]) -> Optional[int]:
    return int(v / 1024) if isinstance(v, int) and v >= 0 else None

def round1(v: Optional[float]) -> Optional[float]:
    return round(float(v), 1) if v is not None else None

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

# ------------------------- Temperature canonicalization -------------------------

def normalize_temperature_keys(os_name: str, temps: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    Canonicalize temperature keys across platforms.
    Linux: map coretemp/k10temp/zenpower/etc. to cpu.package.N / cpu.core.N / cpu.tctl / cpu.ccd.N
    Windows: map ACPI zones TZxx_* to platform.acpi.zone.N
    """
    if not temps or not isinstance(temps, dict):
        return temps

    out: Dict[str, float] = {}
    for raw_key, val in temps.items():
        # guard: only keep numeric temp values (float/int)
        try:
            num = float(val)
        except Exception:
            continue

        key = str(raw_key).strip()

        if os_name == "linux":
            if ":" in key:
                driver, label = key.split(":", 1)
                driver = driver.strip().lower()
                label = label.strip()

                # Intel coretemp
                m_core = re.match(r"^Core\s+(\d+)$", label, re.I)
                m_pkg  = re.match(r"^Package\s+id\s+(\d+)$", label, re.I)
                if driver == "coretemp":
                    if m_core:
                        out[f"cpu.core.{m_core.group(1)}"] = num
                        continue
                    if m_pkg:
                        out[f"cpu.package.{m_pkg.group(1)}"] = num
                        continue

                # AMD k10temp / zenpower
                if driver in ("k10temp", "zenpower"):
                    if re.fullmatch(r"Tctl", label, re.I):
                        out["cpu.tctl"] = num
                        continue
                    if re.fullmatch(r"Tdie", label, re.I):
                        out["cpu.package.0"] = num
                        continue
                    m_ccd = re.match(r"(?:Tccd|CCD)\s*(\d+)", label, re.I)
                    if m_ccd:
                        out[f"cpu.ccd.{m_ccd.group(1)}"] = num
                        continue

                # ARM/SOC heuristics
                if re.search(r"\bcpu\b", label, re.I):
                    out["cpu.package.0"] = num
                    continue
                if re.search(r"\bsoc\b", label, re.I):
                    out["cpu.soc"] = num
                    continue
                if re.search(r"big", label, re.I):
                    out["cpu.cluster.big"] = num
                    continue
                if re.search(r"little", label, re.I):
                    out["cpu.cluster.little"] = num
                    continue

                # Fallback: stable namespaced key
                token = re.sub(r"[^a-z0-9]+", ".", label.lower()).strip(".")
                out[f"cpu.sensor.{driver}.{token}"] = num
                continue

            # No "driver:label" form; sanitize entire key
            token = re.sub(r"[^a-z0-9]+", ".", key.lower()).strip(".")
            out[f"cpu.sensor.{token}"] = num
            continue

        if os_name == "windows":
            m_tz = re.match(r"^TZ(\d+)_\d+$", key, re.I)
            if m_tz:
                idx = int(m_tz.group(1))  # remove leading zeros: "00" -> 0
                out[f"platform.acpi.zone.{idx}"] = num
                continue
            token = re.sub(r"[^a-z0-9]+", ".", key.lower()).strip(".")
            out[f"platform.acpi.{token}"] = num
            continue

        # macOS or unknown: just sanitize
        token = re.sub(r"[^a-z0-9]+", ".", key.lower()).strip(".")
        out[token] = num

    return out or None

# --------------------------- Linux collectors -------------------------

def read_proc_stat_snapshot() -> dict:
    snapshot = {}
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("cpu"):
                    parts = line.split()
                    snapshot[parts[0]] = [int(x) for x in parts[1:]]
    except Exception:
        pass
    return snapshot

def compute_utilization_from_snapshots(s1: dict, s2: dict) -> dict:
    def compute(a, b):
        if not a or not b:
            return None
        idle1 = a[3] + (a[4] if len(a) > 4 else 0)
        idle2 = b[3] + (b[4] if len(b) > 4 else 0)
        total1, total2 = sum(a), sum(b)
        totald, idled = total2 - total1, idle2 - idle1
        if totald <= 0:
            return None
        return round((totald - idled) * 100.0 / totald, 2)
    out = {}
    for k in s1:
        if k in s2:
            out[k] = compute(s1[k], s2[k])
    return out

def read_linux_per_cpu_freq_hz() -> Optional[List[Optional[int]]]:
    result: List[Optional[int]] = []
    try:
        cpu_dirs = sorted(
            [d for d in os.listdir("/sys/devices/system/cpu") if re.match(r'cpu\d+$', d)],
            key=lambda x: int(x[3:])
        )
        for d in cpu_dirs:
            path = f"/sys/devices/system/cpu/{d}/cpufreq/scaling_cur_freq"
            hz = None
            if os.path.isfile(path):
                try:
                    with open(path) as f:
                        khz = int(f.read().strip())
                    hz = khz * 1000
                except Exception:
                    hz = None
            result.append(hz)
    except Exception:
        pass
    return result if result else None

def read_linux_cache_info() -> Optional[Dict[str, Any]]:
    info: Dict[str, Any] = {}
    try:
        base = "/sys/devices/system/cpu/cpu0/cache"
        if os.path.isdir(base):
            for idx in os.listdir(base):
                p = f"{base}/{idx}"
                try:
                    with open(f"{p}/level") as f1, open(f"{p}/size") as f2, open(f"{p}/type") as f3:
                        level = f1.read().strip()
                        size  = f2.read().strip()
                        typ   = f3.read().strip()
                    info[f"L{level}_{typ.lower()}"] = size
                except Exception:
                    pass
    except Exception:
        pass
    return info or None

def read_linux_cpu_info() -> Dict[str, Any]:
    model = vendor = stepping = family = microcode = None
    flags = None
    serial = None
    try:
        with open("/proc/cpuinfo") as f:
            text = f.read()
        block = text.split("\n\n")[0]
        for line in block.splitlines():
            low = line.lower()
            if low.startswith("model name"):
                model = line.split(":",1)[1].strip()
            elif low.startswith("vendor_id"):
                vendor = line.split(":",1)[1].strip()
            elif low.startswith("flags"):
                flags = line.split(":",1)[1].strip().split()
            elif low.startswith("stepping"):
                stepping = line.split(":",1)[1].strip()
            elif low.startswith("cpu family"):
                family = line.split(":",1)[1].strip()
            elif low.startswith("microcode"):
                microcode = line.split(":",1)[1].strip()
            elif low.startswith("serial"):
                serial = line.split(":",1)[1].strip()
    except Exception:
        pass
    return {
        "model_name": model,
        "vendor_id": vendor,
        "flags": flags,
        "stepping": stepping,
        "family": family,
        "microcode": microcode,
        "cpu_serial": serial
    }

def read_linux_cpu_temperatures_c() -> Optional[Dict[str, float]]:
    ALLOW_CPU_HWMON = {
        # x86
        "coretemp", "k10temp", "zenpower",
        # Raspberry Pi / Broadcom
        "bcm2711_thermal", "bcm2835_thermal", "bcm2711-thermal", "bcm2835-thermal",
        # Rockchip
        "rockchip_thermal", "rk3399_thermal", "rk3568_thermal", "rk3588_thermal",
        # Allwinner
        "sun8i_thermal", "sun50i_thermal", "sunxi-thermal",
        # NXP i.MX
        "imx_thermal", "imx8mm_thermal", "imx8mq_thermal",
        # Qualcomm
        "tsens", "qcom-tsens", "qcom_spmi_temp_alarm",
        # Amlogic
        "meson_thermal", "amlogic_thermal",
        # NVIDIA Tegra
        "tegra-thermal", "tegra194-thermal", "tegra186-thermal",
        # MediaTek
        "mtk_thermal", "mtktscpu",
        # Samsung Exynos
        "exynos-thermal", "exynos_thermal",
        # HiSilicon
        "hisilicon_thermal", "hi3660_thermal",
        # Generic ARM/SOC names
        "cpu_thermal", "cpu-thermal", "soc_thermal", "soc-thermal",
        "scpi_sensors", "thermal-fan-est",
    }

    sensors: Dict[str, float] = {}
    try:
        for hw in os.listdir("/sys/class/hwmon"):
            base = os.path.join("/sys/class/hwmon", hw)
            try:
                name_path = os.path.join(base, "name")
                if os.path.isfile(name_path):
                    with open(name_path) as nf:
                        name = nf.read().strip()
                else:
                    name = hw
            except Exception:
                name = hw

            if name not in ALLOW_CPU_HWMON:
                continue

            for fname in os.listdir(base):
                if re.match(r"temp\d+_input", fname):
                    idx = re.findall(r"\d+", fname)[0]
                    label_path = os.path.join(base, f"temp{idx}_label")
                    label = None
                    if os.path.isfile(label_path):
                        try:
                            with open(label_path) as lf:
                                label = lf.read().strip()
                        except Exception:
                            label = None
                    try:
                        with open(os.path.join(base, fname)) as tf:
                            millic = int(tf.read().strip())
                        c = millic / 1000.0
                        key = f"{name}:{label}" if label else f"{name}:temp{idx}"
                        sensors[key] = round(c, 1)
                    except Exception:
                        pass
    except Exception:
        pass

    return sensors or None

def read_linux_uptime_seconds() -> Optional[int]:
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return None

# --------------------------- Windows collectors -------------------------

def parse_wmi_datetime(dt_str: str) -> Optional[datetime]:
    m = re.match(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\.(\d+)([+\-]\d{3})?", dt_str or "")
    if not m:
        return None
    y, mo, d, h, mi, se = map(int, m.groups()[:6])
    try:
        return datetime(y, mo, d, h, mi, se, tzinfo=timezone.utc)
    except Exception:
        return None

def query_windows_cpu_properties() -> Dict[str, Any]:
    props = [
        "Name","NumberOfCores","NumberOfLogicalProcessors","MaxClockSpeed",
        "CurrentClockSpeed","LoadPercentage","Manufacturer","Caption","DeviceID",
        "Architecture","L2CacheSize","L3CacheSize","ProcessorId","SocketDesignation"
    ]
    out = run_command(["wmic","cpu","get",",".join(props),"/format:list"])
    data: Dict[str, Any] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    if data:
        return data
    ps = (
        "$p=Get-CimInstance Win32_Processor | "
        "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,CurrentClockSpeed,LoadPercentage,"
        "Manufacturer,Caption,DeviceID,Architecture,L2CacheSize,L3CacheSize,ProcessorId,SocketDesignation;"
        "$p | ConvertTo-Json -Depth 2"
    )
    jout = run_command(["powershell","-NoProfile","-Command", ps], timeout=RUN_TIMEOUT_SEC)
    try:
        obj = json.loads(jout)
        if isinstance(obj, list):
            obj = obj[0] if obj else {}
        return {k: (str(obj.get(k)) if obj and k in obj else None) for k in props}
    except Exception:
        return {}

def query_windows_serials() -> Dict[str, Any]:
    bios = run_command(["wmic","bios","get","SerialNumber","/format:list"])
    bb   = run_command(["wmic","baseboard","get","SerialNumber","/format:list"])
    def pick(s):
        for line in s.splitlines():
            if "=" in line:
                return line.split("=",1)[1].strip()
        return None
    bios_sn, bb_sn = pick(bios), pick(bb)
    if not (bios_sn or bb_sn):
        ps = (
            "$b=Get-CimInstance Win32_BIOS | Select-Object -ExpandProperty SerialNumber;"
            "$m=Get-CimInstance Win32_BaseBoard | Select-Object -ExpandProperty SerialNumber;"
            "[PSCustomObject]@{BIOS=$b;Baseboard=$m} | ConvertTo-Json"
        )
        jout = run_command(["powershell","-NoProfile","-Command", ps], timeout=RUN_TIMEOUT_SEC)
        try:
            o = json.loads(jout)
            bios_sn, bb_sn = o.get("BIOS"), o.get("Baseboard")
        except Exception:
            pass
    return {"system_serial": bios_sn, "baseboard_serial": bb_sn}

def collect_windows_percpu_utilization() -> Optional[List[float]]:
    """
    Collect per-CPU utilization via Get-Counter; fallback to typeperf.
    Returns a list of percent values (sorted by core index) or None.
    """
    ps = (
        "$c=Get-Counter '\\Processor(*)\\% Processor Time' -SampleInterval 1 -MaxSamples 1;"
        "$c.CounterSamples | Select-Object InstanceName,CookedValue | ConvertTo-Json -Depth 3"
    )
    out = run_command(["powershell", "-NoProfile", "-Command", ps], timeout=RUN_TIMEOUT_SEC)
    try:
        j = json.loads(out)
        if isinstance(j, dict):
            j = [j]
        entries: List[Tuple[int, float]] = []
        for item in j or []:
            name = str(item.get("InstanceName", ""))
            val  = item.get("CookedValue")
            if re.fullmatch(r"\d+", name) and val is not None:  # numeric cores only
                entries.append((int(name), round(float(val), 2)))
        if entries:
            entries.sort(key=lambda kv: kv[0])                  # order by core index
            return [v for _, v in entries]
    except Exception:
        pass

    # typeperf fallback
    csv = run_command(["typeperf", r"\Processor(*)\% Processor Time", "-sc", "1"], timeout=RUN_TIMEOUT_SEC)
    lines = [ln for ln in csv.splitlines() if ln and not ln.startswith('"(')]
    if len(lines) >= 2:
        headers = [h.strip().strip('"') for h in lines[0].split(",")]
        values  = [v.strip().strip('"') for v in lines[1].split(",")]
        entries = []
        for h, v in zip(headers[1:], values[1:]):
            m = re.search(r"\\Processor\((.+)\)\\% Processor Time", h)
            if m:
                name = m.group(1)
                if re.fullmatch(r"\d+", name):
                    entries.append((int(name), round(to_float(v) or 0.0, 2)))
        if entries:
            entries.sort(key=lambda kv: kv[0])
            return [v for _, v in entries]

    return None

def collect_windows_percpu_frequency_hz(max_clock_mhz: Optional[int]) -> Tuple[Optional[List[Optional[int]]], Optional[int]]:
    def filter_numeric_instances(items):
        return [it for it in items if re.fullmatch(r"\d+", str(it.get("InstanceName","")))]

    # Direct Processor Frequency (MHz) → Hz
    ps_freq = (
        "$c=Get-Counter '\\Processor Information(*)\\Processor Frequency' -SampleInterval 1 -MaxSamples 1;"
        "$c.CounterSamples | Select-Object InstanceName,CookedValue | ConvertTo-Json -Depth 3"
    )
    out = run_command(["powershell","-NoProfile","-Command", ps_freq], timeout=RUN_TIMEOUT_SEC)
    try:
        j = json.loads(out)
        if isinstance(j, dict):
            j = [j]
        core_items = filter_numeric_instances(j)
        per_hz: List[Optional[int]] = []
        for item in core_items:
            mhz = to_int(item.get("CookedValue"))
            per_hz.append(mhz * 1_000_000 if mhz is not None else None)
        total_item = next((i for i in j if i.get("InstanceName") == "_Total"), None)
        total_hz = (to_int(total_item.get("CookedValue")) * 1_000_000) if total_item and total_item.get("CookedValue") else None
        if per_hz:
            return per_hz, total_hz
    except Exception:
        pass

    # Fallback: % Processor Performance × MaxClockSpeed
    ps_perf = (
        "$c=Get-Counter '\\Processor Information(*)\\% Processor Performance' -SampleInterval 1 -MaxSamples 1;"
        "$c.CounterSamples | Select-Object InstanceName,CookedValue | ConvertTo-Json -Depth 3"
    )
    out2 = run_command(["powershell","-NoProfile","-Command", ps_perf], timeout=RUN_TIMEOUT_SEC)
    try:
        j2 = json.loads(out2)
        if isinstance(j2, dict):
            j2 = [j2]
        core_items = filter_numeric_instances(j2)
        perf_vals = [to_float(it.get("CookedValue")) for it in core_items]
        total_item = next((i for i in j2 if i.get("InstanceName") == "_Total"), None)
        total_perf = to_float(total_item.get("CookedValue")) if total_item else None
        if perf_vals and max_clock_mhz:
            max_hz = max_clock_mhz * 1_000_000.0
            per_hz = [to_int(round((p or 0)/100.0 * max_hz)) for p in perf_vals]
            total_hz = to_int(round((total_perf or 0)/100.0 * max_hz)) if total_perf is not None else None
            return per_hz, total_hz
    except Exception:
        pass

    return None, None

def read_windows_processor_queue_length() -> Optional[int]:
    ps = (
        "$q=Get-Counter '\\System\\Processor Queue Length' -SampleInterval 1 -MaxSamples 1;"
        "$q.CounterSamples[0].CookedValue"
    )
    out = run_command(["powershell","-NoProfile","-Command", ps], timeout=RUN_TIMEOUT_SEC).strip()
    return to_int(float(out)) if out else None

def read_windows_uptime_seconds() -> Optional[int]:
    out = run_command(["wmic","os","get","LastBootUpTime","/value"])
    ts = None
    for line in out.splitlines():
        if line.startswith("LastBootUpTime"):
            ts = line.split("=",1)[1].strip()
            break
    dt = parse_wmi_datetime(ts)
    if not dt:
        return None
    return int((datetime.now(timezone.utc) - dt).total_seconds())

def read_windows_acpi_temperatures_c() -> Optional[Dict[str, float]]:
    temps: Dict[str, float] = {}

    # WMIC CSV
    out = run_command([
        "wmic",
        "/namespace:\\\\root\\wmi",
        "PATH", "MSAcpi_ThermalZoneTemperature",
        "get", "CurrentTemperature,InstanceName",
        "/format:csv"
    ], timeout=RUN_TIMEOUT_SEC)

    try:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if lines and "CurrentTemperature" in (lines[0] if lines else ""):
            for row in lines[1:]:
                cols = [c.strip() for c in row.split(",")]
                if len(cols) >= 3:
                    raw = to_int(cols[1]); name = cols[2]
                    if raw and raw > 0:
                        c = (raw / 10.0) - 273.15
                        short = name.split("\\")[-1] if "\\" in name else name
                        temps[short] = round(c, 1)
    except Exception:
        pass

    if temps:
        return temps

    # PowerShell CIM fallback
    ps = (
        "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | "
        "Select-Object InstanceName,CurrentTemperature | ConvertTo-Json -Depth 2"
    )
    jout = run_command(["powershell","-NoProfile","-Command", ps], timeout=RUN_TIMEOUT_SEC)
    try:
        j = json.loads(jout)
        if isinstance(j, dict):
            j = [j]
        for item in j or []:
            name = item.get("InstanceName", "ACPI")
            raw  = to_int(item.get("CurrentTemperature"))
            if raw and raw > 0:
                temps[name] = round((raw/10.0) - 273.15, 1)
    except Exception:
        pass

    if temps:
        return temps

    # Legacy WMI fallback
    ps2 = (
        "Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi | "
        "Select-Object InstanceName,CurrentTemperature | ConvertTo-Json -Depth 2"
    )
    jout2 = run_command(["powershell","-NoProfile","-Command", ps2], timeout=RUN_TIMEOUT_SEC)
    try:
        j2 = json.loads(jout2)
        if isinstance(j2, dict):
            j2 = [j2]
        for item in j2 or []:
            name = item.get("InstanceName", "ACPI")
            raw  = to_int(item.get("CurrentTemperature"))
            if raw and raw > 0:
                temps[name] = round((raw/10.0) - 273.15, 1)
    except Exception:
        pass

    return temps or None

# --------------------------- macOS collectors -------------------------

def read_macos_sysctl(keys: List[str]) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for k in keys:
        val = run_command(["sysctl","-n",k]).strip()
        out[k] = val if val else None
    return out

def read_macos_cpu_utilization() -> Optional[Dict[str, float]]:
    out = run_command(["top","-l","1","-n","0"])
    m = re.search(r"CPU usage:\s*([\d\.]+)% user,\s*([\d\.]+)% sys,\s*([\d\.]+)% idle", out)
    if m:
        u = float(m.group(1)); s = float(m.group(2)); i = float(m.group(3))
        return {"user": u, "system": s, "idle": i, "total_busy": round(100.0 - i, 2)}
    return None

def read_macos_loadavg() -> Optional[List[float]]:
    out = run_command(["sysctl","-n","vm.loadavg"]).strip()
    nums = re.findall(r"[\d\.]+", out)
    return [float(x) for x in nums[:3]] if nums else None

def read_macos_uptime_seconds() -> Optional[int]:
    out = run_command(["sysctl","-n","kern.boottime"]).strip()
    m = re.search(r"sec\s*=\s*(\d+)", out)
    if not m:
        return None
    boot = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
    return int((datetime.now(timezone.utc) - boot).total_seconds())

def read_macos_system_serial() -> Dict[str, Optional[str]]:
    out = run_command(["system_profiler","SPHardwareDataType"])
    m = re.search(r"Serial Number.*:\s*([^\n]+)", out)
    return {"system_serial": m.group(1).strip() if m else None}

# --------------------------- CPU orchestrator (threaded) -------------------------

def collect_cpu_metrics() -> Dict[str, Any]:
    """Collect normalized CPU telemetry for the current OS (threaded where helpful)."""
    sysinfo: Dict[str, Any] = {
        "timestamp_utc": get_timestamp_utc_iso(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor()
        },
        "cpu_count_logical": os.cpu_count()
    }

    os_name = platform.system().lower()

    # Thread pool for IO-bound collectors
    with ThreadPoolExecutor(max_workers=8) as ex:

        if os_name == "linux":
            # Utilization requires two snapshots 1s apart (sequential)
            s1 = read_proc_stat_snapshot()
            time.sleep(1.0)
            s2 = read_proc_stat_snapshot()
            pct = compute_utilization_from_snapshots(s1, s2)

            futures = {
                "uptime": ex.submit(read_linux_uptime_seconds),
                "percpu_freq_hz": ex.submit(read_linux_per_cpu_freq_hz),
                "cache_info": ex.submit(read_linux_cache_info),
                "cpu_info": ex.submit(read_linux_cpu_info),
                "temps": ex.submit(read_linux_cpu_temperatures_c),
            }

            try:
                with open("/proc/loadavg") as f:
                    load_avg = [float(x) for x in f.read().split()[:3]]
            except Exception:
                load_avg = None

            results = {k: f.result() for k, f in futures.items()}

            total_pct = pct.get("cpu") if pct else None
            percpu = []
            if pct:
                for k, v in sorted(((k, v) for k, v in pct.items() if k.startswith("cpu") and k != "cpu"),
                                   key=lambda kv: int(kv[0][3:])):
                    percpu.append(v)

            # cpu0 clocks
            base0 = "/sys/devices/system/cpu/cpu0/cpufreq"
            cur = mmin = mmax = None
            try:
                if os.path.isfile(f"{base0}/scaling_cur_freq"):
                    with open(f"{base0}/scaling_cur_freq") as fcur:
                        cur = int(fcur.read().strip()) * 1000
                if os.path.isfile(f"{base0}/cpuinfo_min_freq"):
                    with open(f"{base0}/cpuinfo_min_freq") as fmin:
                        mmin = int(fmin.read().strip()) * 1000
                if os.path.isfile(f"{base0}/cpuinfo_max_freq"):
                    with open(f"{base0}/cpuinfo_max_freq") as fmax:
                        mmax = int(fmax.read().strip()) * 1000
            except Exception:
                pass

            sysinfo.update({
                "uptime_seconds": results["uptime"],
                "utilization_percent_total": total_pct,
                "utilization_percent_percpu": percpu if percpu else None,
                "load_avg": load_avg,
                "cpu_freq_hz": {
                    "current": cur,
                    "min": mmin,
                    "max": mmax,
                    "percpu": results["percpu_freq_hz"]
                },
                "cpu_info": results["cpu_info"],
                "cache_info": results["cache_info"],
                "temperatures_c": results["temps"],
                "ids_serials": {"cpu_serial_dmidecode": None, "cpu_id_dmidecode": None, "system_serial": None, "baseboard_serial": None}
            })

        elif os_name == "windows":
            cpu = query_windows_cpu_properties()

            futures = {
                "per_util": ex.submit(collect_windows_percpu_utilization),
                "qlen": ex.submit(read_windows_processor_queue_length),
                "uptime": ex.submit(read_windows_uptime_seconds),
                "serials": ex.submit(query_windows_serials),
                "temps": ex.submit(read_windows_acpi_temperatures_c),
            }

            arch_map = {0:"x86", 5:"ARM", 6:"IA64", 9:"x64", 12:"ARM64"}
            arch_code = to_int(cpu.get("Architecture"))
            max_mhz = to_int(cpu.get("MaxClockSpeed"))
            cur_mhz = to_int(cpu.get("CurrentClockSpeed"))

            freq_future = ex.submit(collect_windows_percpu_frequency_hz, max_clock_mhz=max_mhz)

            results = {k: f.result() for k, f in futures.items()}
            perfreq_hz, totalfreq_hz = freq_future.result()

            sysinfo.update({
                "uptime_seconds": results["uptime"],
                "utilization_percent_total": to_int(cpu.get("LoadPercentage")),
                "utilization_percent_percpu": results["per_util"],
                "processor_queue_length": results["qlen"],
                "cpu_freq_hz": {
                    "current": (cur_mhz * 1_000_000) if cur_mhz else totalfreq_hz,
                    "min": None,
                    "max": (max_mhz * 1_000_000) if max_mhz else None,
                    "percpu": perfreq_hz
                },
                "cpu_info": {
                    "name": cpu.get("Name"),
                    "manufacturer": cpu.get("Manufacturer"),
                    "caption": cpu.get("Caption"),
                    "architecture_code": arch_code,
                    "architecture": arch_map.get(arch_code),
                    "socket": cpu.get("SocketDesignation"),
                    "processor_id": cpu.get("ProcessorId")
                },
                "core_counts": {
                    "physical": to_int(cpu.get("NumberOfCores")),
                    "logical": to_int(cpu.get("NumberOfLogicalProcessors"))
                },
                "cache_info": {
                    "L2_KB": to_int(cpu.get("L2CacheSize")),
                    "L3_KB": to_int(cpu.get("L3CacheSize"))
                },
                "temperatures_c": results["temps"],
                "ids_serials": {
                    "cpu_serial": None,
                    **results["serials"]
                }
            })

        elif os_name == "darwin":  # macOS
            sctl = read_macos_sysctl([
                "machdep.cpu.brand_string",
                "machdep.cpu.features",
                "machdep.cpu.leaf7_features",
                "hw.ncpu",
                "hw.physicalcpu",
                "hw.cpufrequency",
                "hw.cpufrequency_max",
                "hw.cpufrequency_min",
                "hw.l1icachesize",
                "hw.l1dcachesize",
                "hw.l2cachesize",
                "hw.l3cachesize"
            ])

            futures = {
                "util": ex.submit(read_macos_cpu_utilization),
                "load_avg": ex.submit(read_macos_loadavg),
                "uptime": ex.submit(read_macos_uptime_seconds),
                "serials": ex.submit(read_macos_system_serial),
            }
            results = {k: f.result() for k, f in futures.items()}

            def i_or_none(k): return to_int(sctl.get(k))

            sysinfo.update({
                "uptime_seconds": results["uptime"],
                "utilization_percent_total": (results["util"] or {}).get("total_busy"),
                "utilization_breakdown": results["util"],
                "load_avg": results["load_avg"],
                "cpu_freq_hz": {
                    "current": i_or_none("hw.cpufrequency"),
                    "max": i_or_none("hw.cpufrequency_max"),
                    "min": i_or_none("hw.cpufrequency_min"),
                    "percpu": None
                },
                "cpu_info": {
                    "brand": sctl.get("machdep.cpu.brand_string"),
                    "features": (sctl.get("machdep.cpu.features") or "").split(),
                    "leaf7_features": (sctl.get("machdep.cpu.leaf7_features") or "").split()
                },
                "core_counts": {
                    "physical": i_or_none("hw.physicalcpu"),
                    "logical": i_or_none("hw.ncpu")
                },
                "cache_info": {
                    "L1i_bytes": i_or_none("hw.l1icachesize"),
                    "L1d_bytes": i_or_none("hw.l1dcachesize"),
                    "L2_bytes": i_or_none("hw.l2cachesize"),
                    "L3_bytes": i_or_none("hw.l3cachesize")
                },
                "temperatures_c": None,
                "ids_serials": {
                    "system_serial": (results["serials"] or {}).get("system_serial"),
                    "cpu_serial": None
                }
            })

        else:
            sysinfo["error"] = f"Unsupported platform: {os_name}"

    # --------------------------- Post-collection normalization -------------------------

    # 1) Frequencies: convert Hz → MHz (integers), in-place under existing key `cpu_freq_hz`
    freq = sysinfo.get("cpu_freq_hz")
    if freq:
        freq["current"] = hz_to_mhz(freq.get("current"))
        freq["min"]     = hz_to_mhz(freq.get("min"))
        freq["max"]     = hz_to_mhz(freq.get("max"))
        if isinstance(freq.get("percpu"), list):
            freq["percpu"] = [hz_to_mhz(x) for x in freq["percpu"]]

    # (Optional) adjust Linux max to observed turbo if percpu shows higher than base
    if os_name == "linux" and freq and isinstance(freq.get("percpu"), list):
        observed_max = max([v for v in freq["percpu"] if isinstance(v, int)], default=None)
        if observed_max and (freq.get("max") is None or (isinstance(freq.get("max"), int) and observed_max > freq["max"])):
            freq["max"] = observed_max

    # 2) Cache: add MB alongside KB where available
    cache = sysinfo.get("cache_info")
    if cache:
        if "L2_KB" in cache and cache["L2_KB"] is not None: cache["L2_MB"] = kb_to_mb(cache["L2_KB"])
        if "L3_KB" in cache and cache["L3_KB"] is not None: cache["L3_MB"] = kb_to_mb(cache["L3_KB"])

    # 3) Utilization rounding to 1 decimal
    if "utilization_percent_total" in sysinfo and sysinfo["utilization_percent_total"] is not None:
        sysinfo["utilization_percent_total"] = round1(sysinfo["utilization_percent_total"])
    if "utilization_percent_percpu" in sysinfo and isinstance(sysinfo["utilization_percent_percpu"], list):
        sysinfo["utilization_percent_percpu"] = [round1(x) if x is not None else None for x in sysinfo["utilization_percent_percpu"]]

    # 3b) Clamp per-CPU list to cpu_count_logical (Windows sometimes returns a stray extra instance)
    vals = sysinfo.get("utilization_percent_percpu")
    count = sysinfo.get("cpu_count_logical")
    if isinstance(vals, list) and isinstance(count, int) and count > 0 and len(vals) > count:
        sysinfo["utilization_percent_percpu"] = vals[:count]

    # 3c) PATCH: Compute total utilization if missing (Windows occasionally returns None)
    if sysinfo.get("utilization_percent_total") is None:
        vals2 = sysinfo.get("utilization_percent_percpu")
        if isinstance(vals2, list) and vals2:
            numeric = [float(v) for v in vals2 if v is not None]
            if numeric:
                sysinfo["utilization_percent_total"] = round1(sum(numeric) / len(numeric))

    # 4) Canonicalize temperature keys and null-out empty dicts
    sysinfo["temperatures_c"] = normalize_temperature_keys(os_name, sysinfo.get("temperatures_c"))
    if isinstance(sysinfo.get("temperatures_c"), dict) and not sysinfo["temperatures_c"]:
        sysinfo["temperatures_c"] = None

    return sysinfo

# ------------------------- Endpoints -------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    smi = find_nvidia_smi()
    return {
        "status": "ok" if smi else "degraded",
        "nvidia_smi_path": smi,
        "timeout_sec": RUN_TIMEOUT_SEC,
        "endpoints": ["/health", "/docs/", "/nvidia/", "/cpu"],
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

@app.get("/cpu", dependencies=[Depends(require_api_key)], summary="On-demand CPU telemetry (normalized, cross-platform)")
def cpu_latest() -> Dict[str, Any]:
    """
    Collect CPU metrics NOW and return normalized telemetry.
    - Frequencies are in MHz (integers) under `cpu_freq_hz` key (by request).
    - Temperatures have canonical keys (cpu.package.N, cpu.core.N, platform.acpi.zone.N).
    - Utilization is rounded to 1 decimal and computed from per-CPU values when missing.
    """
    try:
        data = collect_cpu_metrics()
        return sanitize_json(data)
    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="CPU collection timed out")
    except Exception as e:
        logger.exception("cpu endpoint failed: %s", e)
        raise HTTPException(status_code=502, detail=f"cpu query failed: {e}")
