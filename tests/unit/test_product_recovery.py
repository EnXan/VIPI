"""Mode isolation, shared recovery and local decision contracts."""

from dataclasses import asdict
import hashlib
import json
import socket

from PIL import Image
import pytest

from vipi.config import ScanOptions
from vipi.ocr.recovery import pipeline as recovery_pipeline
from vipi.ocr.recovery.tiles import recover_with_tiles
from vipi.ocr.transforms import views_for_size
from vipi.storage.ocr import RunStore


@pytest.mark.parametrize(
    "mode,decision,ocr",
    [
        ("quality", "clef-flash", "ppocr-v6"),
        ("balanced", "d1", "ppocr-v6-small"),
        ("speed", "d1", "ppocr-v6-tiny"),
        ("fast", "d1", "ppocr-v6-tiny"),
    ],
)
def test_full_local_mode_resolves_both_model_roles(mode, decision, ocr):
    options = ScanOptions(ocr_mode=mode)
    assert options.resolved_ocr_model == ocr
    assert options.resolved_decision_provider == options.resolved_detector == decision
    assert set(options.detection_options()["thresholds"]["signals"]) == {decision}


@pytest.mark.parametrize(
    "options",
    [
        {"ocr_execution_mode": "local", "decision_provider": "openai"},
        {"ocr_execution_mode": "local", "detector": "jev"},
        {"ocr_execution_mode": "cloud", "decision_provider": "d1"},
        {"ocr_execution_mode": "cloud", "detector": "prompt-guard"},
    ],
)
def test_mixed_execution_is_rejected_before_any_provider(options, monkeypatch):
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: pytest.fail("No network during routing"),
    )
    with pytest.raises(ValueError, match="conflicts with --modus"):
        ScanOptions(**options)


def test_cloud_provider_choices_are_independent_of_cloud_ocr():
    options = ScanOptions(
        ocr_execution_mode="cloud", ocr_provider="mistral", decision_provider="jev"
    )
    assert options.resolved_ocr_model == "mistral-ocr-4-1"
    assert options.resolved_detector == options.resolved_decision_provider == "jev"


def test_missing_review_key_stops_before_billable_cloud_ocr(tmp_path, monkeypatch):
    from vipi.scanner import scan

    source = tmp_path / "input.png"
    Image.new("RGB", (32, 24)).save(source)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-key")
    monkeypatch.setenv("GOOGLE_CLOUD_API_KEY", "fixture-key")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: pytest.fail("No request before credential validation"),
    )
    report = scan(
        [source], ocr_execution_mode="cloud", detector="jev", decision_provider="openai"
    )
    assert report["summary"]["not_scanned"] == 1
    assert "OPENAI_API_KEY for OCR decisions" in report["errors"][0]["error"]


def test_local_injection_and_visual_review_use_only_the_supplied_local_runtime(
    tmp_path, monkeypatch
):
    from vipi.detection.providers.local import LocalDecisionProvider
    from vipi.ocr.recovery.decision_adapters import LocalDecider

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: pytest.fail("Local must stay offline"),
    )
    calls = []

    class Runtime:
        model = "local-fixture"
        identity = {"revision": "fixture"}
        device = "mps"

        def ask(self, state, questions, images=None):
            calls.append((state, questions, images))
            return {
                "answers": {
                    name: {
                        "type": q["type"],
                        **(
                            {
                                "choice": {
                                    "completeness": "complete",
                                    "reviewability": "sufficient",
                                    "repair": "none",
                                }.get(name, next(iter(q.get("criteria", {})), "ready")),
                                "confidence": 0.9,
                            }
                            if q["type"] == "choice"
                            else {"noul": 0.8}
                        ),
                    }
                    for name, q in questions.items()
                }
            }

    runtime = Runtime()
    review = LocalDecider("d1", tmp_path, runtime=runtime)
    result = review.assess(
        Image.new("RGB", (300, 300)), {"text": "source text"}, tmp_path / "review"
    )
    assert result["estimated_usd"] == 0
    assert calls[0][0]["image_order"] == ["<original-image>"]
    assert len(calls[0][2]) == 1
    provider = LocalDecisionProvider("d1", tmp_path, runtime=runtime)
    assert (
        provider.check({"untrusted_evidence": {"text": "source text"}})["probability"]
        == 0.8
    )
    assert len(calls) == 2


