"""Label fields of the combined catalog and their editable vocabulary.

The seed reflects the taxonomy agreed on 2026-11-07. The vocabulary file in the
dataset is the source of truth afterwards; values are added or removed there.
"""

import re

LABELS = ("benign", "injection", "jailbreak")

SEED = {
    "label": {
        "multiple": False,
        "applies_to": list(LABELS),
        "values": {
            "benign": "No instruction aimed at changing an AI system's behavior.",
            "injection": "Instruction meant to make an AI system deviate from the "
            "user's or operator's task.",
            "jailbreak": "Tries to get disallowed content past safety policies "
            "without hijacking someone else's task.",
        },
    },
    "techniques": {
        "multiple": True,
        "applies_to": ["injection", "jailbreak"],
        "values": {
            "instruction_override": "Tells the model to ignore or replace prior "
            "instructions.",
            "task_redirection": "Steers the model to another task or output than "
            "requested.",
            "forged_authority": "Impersonates a trusted person, team or system.",
            "contextual_camouflage": "Hidden in plausible content: website, email, "
            "chat, code, docs.",
            "step_by_step_elicitation": "Asks for stepwise instructions, typically "
            "as a list to complete.",
        },
    },
    "goal": {
        "multiple": True,
        "applies_to": ["injection"],
        "values": {
            "data_exfiltration": "Reveal or send files, secrets, personal data or "
            "instructions.",
            "unauthorized_action": "Act beyond the task: submit, delete, edit, "
            "forward, use tools.",
            "code_execution": "Run commands or scripts, install or trust packages.",
            "output_manipulation": "Wrong answer or verdict, suppressed finding, "
            "misleading the human.",
            "persistence": "Store instructions for later turns or other agents.",
        },
    },
    "obfuscation": {
        "multiple": True,
        "applies_to": list(LABELS),
        "values": {
            "low_contrast": "Text close to the background color.",
            "small_font": "Text deliberately small.",
            "high_transparency": "Text with high transparency.",
            "blur": "Blurred text.",
            "italic_font": "Slanted or italic glyphs.",
            "distorted_text": "Warped or noisy glyphs.",
            "rotated_text": "Text rotated.",
            "mirrored_text": "Text mirrored.",
            "image_scaling": "Readable only after downscaling.",
            "base64": "Payload encoded as Base64.",
            "unicode_homoglyphs": "Lookalike characters from other scripts.",
            "split_text": "Payload split across separate regions.",
            "flowchart": "Payload spread over a diagram.",
        },
    },
    "evidence": {
        "multiple": True,
        "applies_to": ["injection", "jailbreak"],
        "values": {
            "text": "The instruction can be read as text.",
            "visual_context": "Its meaning depends on the image: UI mimicry, "
            "arrows, placement, pictures.",
            "encoded": "Requires decoding (Base64, QR, LSB).",
            "image_only": "No readable instruction text; conveyed visually.",
        },
    },
    "content": {
        "multiple": False,
        "applies_to": list(LABELS),
        "values": {
            "web_page": "Website or web app page: shop, booking, trust center.",
            "email": "Email message or inbox.",
            "chat": "Messenger or assistant conversation.",
            "form": "Form or checklist to fill in or confirm.",
            "document": "Invoice, ticket, report, notebook, manifest, receipt.",
            "code": "Source file, README, config or diff.",
            "terminal": "Command-line output or logs.",
            "dashboard": "Metrics, monitoring or status view.",
            "diagram": "Flowchart, architecture board or whiteboard.",
            "illustration": "Designed visual scene, infographic or technical illustration.",
            "desktop": "Desktop application or local agent workspace screenshot.",
            "poster": "Operational announcement or campaign poster.",
            "text_image": "Text rendered as the main content, no interface.",
            "real_world": "Photo of signs, products, objects or scenes with text.",
        },
    },
}
FIELDS = tuple(SEED)


def seed():
    """Return a fresh, independent copy of the seed vocabulary."""
    return {
        "version": 1,
        "fields": {
            name: {
                "multiple": spec["multiple"],
                "applies_to": list(spec["applies_to"]),
                "values": [
                    {"value": value, "description": description}
                    for value, description in spec["values"].items()
                ],
            }
            for name, spec in SEED.items()
        },
    }


def normalize(value):
    """Lowercase and join words with underscores: 'Low-Contrast' -> 'low_contrast'."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def allowed(vocabulary, field):
    return {item["value"] for item in vocabulary["fields"][field]["values"]}


def near_duplicates(vocabulary, field, candidate):
    """Existing values that normalize to the same spelling as ``candidate``."""
    target = normalize(candidate).replace("_", "")
    return sorted(
        value
        for value in allowed(vocabulary, field)
        if normalize(value).replace("_", "") == target
    )
