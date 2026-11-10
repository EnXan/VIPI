"""Where a run executed: the host machine and the device of each component.

Recorded in every run summary so times and memory can be read against the
hardware they were measured on (ADR 0062). The torch rule mirrors
``vipi.local_decisions.LocalDecisionModel._runtime``; it is repeated here so
product sources, and with them reusable earlier results (ADR 0058), stay
unchanged. Local OCR runs on CPU through ONNX Runtime (``vipi.ocr.session``)
and Prompt Guard is loaded on CPU (``vipi.detection.providers.prompt_guard``).
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess

from vipi.config import LOCAL_DECISION_PROVIDERS, ScanOptions

# dtype per device, as vipi.local_decisions loads decision models.
DTYPES = {"cuda": "bfloat16", "mps": "float16", "cpu": "float32"}
MPS_NAME = "Apple GPU (MPS)"


def sysctl(key):
    try:
        result = subprocess.run(
            ["sysctl", "-n", key], check=False, capture_output=True, text=True
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def cpu_name():
    if platform.system() == "Darwin":
        return sysctl("machdep.cpu.brand_string")
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def torch_device():
    """The device and dtype local decision models select on this host."""
    import torch

    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        return {
            "device": "cuda",
            "dtype": DTYPES["cuda"],
            "name": properties.name,
            "memory_bytes": properties.total_memory,
        }
    if torch.backends.mps.is_available():
        return {"device": "mps", "dtype": DTYPES["mps"], "name": MPS_NAME}
    return {"device": "cpu", "dtype": DTYPES["cpu"]}


def machine():
    import psutil

    return {
        "system": platform.platform(),
        "cpu": cpu_name(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "logical_cpus": os.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
    }


def record(scan_options, *, device=None, host=None):
    """Host and per-component devices for one configuration's scan options."""
    options = ScanOptions(**scan_options)
    local_models = {
        options.resolved_decision_provider,
        options.resolved_detector,
    } & set(LOCAL_DECISION_PROVIDERS)
    # Looked up at call time so tests can replace the module functions.
    selected = (device or torch_device)() if local_models else None

    def component(name):
        if name in LOCAL_DECISION_PROVIDERS:
            return {
                "model": name,
                "device": selected["device"],
                "dtype": selected["dtype"],
            }
        if name == "prompt-guard":
            return {"model": name, "device": "cpu", "dtype": "float32"}
        return {"model": name, "device": "api"}

    if selected is None or selected["device"] == "cpu":
        gpu = None
    elif selected["device"] is None:
        gpu = "not recorded"
    else:
        gpu = {
            key: value
            for key, value in selected.items()
            if key in ("name", "memory_bytes")
        }
    local_ocr = options.resolved_ocr_execution_mode == "local"
    return {
        "host": {**(host or machine)(), "gpu": gpu},
        "ocr": {
            "model": options.resolved_ocr_model,
            "device": "cpu" if local_ocr else "api",
            **({} if local_ocr else {"provider": options.resolved_ocr_provider}),
        },
        "decision": component(options.resolved_decision_provider),
        "detector": component(options.resolved_detector),
    }


def describe_component(value):
    if value["device"] == "api":
        return f"{value['model']} via API"
    if value["device"] is None:
        return f"{value['model']}, device not recorded"
    precision = f", {value['dtype']}" if value.get("dtype") else ""
    return f"{value['model']} on {value['device'].upper()}{precision}"


def report_lines(execution):
    """Markdown lines for the run report."""
    host = execution["host"]
    memory = (
        f"{host['memory_bytes'] / 1024**3:.0f} GiB RAM"
        if host.get("memory_bytes")
        else "RAM unknown"
    )
    gpu = host.get("gpu")
    if isinstance(gpu, str):
        gpu_text = f"GPU {gpu}"
    else:
        gpu_text = gpu["name"] if gpu else "no GPU used"
    if isinstance(gpu, dict) and gpu.get("memory_bytes"):
        gpu_text += f" ({gpu['memory_bytes'] / 1024**3:.0f} GiB)"
    return [
        "",
        "## Execution",
        "",
        f"Host: {host.get('cpu') or 'CPU unknown'}; "
        f"{host.get('physical_cpus') or '?'} physical / "
        f"{host.get('logical_cpus') or '?'} logical CPUs; {memory}; {gpu_text}; "
        f"{host.get('system') or 'system unknown'}.",
        "",
        f"OCR: {describe_component(execution['ocr'])}. "
        f"OCR review: {describe_component(execution['decision'])}. "
        f"Injection detector: {describe_component(execution['detector'])}.",
    ]


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def observed_decision_devices(benchmark_directory):
    """Devices OCR review requests recorded in a run's local artifacts.

    ``vipi.ocr.recovery.decision_adapters`` writes the device the loaded
    decision model actually used (``decision_device``) into every local review
    request; the injection detector reuses that loaded model in the same
    worker process. Returns the set of devices and the number of requests."""
    devices, requests = set(), 0
    for path in sorted(Path(benchmark_directory).glob("*/rows/*.json")):
        row = read_json(path)
        if not isinstance(row, dict) or not row.get("artifacts"):
            continue
        for request in Path(row["artifacts"]).glob("decisions/*/request.json"):
            value = (read_json(request) or {}).get("decision_device")
            if value:
                devices.add(value)
                requests += 1
    return devices, requests


def recorded_host(host):
    """The host block every summary already has (macOS sysctl values)."""
    hardware = host.get("hardware") or {}

    def number(key):
        value = hardware.get(key)
        return int(value) if value not in (None, "") else None

    return {
        "system": host.get("platform"),
        "cpu": hardware.get("machdep.cpu.brand_string"),
        "physical_cpus": number("hw.physicalcpu"),
        "logical_cpus": number("hw.logicalcpu"),
        "memory_bytes": number("hw.memsize"),
    }


def backfill(summary, benchmark_directory=None):
    """Execution for a summary written before ADR 0062, from recorded data only.

    The host comes from the summary's own host block. The device of local
    decision models comes from the review requests in the run's local
    artifacts; without them, or if they disagree, it stays unrecorded."""
    devices, requests = (
        observed_decision_devices(benchmark_directory)
        if benchmark_directory is not None
        else (set(), 0)
    )
    device = next(iter(devices)) if len(devices) == 1 else None
    selected = {"device": device, "dtype": DTYPES.get(device)}
    if device == "mps":
        selected["name"] = MPS_NAME
    elif device == "cuda":
        selected["name"] = "CUDA GPU (model not recorded)"
    value = record(
        summary["manifest"]["configuration"]["scan_options"],
        device=lambda: selected,
        host=lambda: recorded_host(summary.get("host") or {}),
    )
    return {
        **value,
        "backfilled": {
            "at": datetime.now(timezone.utc).isoformat(),
            "decision_requests": requests,
            "decision_devices": sorted(devices),
        },
    }