def test_local_comparison_uses_original_and_candidate_with_complete_text_groups(
    tmp_path,
):
    from vipi.ocr.recovery.decision_adapters import LocalDecider

    class Runtime:
        model = "local-fixture"
        device = "mps"

        def __init__(self):
            self.images = []

        def ask(self, state, questions, images=None):
            self.images.append((state, images))
            return {
                "answers": {
                    "comparison": {
                        "type": "choice",
                        "choice": "equivalent",
                        "confidence": 0.9,
                    }
                }
            }

    runtime = Runtime()
    review = LocalDecider("d1", tmp_path, runtime=runtime)
    original = Image.new("RGB", (1800, 1200))
    incumbent = {
        "id": "0001",
        "text": "source transcription",
        "raster": original,
        "groups": [{"text": "source transcription", "box": [1, 2, 3, 4]}],
        "step": {"regions": []},
    }
    candidate = {
        "id": "0002",
        "text": "candidate transcription",
        "raster": Image.new("RGB", (3600, 2400)),
        "groups": [{"text": "candidate transcription", "box": [1, 2, 3, 4]}],
        "step": {"regions": []},
    }

    review.compare(original, incumbent, candidate, tmp_path / "compare")

    state, images = runtime.images[0]
    assert state["image_order"] == ["<source-image>", "<candidate-image>"]
    assert state["incumbent"]["image"] == "<source-image>"
    assert state["candidate"]["image"] == "<candidate-image>"
    assert state["incumbent"]["text_groups"] == ["source transcription"]
    assert state["candidate"]["text_groups"] == ["candidate transcription"]
    assert all("box" not in group for group in state["incumbent"]["text_groups"])
    assert len(images) == 2
    assert all(max(image.size) <= 512 for image in images)
    saved_request = json.loads((tmp_path / "compare" / "request.json").read_text())
    assert saved_request["ocr_mode"] == "quality"
    assert saved_request["decision_device"] == "mps"
    assert saved_request["preview_maximum"] == 512
    assert set(map(tuple, saved_request["submitted_image_sizes"].values())) == {
        (512, 341)
    }


def test_local_scan_requires_prepared_pinned_code_and_never_downloads(
    tmp_path, monkeypatch
):
    from vipi.local_decisions import LocalDecisionModel, MODELS

    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: pytest.fail("No downloads in scan")
    )
    code = b"# pinned fixture\n"
    monkeypatch.setitem(
        MODELS,
        "d1",
        {
            "runtime": "d1",
            "repository": "fixture/d1",
            "revision": "fixed",
            "code": {"model.py": hashlib.sha256(code).hexdigest()},
        },
    )
    with pytest.raises(ValueError, match="vipi setup"):
        LocalDecisionModel("d1", tmp_path)
    for name in ("config.json", "tokenizer_config.json", "model.safetensors"):
        (tmp_path / name).write_text("{}")
    (tmp_path / "READY.json").write_text(json.dumps({"revision": "fixed"}))
    (tmp_path / "model.py").write_bytes(code)
    assert LocalDecisionModel("d1", tmp_path).model == "fixture/d1"
    (tmp_path / "model.py").write_text("changed")
    with pytest.raises(ValueError, match="pinned revision"):
        LocalDecisionModel("d1", tmp_path)


def test_weak_boxes_do_not_trigger_small_text_tiles(tmp_path):
    original = Image.new("RGB", (400, 300))
    region = {
        "text": "KEEP",
        "confidence": 0.4,
        "input_polygon": [[10, 10], [60, 10], [60, 15], [10, 15]],
    }
    selected = {"text": "KEEP", "groups": [region], "step": {"regions": [region]}}
    result = recover_with_tiles(original, selected, None, None, [], None)
    assert result[0] == "KEEP" and not result[3]["triggered"]


