"""Normalize source-backed image typography hints for the shared catalog."""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "1.4.0"


IMAGE_CONTEXT = {
    "text_only": "plain_background",
    "overlay_on_scene": "photographic_scene",
    "captcha_on_scene": "photographic_scene",
    "rendered_text_below_scene": "composite_scene",
    "email_inbox": "interface_screenshot",
    "messenger_chat": "interface_screenshot",
    "webpage_popup": "interface_screenshot",
}
TEXT_PLACEMENT = {
    "text_only": "standalone",
    "overlay_on_scene": "overlay",
    "captcha_on_scene": "overlay",
    "rendered_text_below_scene": "below_scene_panel",
    "email_inbox": "ui_element",
    "messenger_chat": "ui_element",
    "webpage_popup": "ui_element",
}
TEXT_LAYOUT = {
    "overlay": "multiline",
    "numbered_list": "list",
    "captcha": "captcha",
    "wrapped_phrase": "multiline",
    "bottom_text_panel": "multiline",
    "split_text_fragment": "fragment",
    "wrapped_paragraph": "paragraph",
    "modal_overlay_description": "paragraph",
    "selected_email_body": "paragraph",
    "selected_chat_message": "multiline",
}
RENDERING_METHOD = {
    "synthetic": "synthetic_generation",
    "rendered": "programmatic_render",
    "rendered_typography": "programmatic_render",
    "live_webpage_screenshot": "web_screenshot",
}
OCR_CHALLENGE = {
    "low_contrast": "low_contrast",
    "oblique_font": "oblique_text",
    "fragmented_text": "fragmented_text",
    "wrapped_text": "wrapped_text",
    "obfuscated": "visual_distortion",
}

RISK_CATEGORY_ALIASES = {
    "01-illegal_activitiy": "illegal_activity",
    "illegal activity": "illegal_activity",
    "illegal_activity": "illegal_activity",
    "02-hatespeech": "hate_speech",
    "hate speech": "hate_speech",
    "hate_speech": "hate_speech",
    "03-malware_generation": "malware_generation",
    "malware generation": "malware_generation",
    "malware_generation": "malware_generation",
    "04-physical_harm": "physical_harm",
    "physical harm": "physical_harm",
    "physical_harm": "physical_harm",
    "05-economicharm": "economic_harm",
    "economic harm": "economic_harm",
    "economic_harm": "economic_harm",
    "06-fraud": "fraud",
    "fraud": "fraud",
    "07-sex": "adult_content",
    "adult content": "adult_content",
    "adult_content": "adult_content",
    "08-political_lobbying": "political_lobbying",
    "political lobbying": "political_lobbying",
    "political_lobbying": "political_lobbying",
    "09-privacy_violence": "privacy_violation",
    "privacy violation": "privacy_violation",
    "privacy_violation": "privacy_violation",
    "data privacy": "privacy_violation",
    "data_privacy": "privacy_violation",
    "10-legal_opinion": "legal_opinion",
    "legal opinion": "legal_opinion",
    "legal_opinion": "legal_opinion",
    "11-financial_advice": "financial_advice",
    "financial advice": "financial_advice",
    "financial_advice": "financial_advice",
    "12-health_consultation": "health_consultation",
    "health consultation": "health_consultation",
    "health_consultation": "health_consultation",
    "13-gov_decision": "government_decision",
    "government decision": "government_decision",
    "government_decision": "government_decision",
    "content policy": "content_policy",
    "content_policy": "content_policy",
    "system bypass": "system_bypass",
    "system_bypass": "system_bypass",
    "logic-violating": "logic_violating",
    "logic_violating": "logic_violating",
    "security-violating": "security_violating",
    "security_violating": "security_violating",
}

SPLIT_ALIASES = {
    "train": "train",
    "training": "train",
    "val": "validation",
    "valid": "validation",
    "validation": "validation",
    "test": "test",
    "eval": "test",
    "evaluation": "test",
}


def _evidence(kind: str, *paths: str) -> list[dict[str, str]]:
    return [{"kind": kind, "path": path} for path in paths]


