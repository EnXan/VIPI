"""LightOnOCR-3 through its official Transformers classes and image-only prompt."""

from importlib.metadata import version
from pathlib import Path


class LightOnEngine:
    def __init__(self, model, directory):
        import torch
        from transformers import (
            AutoProcessor,
            LightOnOcrForConditionalGeneration,
            LightOnOcrProcessor,
            Qwen3_5ForConditionalGeneration,
        )

        self.id = model
        self.device = (
            "mps"
            if torch.backends.mps.is_available()
            else "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )
        self.dtype = (
            torch.float32
            if model.endswith("-1b") and self.device == "mps"
            else torch.bfloat16
            if self.device != "cpu"
            else torch.float32
        )
        path = Path(directory) / "candidates" / model
        # PyTorch 2.6 MPS SDPA rejects these grouped-attention tensor shapes.
        self.attention = "eager" if self.device == "mps" else "sdpa"
        model_class = (
            LightOnOcrForConditionalGeneration
            if model.endswith("-1b")
            else Qwen3_5ForConditionalGeneration
        )
        processor_class = (
            LightOnOcrProcessor if model.endswith("-1b") else AutoProcessor
        )
        self.model = (
            model_class.from_pretrained(
                path,
                dtype=self.dtype,
                local_files_only=True,
                attn_implementation=self.attention,
            )
            .to(self.device)
            .eval()
        )
        self.processor = processor_class.from_pretrained(path, local_files_only=True)

    def recognize(self, image):
        import torch

        kwargs = {} if self.id.endswith("-1b") else {"enable_thinking": False}
        inputs = self.processor.apply_chat_template(
            [{"role": "user", "content": [{"type": "image", "image": image}]}],
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            **kwargs,
        )
        inputs = {
            key: value.to(device=self.device, dtype=self.dtype)
            if value.is_floating_point()
            else value.to(self.device)
            for key, value in inputs.items()
        }
        input_count = inputs["input_ids"].shape[1]
        capacity = self.model.config.text_config.max_position_embeddings
        budget = capacity - input_count
        if budget <= 0:
            raise ValueError("Image prompt exceeds the model's context capacity.")
        with torch.inference_mode():
            result = self.model.generate(**inputs, max_new_tokens=budget)
        generated = result[0, input_count:]
        text = self.processor.decode(generated, skip_special_tokens=True)
        eos = self.model.generation_config.eos_token_id
        ended = bool(len(generated)) and int(generated[-1]) in (
            eos if isinstance(eos, list) else [eos]
        )
        return {
            "text": text,
            "regions": [],
            "full_page_text": True,
            "preprocessing": {
                "model": self.id,
                "pipeline": "official Transformers image-only transcription",
                "backend": self.device,
                "dtype": str(self.dtype),
                "attention_implementation": self.attention,
                "prompt": "",
                "max_new_tokens": budget,
                "limit_basis": "remaining model context capacity",
                "finish_reason": "eos" if ended else "context_limit",
                "output_tokens": len(generated),
                "package_versions": {
                    name: version(name) for name in ("torch", "transformers")
                },
            },
        }
