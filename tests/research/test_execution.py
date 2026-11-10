import json

from research.evaluate import execution, runs, suite

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


def write_run(root, run_id, devices):
    """A run directory whose rows point at artifacts with review requests."""
    directory = root / "runs/evaluations" / run_id / "benchmark/local-speed"
    for index, device in enumerate(devices):
        artifacts = root / "artifacts" / f"{run_id}-{index}"
        request = artifacts / "decisions/0001/request.json"
        request.parent.mkdir(parents=True)
        request.write_text(json.dumps({"decision_device": device}))
        row = directory / "rows" / f"{index}.json"
        row.parent.mkdir(parents=True, exist_ok=True)
        row.write_text(json.dumps({"key": str(index), "artifacts": str(artifacts)}))


def old_summary(run_id, configuration="local-speed"):
    return {
        "kind": suite.SUMMARY_KIND,
        "run_id": run_id,
        "manifest": {
            "configuration": {"scan_options": suite.CONFIGURATIONS[configuration]}
        },
        "host": {
            "platform": "macOS-27.0.1-arm64-arm-64bit",
            "hardware": {
                "machdep.cpu.brand_string": "Apple M2",
                "hw.memsize": str(16 * 1024**3),
                "hw.physicalcpu": "8",
                "hw.logicalcpu": "8",
            },
        },
        "local_artifacts": f"runs/evaluations/{run_id}",
    }


def test_backfill_uses_recorded_review_devices_and_host(tmp_path):
    write_run(tmp_path, "r", ["mps", "mps"])
    value = execution.backfill(
        old_summary("r"), tmp_path / "runs/evaluations/r/benchmark"
    )
    assert value["host"] == {
        "system": "macOS-27.0.1-arm64-arm-64bit",
        "cpu": "Apple M2",
        "physical_cpus": 8,
        "logical_cpus": 8,
        "memory_bytes": 16 * 1024**3,
        "gpu": {"name": "Apple GPU (MPS)"},
    }
    assert (
        value["decision"]
        == value["detector"]
        == {
            "model": "d1",
            "device": "mps",
            "dtype": "float16",
        }
    )
    assert value["backfilled"]["decision_requests"] == 2
    assert value["backfilled"]["decision_devices"] == ["mps"]


def test_backfill_leaves_unknown_or_mixed_devices_unrecorded(tmp_path):
    write_run(tmp_path, "mixed", ["mps", "cpu"])
    for directory in (None, tmp_path / "runs/evaluations/mixed/benchmark"):
        value = execution.backfill(old_summary("mixed"), directory)
        assert value["decision"] == {"model": "d1", "device": None, "dtype": None}
        assert value["host"]["gpu"] == "not recorded"
        lines = execution.report_lines(value)
        assert "GPU not recorded" in lines[3]
        assert "d1, device not recorded" in lines[5]


def test_backfill_command_updates_baselines_and_runs_once(tmp_path):
    write_run(tmp_path, "r", ["mps"])
    baseline = tmp_path / suite.BASELINES / "r.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps(old_summary("r")))
    summary = tmp_path / "runs/evaluations/r/summary.json"
    summary.write_text(json.dumps(old_summary("r")))
    cloud = tmp_path / "runs/evaluations/c/summary.json"
    cloud.parent.mkdir(parents=True)
    cloud.write_text(json.dumps(old_summary("c", "cloud-google")))

    assert len(runs.backfill_execution(tmp_path, dry_run=True)) == 3
    assert "execution" not in json.loads(baseline.read_text())

    changed = runs.backfill_execution(tmp_path)
    assert [path for path, _ in changed] == [baseline, cloud, summary]
    assert json.loads(baseline.read_text())["execution"]["decision"]["device"] == "mps"
    assert json.loads(cloud.read_text())["execution"]["ocr"]["device"] == "api"
    assert runs.backfill_execution(tmp_path) == []
