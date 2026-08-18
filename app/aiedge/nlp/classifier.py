"""TransformerContentClassifier: the real ContentClassifier (Phase 2) behind the port.

Loads a fine-tuned sequence-classification model (RoBERTa or DeBERTa-v3, the
bake-off winner) from a directory produced by training/train_classifier.py and
maps a document's text to a governance class + confidence.

torch/transformers are imported lazily so the package loads without them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiedge.ports import ContentSignal


class TransformerContentClassifier:
    def __init__(self, model: Any, tokenizer: Any, id2label: dict[int, str], max_len: int = 256):
        self._model = model
        self._tokenizer = tokenizer
        self._id2label = id2label
        self._max_len = max_len

    @classmethod
    def load(cls, model_dir: str | Path, *, max_len: int = 256) -> TransformerContentClassifier:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        model_dir = Path(model_dir)
        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        model.eval()

        label_map_path = model_dir / "label_map.json"
        if label_map_path.exists():
            raw = json.loads(label_map_path.read_text(encoding="utf-8"))["id2label"]
            id2label = {int(k): v for k, v in raw.items()}
        else:
            id2label = {int(k): v for k, v in model.config.id2label.items()}
        # torch stays imported for classify()
        cls._torch = torch  # type: ignore[attr-defined]
        return cls(model, tokenizer, id2label, max_len=max_len)

    def classify(self, event: dict[str, Any]) -> ContentSignal:
        import torch

        text = event["content"]["text"]
        inputs = self._tokenizer(
            text, truncation=True, max_length=self._max_len, return_tensors="pt"
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        idx = int(torch.argmax(probs).item())
        return ContentSignal(
            content_class=self._id2label[idx],
            content_confidence=round(float(probs[idx].item()), 4),
        )
