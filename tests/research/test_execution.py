from research.evaluate import execution, suite

HOST = {
    "system": "fixture",
    "cpu": "Apple M4 Pro",
    "physical_cpus": 14,
    "logical_cpus": 14,
    "memory_bytes": 48 * 1024**3,
}


def record(name, device):
    calls = []

    def selected():
        calls.append(name)
        return device

    return execution.record(
        suite.CONFIGURATIONS[name], device=selected, host=lambda: HOST
    ), calls


def test_local_models_record_the_selected_torch_device():
    mps = {"device": "mps", "dtype": "float16", "name": "Apple GPU (MPS)"}
    value, _ = record("local-quality-clef-flash", mps)
    assert value["ocr"] == {"model": "ppocr-v6", "device": "cpu"}
    assert (
        value["decision"]
        == value["detector"]
        == {
            "model": "clef-flash",
            "device": "mps",
            "dtype": "float16",
        }
    )
    assert value["host"] == {**HOST, "gpu": {"name": "Apple GPU (MPS)"}}
    lines = execution.report_lines(value)
    assert "Host: Apple M4 Pro; 14 physical / 14 logical CPUs; 48 GiB RAM" in lines[3]
    assert lines[5] == (
        "OCR: ppocr-v6 on CPU. OCR review: clef-flash on MPS, float16. "
        "Injection detector: clef-flash on MPS, float16."
    )


def test_prompt_guard_runs_on_cpu_and_cuda_records_gpu_memory():
    cuda = {
        "device": "cuda",
        "dtype": "bfloat16",
        "name": "NVIDIA L4",
        "memory_bytes": 24 * 1024**3,
    }
    value, _ = record("local-speed-prompt-guard", cuda)
    assert value["detector"] == {
        "model": "prompt-guard",
        "device": "cpu",
        "dtype": "float32",
    }
    assert value["decision"]["device"] == "cuda"
    assert value["host"]["gpu"] == {"name": "NVIDIA L4", "memory_bytes": 24 * 1024**3}
    assert "NVIDIA L4 (24 GiB)" in execution.report_lines(value)[3]


def test_cloud_configurations_use_apis_and_do_not_load_torch():
    value, calls = record("cloud-google-jev", None)
    assert calls == []
    assert value["host"]["gpu"] is None
    assert value["ocr"] == {
        "model": "google-cloud-vision",
        "device": "api",
        "provider": "google",
    }
    assert value["decision"] == {"model": "openai", "device": "api"}
    assert value["detector"] == {"model": "jev", "device": "api"}
    assert "no GPU used" in execution.report_lines(value)[3]


def test_machine_reports_this_host():
    value = execution.machine()
    assert value["logical_cpus"] >= 1 and value["memory_bytes"] > 0