def test_unscored_cloud_page_boxes_do_not_launch_unusable_tile_requests():
    original = Image.new("RGB", (2100, 300))
    region = {
        "text": "KEEP",
        "confidence": 0.0,
        "input_polygon": [[0, 0], [2100, 0], [2100, 300], [0, 300]],
    }
    selected = {
        "text": "KEEP",
        "groups": [region],
        "step": {"full_page_text": True, "regions": [region]},
    }
    result = recover_with_tiles(original, selected, None, None, [], None)
    assert result[0] == "KEEP"
    assert result[3]["skipped"] == "full_page_geometry_has_no_confident_tokens"


def test_tiles_preserve_incumbent_words_and_use_the_original_source(tmp_path):
    original = Image.new("RGB", (2100, 80), "red")
    view = views_for_size(*original.size, selected_ids={"original-unchanged-1x"})[0]
    region = {
        "text": "KEEP",
        "confidence": 0.99,
        "polygon": [[10, 10], [60, 10], [60, 30], [10, 30]],
        "input_polygon": [[10, 10], [60, 10], [60, 30], [10, 30]],
    }
    step = {
        "id": "0001",
        "regions": [region],
        "text": "KEEP",
        "transformation": asdict(view),
    }
    selected = {"text": "KEEP", "groups": [region], "step": step}

    class Engine:
        def recognize(self, image):
            assert image.getpixel((0, 0)) == (255, 0, 0)
            return {
                "text": "DROP",
                "regions": [
                    {
                        "text": "DROP",
                        "confidence": 1.0,
                        "polygon": [[10, 10], [60, 10], [60, 30], [10, 30]],
                    }
                ],
            }

    store = RunStore(tmp_path, "fixture")
    result = recover_with_tiles(
        original, selected, Engine(), store, [{"step": step}], None
    )
    assert result[0] == "KEEP"
    assert result[3]["triggered"] and not result[3]["selected"]
    assert result[3]["tile_count"] == len(result[2]) == 3


def test_clear_quality_signals_skip_every_decision_request(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (400, 300), "white").save(source)
    text = "This ordinary label contains enough readable text for the original OCR."

    class Engine:
        def recognize(self, image):
            return {
                "text": text,
                "regions": [
                    {
                        "text": text,
                        "confidence": 0.99,
                        "polygon": [[10, 20], [350, 20], [350, 40], [10, 40]],
                    }
                ],
            }

    class Decider:
        provider = "d1"
        model = "local-fixture"

        def assess(self, *args):
            pytest.fail("Clear local evidence must not invoke a decision model")

        compare = assess

    monkeypatch.setattr(
        "vipi.ocr.recovery.selection.route_extended",
        lambda *a, **k: {"route": "no_signal", "signals": [], "unavailable": []},
    )
    result = recovery_pipeline.extract(
        source,
        "ppocr-v6-tiny",
        engine=Engine(),
        decider=Decider(),
        runs_dir=tmp_path / "runs",
    )
    assert result["text"] == text
    assert result["selection"]["decisions"] == []
    assert result["cost"]["selection_api_calls"] == 0
    assert result["cost"]["estimated_usd"] == 0


@pytest.mark.parametrize("window", [None, 4])
def test_chunked_local_attention_retains_the_full_causal_context(window):
    import torch
    from vipi.local_attention import causal_attention

    torch.manual_seed(17)
    q = torch.randn(1, 4, 11, 8)
    k, v = torch.randn(1, 2, 11, 8), torch.randn(1, 2, 11, 8)
    positions = torch.arange(11)
    allowed = positions[None, :] <= positions[:, None]
    if window is not None:
        allowed &= positions[None, :] > positions[:, None] - window
    expected = torch.nn.functional.scaled_dot_product_attention(
        q,
        k.repeat_interleave(2, dim=1),
        v.repeat_interleave(2, dim=1),
        attn_mask=allowed,
        scale=0.25,
    )
    actual = causal_attention(q, k, v, window, 0.25, query_chunk=3)
    torch.testing.assert_close(actual, expected, rtol=1e-5, atol=1e-6)


