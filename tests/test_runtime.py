from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import sys

import pytest

from ocr_pipeline.runtime import (
    rapid_runtime_params,
    threads_per_worker,
    validate_backend,
    validate_session_providers,
    cuda_available,
    prepare_backend,
)


@pytest.mark.parametrize(
    "cores,workers,expected", [(8, 4, 2), (8, 8, 1), (8, 1, 8), (2, 8, 1), (None, 4, 1)]
)
def test_cpu_budget_is_shared_between_workers(monkeypatch, cores, workers, expected):
    monkeypatch.setattr("ocr_pipeline.runtime.os.cpu_count", lambda: cores)
    assert threads_per_worker(workers) == expected


def test_coreml_requires_a_supported_runtime_and_model(monkeypatch):
    monkeypatch.setattr("ocr_pipeline.runtime.coreml_available", lambda: False)
    validate_backend("tesseract", "cpu")
    with pytest.raises(ValueError, match="macOS"):
        validate_backend("ppocr-v6", "coreml")
    monkeypatch.setattr("ocr_pipeline.runtime.coreml_available", lambda: True)
    validate_backend("ppocr-v6", "coreml")
    with pytest.raises(ValueError, match="Tesseract"):
        validate_backend("tesseract", "coreml")
    for backend in [None, "unknown", [], {}]:
        with pytest.raises(ValueError, match="Choose"):
            validate_backend("ppocr-v6", backend)


def test_cuda_requires_the_gpu_runtime_and_rejects_tesseract(monkeypatch):
    monkeypatch.setattr("ocr_pipeline.runtime.cuda_available", lambda: False)
    with pytest.raises(ValueError, match="ocr-cuda"):
        validate_backend("ppocr-v6", "cuda")
    monkeypatch.setattr("ocr_pipeline.runtime.cuda_available", lambda: True)
    validate_backend("ppocr-v6", "cuda")
    with pytest.raises(ValueError, match="Tesseract"):
        validate_backend("tesseract", "cuda")


@pytest.mark.parametrize(
    "platform,expected", [("linux", True), ("win32", True), ("darwin", False)]
)
def test_cuda_provider_detection(monkeypatch, platform, expected):
    monkeypatch.setattr("ocr_pipeline.runtime.sys.platform", platform)
    runtime = SimpleNamespace(get_available_providers=lambda: ["CUDAExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", runtime)
    assert cuda_available() is expected
    runtime.get_available_providers = lambda: ["CPUExecutionProvider"]
    assert not cuda_available()


def test_cuda_libraries_are_loaded_once_before_concurrent_sessions(monkeypatch):
    calls = []
    runtime = SimpleNamespace(preload_dlls=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setitem(sys.modules, "onnxruntime", runtime)
    monkeypatch.setattr("ocr_pipeline.runtime._cuda_loaded", False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(prepare_backend, ["cuda"] * 8))
    prepare_backend("cpu")
    assert calls == [{"directory": ""}]


@pytest.mark.parametrize(
    "backend,provider",
    [("cuda", "CUDAExecutionProvider"), ("coreml", "CoreMLExecutionProvider")],
)
def test_gpu_session_fallback_is_an_error_for_either_model(backend, provider):
    working = [provider, "CPUExecutionProvider"]
    validate_session_providers(backend, {"detector": working, "recognizer": working})
    for failed in ["detector", "recognizer"]:
        providers = {"detector": working, "recognizer": working}
        providers[failed] = ["CPUExecutionProvider"]
        with pytest.raises(RuntimeError, match="fell back entirely to CPU"):
            validate_session_providers(backend, providers)


def test_cuda_configuration_limits_workspace_and_keeps_fp32(tmp_path):
    params = rapid_runtime_params("cuda", 2, tmp_path)
    assert params["EngineConfig.onnxruntime.use_cuda"] is True
    assert params["EngineConfig.onnxruntime.use_coreml"] is False
    assert (
        params["EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search"]
        == "HEURISTIC"
    )
    assert params["EngineConfig.onnxruntime.cuda_ep_cfg.use_tf32"] == "0"
    assert (
        params["EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_use_max_workspace"]
        == "0"
    )
    assert (
        rapid_runtime_params("cpu", 1, tmp_path)["EngineConfig.onnxruntime.use_cuda"]
        is False
    )


def test_coreml_configuration_keeps_dynamic_shapes_and_precise_accumulation(tmp_path):
    params = rapid_runtime_params("coreml", 2, tmp_path)
    assert params["EngineConfig.onnxruntime.intra_op_num_threads"] == 2
    assert params["EngineConfig.onnxruntime.inter_op_num_threads"] == 1
    assert params["EngineConfig.onnxruntime.use_coreml"] is True
    assert (
        params["EngineConfig.onnxruntime.coreml_ep_cfg.RequireStaticInputShapes"] == "0"
    )
    assert (
        params[
            "EngineConfig.onnxruntime.coreml_ep_cfg.AllowLowPrecisionAccumulationOnGPU"
        ]
        == "0"
    )
    assert Path(
        params["EngineConfig.onnxruntime.coreml_ep_cfg.ModelCacheDirectory"]
    ).is_dir()
    assert (
        rapid_runtime_params("cpu", 1, tmp_path)["EngineConfig.onnxruntime.use_coreml"]
        is False
    )
