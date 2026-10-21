"""Hardware backends and a shared CPU budget across OCR workers."""

import os
import sys
import threading

from .workers import worker_count

DEFAULT_BACKEND = "cpu"
BACKENDS = ("cpu", "coreml", "cuda")
_cuda_load_lock = threading.Lock()
_cuda_loaded = False


def threads_per_worker(workers):
    return max(1, (os.cpu_count() or 1) // worker_count(workers))


def coreml_available():
    if sys.platform != "darwin":
        return False
    try:
        import onnxruntime

        return "CoreMLExecutionProvider" in onnxruntime.get_available_providers()
    except ImportError:
        return False


def cuda_available():
    if sys.platform not in {"linux", "win32"}:
        return False
    try:
        import onnxruntime

        return "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    except ImportError:
        return False


def prepare_backend(backend):
    """Load bundled NVIDIA libraries once, before any worker creates a session."""
    global _cuda_loaded
    if backend != "cuda":
        return
    with _cuda_load_lock:
        if not _cuda_loaded:
            import onnxruntime

            onnxruntime.preload_dlls(directory="")
            _cuda_loaded = True


def validate_backend(model, backend):
    if backend not in BACKENDS:
        raise ValueError("Choose the cpu, coreml or cuda backend.")
    if model == "tesseract" and backend != "cpu":
        raise ValueError("Tesseract supports only the CPU backend.")
    if backend == "coreml":
        if not coreml_available():
            raise ValueError(
                "CoreML requires macOS and an ONNX Runtime with CoreML support."
            )
    if backend == "cuda" and not cuda_available():
        raise ValueError(
            "CUDA requires Linux or Windows, an NVIDIA GPU and onnxruntime-gpu. "
            "Install the ocr-cuda extra; see research/workbench/README.md."
        )


def validate_session_providers(backend, providers):
    required = {
        "coreml": "CoreMLExecutionProvider",
        "cuda": "CUDAExecutionProvider",
    }.get(backend)
    if required and any(required not in values for values in providers.values()):
        raise RuntimeError(
            f"{backend} session creation fell back entirely to CPU for an OCR model. "
            "Check the GPU driver and runtime libraries, or choose CPU explicitly."
        )


def backend_options():
    return [
        {"id": "cpu", "label": "CPU", "available": True},
        {
            "id": "coreml",
            "label": "Apple CoreML · experimentell",
            "available": coreml_available(),
        },
        {"id": "cuda", "label": "NVIDIA CUDA", "available": cuda_available()},
    ]


def rapid_runtime_params(backend, threads, directory):
    params = {
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_coreml": backend == "coreml",
        "EngineConfig.onnxruntime.use_cuda": backend == "cuda",
    }
    if backend == "cuda":
        params.update(
            {
                "EngineConfig.onnxruntime.cuda_ep_cfg.device_id": 0,
                "EngineConfig.onnxruntime.cuda_ep_cfg.arena_extend_strategy": "kSameAsRequested",
                "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
                "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_use_max_workspace": "0",
                "EngineConfig.onnxruntime.cuda_ep_cfg.use_tf32": "0",
            }
        )
    if backend == "coreml":
        cache = directory / "coreml-cache"
        cache.mkdir(parents=True, exist_ok=True)
        params.update(
            {
                "EngineConfig.onnxruntime.coreml_ep_cfg.ModelFormat": "MLProgram",
                "EngineConfig.onnxruntime.coreml_ep_cfg.MLComputeUnits": "ALL",
                "EngineConfig.onnxruntime.coreml_ep_cfg.RequireStaticInputShapes": "0",
                "EngineConfig.onnxruntime.coreml_ep_cfg.AllowLowPrecisionAccumulationOnGPU": "0",
                "EngineConfig.onnxruntime.coreml_ep_cfg.ModelCacheDirectory": str(
                    cache.resolve()
                ),
            }
        )
    return params
