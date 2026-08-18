"""Fine-tune + evaluate one content classifier (RoBERTa or DeBERTa-v3).

Portable: runs on a RunPod GPU or locally on CPU (Trainer auto-detects CUDA).
Run once per model for the bake-off, then compare metrics.json files.

Usage:
  python training/train_classifier.py --model roberta-base --out models/nlp/roberta
  python training/train_classifier.py --model microsoft/deberta-v3-base --out models/nlp/deberta-v3
Options: --epochs --batch-size --max-len --max-train --max-eval (subset for smoke tests)

Saves to --out: the HF model + tokenizer, label_map.json, metrics.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from ml.toget_data.synthetic_content import LABELS

REPO = Path(__file__).resolve().parents[2]  # ml/training/x.py -> repo root (data/, models/)
LABEL2ID = {label: i for i, label in enumerate(LABELS)}
ID2LABEL = {i: label for label, i in LABEL2ID.items()}


def _load(path: Path, limit: int | None):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit:
        rows = rows[:limit]
    texts = [r["text"] for r in rows]
    labels = [LABEL2ID[r["label"]] for r in rows]
    return texts, labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HF model id (e.g. roberta-base, microsoft/deberta-v3-base)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--train", default=str(REPO / "data/raw/content/generated_train.jsonl"))
    ap.add_argument("--test", default=str(REPO / "data/raw/content/generated_test.jsonl"))
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--max-train", type=int, default=None)
    ap.add_argument("--max-eval", type=int, default=None)
    args = ap.parse_args()

    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    train_texts, train_labels = _load(Path(args.train), args.max_train)
    eval_texts, eval_labels = _load(Path(args.test), args.max_eval)
    print(f"model={args.model} device={'cuda' if torch.cuda.is_available() else 'cpu'} "
          f"train={len(train_texts)} eval={len(eval_texts)}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=len(LABELS), id2label=ID2LABEL, label2id=LABEL2ID
    )

    def encode(texts):
        return tokenizer(texts, truncation=True, max_length=args.max_len)

    class DS(torch.utils.data.Dataset):
        def __init__(self, texts, labels):
            self.enc = encode(texts)
            self.labels = labels

        def __len__(self):
            return len(self.labels)

        def __getitem__(self, i):
            item = {k: torch.tensor(v[i]) for k, v in self.enc.items()}
            item["labels"] = torch.tensor(self.labels[i])
            return item

    train_ds, eval_ds = DS(train_texts, train_labels), DS(eval_texts, eval_labels)

    targs = TrainingArguments(
        output_dir=str(out / "_trainer"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=2e-5,
        logging_steps=50,
        save_strategy="no",
        report_to=[],
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train_ds,
        data_collator=DataCollatorWithPadding(tokenizer),
    )
    trainer.train()

    # Manual evaluation (version-robust; avoids eval-strategy naming differences).
    preds_output = trainer.predict(eval_ds)
    y_pred = np.argmax(preds_output.predictions, axis=1)
    y_true = np.array(eval_labels)

    p, r, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="macro", zero_division=0
    )
    per_class = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(len(LABELS))), zero_division=0
    )
    metrics = {
        "model": args.model,
        "eval_count": len(eval_labels),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_precision": round(float(p), 4),
        "macro_recall": round(float(r), 4),
        "macro_f1": round(float(f1), 4),
        "per_class_f1": {LABELS[i]: round(float(per_class[2][i]), 4) for i in range(len(LABELS))},
    }

    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    (out / "label_map.json").write_text(json.dumps({"id2label": ID2LABEL, "label2id": LABEL2ID}), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(json.dumps(metrics, indent=2))
    print(f"\nsaved model + metrics to {out}")


if __name__ == "__main__":
    main()
