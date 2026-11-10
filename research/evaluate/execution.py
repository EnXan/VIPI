"""Where a run executed: the host machine and the device of each component.

Recorded in every run summary so times and memory can be read against the
hardware they were measured on (ADR 0062). The torch rule mirrors
``vipi.local_decisions.LocalDecisionModel._runtime``; it is repeated here so
product sources, and with them reusable earlier results (ADR 0058), stay
unchanged. Local OCR runs on CPU through ONNX Runtime (``vipi.ocr.session``)
and Prompt Guard is loaded on CPU (``vipi.detection.providers.prompt_guard``).
"""

import os
from pathlib import Path
import platform
import subprocess

from vipi.config import LOCAL_DECISION_PROVIDERS, ScanOptions

TORCH_MODELS = (*LOCAL_DECISION_PROVIDERS, "prompt-guard")


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
            "dtype": "bfloat16",
            "name": properties.name,
            "memory_bytes": properties.total_memory,
        }
    if torch.backends.mps.is_available():
        return {"device": "mps", "dtype": "float16", "name": "Apple GPU (MPS)"}
    return {"device": "cpu", "dtype": "float32"}


def machine():
    import psutil

    return {
        "system": platform.platform(),
        "cpu": cpu_name(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "logical_cpus": os.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
    }


def record(scan_options, *, device=torch_device, host=machine):
    """Host and per-component devices for one configuration's scan options."""
    options = ScanOptions(**scan_options)
    local_models = {
        options.resolved_decision_provider,
        options.resolved_detector,
    } & set(LOCAL_DECISION_PROVIDERS)
    selected = device() if local_models else None

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

    local_ocr = options.resolved_ocr_execution_mode == "local"
    return {
        "host": {
            **host(),
            "gpu": None
            if selected is None or selected["device"] == "cpu"
            else {
                key: value
                for key, value in selected.items()
                if key in ("name", "memory_bytes")
            },
        },
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
    gpu_text = gpu["name"] if gpu else "no GPU used"
    if gpu and gpu.get("memory_bytes"):
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