def typography_for_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the same typography fields for every image, leaving unknowns null."""
    specific = record.get("source_specific", {})
    dataset_id = record.get("source", {}).get("dataset_id")
    typography: dict[str, Any] = {
        "font_family_candidates": [],
        "font_family_resolved": None,
        "font_family_class": None,
        "font_style": None,
        "font_weight": None,
        "font_size": None,
        "font_size_unit": None,
        "text_color_rgb": None,
        "background_color_rgb": None,
        "padding_px": None,
        "text_origin_xy_px": None,
        "line_spacing_px": None,
        "metadata_status": "not_found_in_source",
        "evidence": [],
    }

    if dataset_id == "typographic_visual_prompt_injection":
        declared_style = specific.get("declared_font_style")
        typography.update({
            "font_family_class": "sans-serif" if declared_style == "sans_serif" else None,
            "font_style": "oblique" if declared_style == "oblique" else None,
            "font_size": specific.get("declared_font_size_pt"),
            "font_size_unit": "pt" if specific.get("declared_font_size_pt") is not None else None,
            "text_color_rgb": specific.get("declared_text_color_rgb"),
            "background_color_rgb": specific.get("declared_background_rgb"),
            "padding_px": specific.get("declared_padding_px"),
            "metadata_status": "style_and_layout_only",
            "evidence": _evidence(
                "dataset_readme",
                "research/datasets/data/external/Dagger7164/VisualPromptInjection/README.md",
            ),
        })
    elif dataset_id == "figstep" or str(record.get("sample_id", "")).startswith("figstep_pro:"):
        is_fragment = str(record.get("sample_id", "")).startswith("figstep_pro:")
        typography.update({
            "font_family_candidates": ["FreeMonoBold"],
            "font_weight": "bold",
            "font_size": 80,
            "font_size_unit": "px",
            "text_color_rgb": [0, 0, 0],
            "background_color_rgb": [255, 255, 255],
            "text_origin_xy_px": [20, 10],
            "line_spacing_px": 11,
            "metadata_status": "inherited_renderer" if is_fragment else "renderer_declared",
            "evidence": _evidence(
                "generator_code",
                "research/datasets/data/external/FigStep/src/generate_prompts.py",
                *( ["research/datasets/data/external/FigStep/README.md"] if is_fragment else [] ),
            ),
        })
    elif dataset_id == "mm_safetybench":
        typography.update({
            "font_family_candidates": ["Arial"],
            "font_family_resolved": "Arial",
            "font_weight": "regular",
            "font_size": 90,
            "font_size_unit": "px",
            "text_color_rgb": [0, 0, 0],
            "background_color_rgb": [255, 255, 255],
            "text_origin_xy_px": [0, 45],
            "metadata_status": "generator_and_font_asset",
            "evidence": _evidence(
                "generator_code",
                "research/datasets/data/external/MM-SafetyBench/creation/2_img_process.py",
            ) + _evidence(
                "bundled_font_asset",
                "research/datasets/data/external/MM-SafetyBench/assets/font/ARIAL.TTF",
            ),
        })
    elif dataset_id == "vpi_bench":
        platform = specific.get("platform")
        # Keep named CSS-stack families as source candidates but drop the generic
        # sans-serif token. Effective Segoe UI was explicitly confirmed by the user.
        css_by_platform = {
            # Popup descriptions use clamp(0.9em, 1vw, 1.1em): at the 1015px
            # capture viewport the lower bound (14.4px) wins over 1vw (10.15px).
            "amazon": (["Arial"], "Arial", "research/datasets/data/external/VPI-Bench/vpi-bench/web_platforms/amazon/style.css", 14.4),
            "booking": (["Arial"], "Arial", "research/datasets/data/external/VPI-Bench/vpi-bench/web_platforms/booking/style.css", 14.4),
            # Email body and chat bubbles inherit the browser's 16px default size.
            "email": (["Segoe UI"], "Segoe UI", "research/datasets/data/external/VPI-Bench/vpi-bench/web_platforms/email/index.html", 16),
            "messenger": (["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "Helvetica", "Arial"], "Segoe UI", "research/datasets/data/external/VPI-Bench/vpi-bench/web_platforms/messenger/index.html", 16),
        }
        declared = css_by_platform.get(platform)
        if declared:
            candidates, resolved_family, evidence_path, font_size = declared
            dark_text = platform in {"email", "messenger"}
            typography.update({
                "font_family_candidates": candidates,
                "font_family_resolved": resolved_family,
                "font_family_class": "sans-serif",
                "font_style": "normal",
                "font_weight": "regular",
                "font_size": font_size,
                "font_size_unit": "px",
                "text_color_rgb": [0, 0, 0] if dark_text else [55, 70, 171],
                "background_color_rgb": [255, 255, 255],
                "metadata_status": "manually_annotated",
                "evidence": _evidence("css_declaration", evidence_path),
            })

    return typography


def standardize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a catalog record with normalized shared metadata vocabularies."""
    normalized = dict(record)
    normalized["schema_version"] = SCHEMA_VERSION
    # Preserve heterogeneous upstream annotations in source shards only. The
    # aggregate catalog exposes the shared OCR vocabulary below instead.
    normalized.pop("source_specific", None)
    source_visual = record["visual"]
    legacy_scene = source_visual.get("scene_type", "unknown")
    visual = {
        key: value for key, value in source_visual.items()
        if key not in {"scene_type", "generation_type", "challenge_tags"}
    }
    visual["image_context"] = source_visual.get(
        "image_context", IMAGE_CONTEXT.get(legacy_scene, "unknown")
    )
    visual["text_placement"] = source_visual.get(
        "text_placement", TEXT_PLACEMENT.get(legacy_scene, "unknown")
    )
    legacy_layout = source_visual.get("text_layout", "unknown")
    visual["text_layout"] = TEXT_LAYOUT.get(legacy_layout, legacy_layout)
    legacy_rendering = source_visual.get("generation_type", "unknown")
    visual["rendering_method"] = source_visual.get(
        "rendering_method", RENDERING_METHOD.get(legacy_rendering, "unknown")
    )
    visual["ocr_challenges"] = sorted(set(source_visual.get(
        "ocr_challenges",
        [OCR_CHALLENGE[tag] for tag in source_visual.get("challenge_tags", []) if tag in OCR_CHALLENGE],
    )))
    if record.get("source", {}).get("dataset_id") == "vpi_bench":
        visual["ocr_challenges"] = ["wrapped_text"]
    measurements = {
        "text_height_px": None,
        "text_height_ratio": None,
        "opacity": None,
        "contrast_ratio": None,
        "basis": "unknown",
    }
    measurements.update(source_visual.get("text_measurements", {}))
    visual["text_measurements"] = measurements
    normalized["visual"] = visual
    typography = typography_for_record(record)
    typography.update(source_visual.get("typography", {}))
    if record.get("source", {}).get("dataset_id") == "cyberseceval3_visual_prompt_injection":
        # User-requested dataset-level annotation: the rendered typeface was
        # not identified from source assets. Keep CAPTCHA font fields N/A.
        if visual["text_layout"] == "captcha":
            typography.update({
                "font_family_candidates": [],
                "font_family_resolved": None,
                "font_family_class": None,
                "font_style": None,
                "font_weight": None,
                "metadata_status": "not_applicable",
            })
        else:
            typography.update({
                "font_family_candidates": ["Noto Sans"],
                "font_family_resolved": "Noto Sans",
                "font_family_class": "sans-serif",
                "font_style": "normal",
                "font_weight": "regular",
                "metadata_status": "manually_annotated",
            })
    normalized["visual"]["typography"] = typography

    source = dict(record.get("source", {}))
    split = source.get("split")
    source["split"] = SPLIT_ALIASES.get(str(split).strip().lower()) if split is not None else None
    source.pop("license_spdx", None)
    normalized["source"] = source

    group = dict(record.get("group", {}))
    group.pop("variant", None)
    normalized["group"] = group

    eligibility = dict(record.get("eligibility", {}))
    eligibility.pop("training", None)
    normalized["eligibility"] = eligibility

    security = dict(record.get("security", {}))
    security["attack_family"] = "visual_prompt_injection"
    injection_type = str(security.get("injection_type") or "").strip().lower().replace(" ", "_")
    security["injection_type"] = (
        "pixel_perturbation" if injection_type in {"pixel_perturbation", "pixel_pertubation"} else "textual"
    )
    risk_category = security.get("risk_category")
    security["risk_category"] = (
        RISK_CATEGORY_ALIASES.get(str(risk_category).strip().lower()) if risk_category is not None else None
    )
    security.pop("contains_injection_instruction", None)
    security.pop("contains_harmful_instruction", None)
    normalized["security"] = security
    normalized.pop("rights", None)
    return normalized