def test_serial_vision_preserves_every_tile_and_hidden_state():
    import torch
    from transformers import Siglip2VisionConfig, Siglip2VisionModel
    from vipi.local_attention import serial_vision_forward

    torch.manual_seed(21)
    model = Siglip2VisionModel(
        Siglip2VisionConfig(
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_patches=4,
            patch_size=4,
        )
    ).eval()
    pixels = torch.randn(3, 4, 3 * 4 * 4)
    shapes = torch.tensor([[2, 2], [2, 2], [2, 2]])
    masks = torch.ones(3, 4)
    with torch.inference_mode():
        expected = model(
            pixel_values=pixels,
            spatial_shapes=shapes,
            pixel_attention_mask=masks,
            return_dict=True,
            output_hidden_states=True,
        )
        actual = serial_vision_forward(
            model.forward,
            pixels,
            shapes,
            masks,
            return_dict=True,
            output_hidden_states=True,
        )
    torch.testing.assert_close(actual.last_hidden_state, expected.last_hidden_state)
    torch.testing.assert_close(actual.pooler_output, expected.pooler_output)
    for got, want in zip(actual.hidden_states, expected.hidden_states, strict=True):
        torch.testing.assert_close(got, want)


def test_clef_flash_replaces_clef_as_the_pinned_quality_model():
    from vipi.config import DECISION_PROVIDERS, LOCAL_DECISION_PROVIDERS, ScanOptions
    from vipi.local_decisions import MODELS

    flash = MODELS["clef-flash"]
    assert flash["repository"] == "Cloudflare/clef-flash"
    assert len(flash["revision"]) == 40
    assert flash["runtime"] == "clef"
    assert MODELS["d1"]["runtime"] == "d1"
    assert set(MODELS) == {"clef-flash", "d1"}  # Clef was removed (ADR 0065)
    assert LOCAL_DECISION_PROVIDERS == ("clef-flash", "d1")
    assert "clef" not in DECISION_PROVIDERS
    with pytest.raises(ValueError, match="clef-flash"):
        ScanOptions(decision_provider="clef").resolved_decision_provider
    options = ScanOptions(ocr_mode="speed", decision_provider="clef-flash")
    assert options.resolved_decision_provider == "clef-flash"
    assert options.resolved_detector == "clef-flash"
    assert ScanOptions().resolved_decision_provider == "clef-flash"  # quality default
    with pytest.raises(ValueError, match="clef-flash"):
        ScanOptions(
            ocr_execution_mode="cloud", decision_provider="clef-flash"
        ).resolved_decision_provider


def test_clef_runtime_models_need_their_joint_head(tmp_path, monkeypatch):
    from vipi.local_decisions import MODELS, validate_model

    code = b"# pinned fixture\n"
    monkeypatch.setitem(
        MODELS,
        "clef-flash",
        {
            **MODELS["clef-flash"],
            "revision": "fixed",
            "code": {"joint_schema_model.py": hashlib.sha256(code).hexdigest()},
        },
    )
    (tmp_path / "READY.json").write_text(json.dumps({"revision": "fixed"}))
    (tmp_path / "joint_schema_model.py").write_bytes(code)
    for name in ("config.json", "tokenizer_config.json", "model.safetensors"):
        (tmp_path / name).write_text("{}")
    with pytest.raises(ValueError, match="joint_head.safetensors"):
        validate_model("clef-flash", tmp_path)
    (tmp_path / "joint_head.safetensors").write_bytes(b"")
    assert validate_model("clef-flash", tmp_path)["runtime"] == "clef"


def test_clef_runtime_can_load_with_a_device_map(tmp_path):
    # The pinned Clef/Clef-Flash loader (joint_schema_model.load_release_model)
    # calls from_pretrained(..., device_map={"": device}); transformers needs
    # accelerate for that, so it must ship with the detector-local extra.
    transformers = pytest.importorskip("transformers")

    config = transformers.GPT2Config(n_layer=1, n_embd=8, n_head=2, vocab_size=16)
    transformers.GPT2LMHeadModel(config).save_pretrained(tmp_path)
    model = transformers.GPT2LMHeadModel.from_pretrained(
        tmp_path, device_map={"": "cpu"}
    )
    assert str(model.device) == "cpu"
