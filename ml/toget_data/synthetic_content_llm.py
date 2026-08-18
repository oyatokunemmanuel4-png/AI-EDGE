"""LLM-backed synthetic governance-document generation (Phase 2 dataset).

Produces far more diverse, realistic labelled documents than the template
generator by prompting an LLM across varied diversity axes (industry, document
type, tone, length) with a share of deliberately ambiguous "hard" cases. The
pure helpers here — diversity sampling, prompt building, dedup, record building
— are unit-testable without any API key; the async orchestration that actually
calls the Anthropic API lives in scripts/generate_content_llm.py.

Design notes (see docs/phase2.md):
- Diversity axes are sampled per call so the corpus doesn't mode-collapse.
- ``hard_fraction`` of calls request ambiguous docs (dominant class + a
  distractor theme) so the RoBERTa vs DeBERTa-v3 bake-off is non-trivial.
- Dedup drops exact-normalised duplicates and near-duplicate openings (LLMs
  repeat themselves).
- Test split is generated with different seeds/axes and de-duplicated against
  train so metrics aren't inflated by train/test leakage.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Iterable
from dataclasses import dataclass

from toget_data.synthetic_content import LABELS  # reuse the 5-class label set

INDUSTRIES = (
    "healthcare", "banking", "government", "retail", "manufacturing",
    "education", "technology", "energy", "legal services", "logistics",
)
DOC_TYPES = (
    "email", "internal memo", "policy document", "report", "support ticket",
    "meeting notes", "invoice", "press release", "contract clause",
    "spreadsheet summary", "chat transcript", "intake form",
)
TONES = ("formal", "casual", "terse", "verbose", "technical", "non-native English")
LENGTHS = ("one sentence", "two to three sentences", "a short paragraph", "two short paragraphs")

CLASS_GUIDANCE = {
    "PII": "personal data about identifiable individuals (names, addresses, IDs, health, contact details)",
    "financial": "financial or accounting content (revenue, budgets, invoices, banking, payroll, forecasts)",
    "policy": "governance, compliance, or policy content (data policies, GDPR/ISO 27001, procedures, standards)",
    "internal": "internal operational content not sensitive on its own (project notes, roadmaps, wikis, memos)",
    "public": "content intended for public release (press releases, marketing, published FAQs, website copy)",
}


@dataclass(frozen=True)
class GenSpec:
    """One generation call's parameters."""

    label: str
    industry: str
    doc_type: str
    tone: str
    length: str
    hard: bool
    count: int


def plan_specs(
    total: int,
    *,
    per_call: int = 10,
    hard_fraction: float = 0.3,
    seed: int = 740,
) -> list[GenSpec]:
    """Balanced generation plan across classes and diversity axes."""
    if total <= 0:
        return []
    rng = random.Random(seed)
    per_label = max(total // len(LABELS), 1)

    specs: list[GenSpec] = []
    for label in LABELS:
        remaining = per_label
        while remaining > 0:
            n = min(per_call, remaining)
            specs.append(
                GenSpec(
                    label=label,
                    industry=rng.choice(INDUSTRIES),
                    doc_type=rng.choice(DOC_TYPES),
                    tone=rng.choice(TONES),
                    length=rng.choice(LENGTHS),
                    hard=rng.random() < hard_fraction,
                    count=n,
                )
            )
            remaining -= n
    rng.shuffle(specs)
    return specs


def build_prompt(spec: GenSpec) -> str:
    """User prompt for one generation call. Returns instructions; the model
    replies with JSON per the structured-output schema."""
    other = ", ".join(lab for lab in LABELS if lab != spec.label)
    hard_clause = (
        f" Make each document ambiguous: weave in some content that could plausibly be "
        f"mistaken for another category ({other}), while the DOMINANT theme stays "
        f"clearly '{spec.label}'."
        if spec.hard
        else ""
    )
    return (
        f"Generate {spec.count} distinct, realistic enterprise documents for a "
        f"{spec.industry} organisation. Each should read like a real {spec.doc_type} "
        f"written in a {spec.tone} tone, about {spec.length} long. "
        f"Every document must be an example of the governance category '{spec.label}': "
        f"{CLASS_GUIDANCE[spec.label]}.{hard_clause} "
        f"Use realistic but entirely fictional names, numbers, and identifiers. "
        f"Return plain text only (no markdown, no headings). Vary wording, structure, "
        f"and specifics across the documents so they are not near-duplicates."
    )


# JSON schema for structured outputs (see scripts/generate_content_llm.py).
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        }
    },
    "required": ["documents"],
}

SYSTEM_PROMPT = (
    "You synthesize realistic, fictional enterprise documents for training a "
    "governance-document classifier. Output only via the required JSON schema."
)


# --- Post-processing (pure, testable) ---------------------------------------

_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]+")


def _normalise(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def _opening_signature(text: str, words: int = 10) -> str:
    # Punctuation-insensitive so a stray comma can't defeat near-dup detection.
    stripped = _NON_WORD.sub(" ", _normalise(text))
    tokens = _WS.sub(" ", stripped).split()[:words]
    return hashlib.sha1(" ".join(tokens).encode("utf-8")).hexdigest()


def dedupe(texts: Iterable[str], *, seen_norm: set[str] | None = None,
           seen_sig: set[str] | None = None) -> list[str]:
    """Drop exact-normalised duplicates and near-duplicate openings.

    Pass shared ``seen_norm`` / ``seen_sig`` sets to also dedupe across splits
    (e.g. remove test docs that collide with train).
    """
    seen_norm = seen_norm if seen_norm is not None else set()
    seen_sig = seen_sig if seen_sig is not None else set()
    out: list[str] = []
    for text in texts:
        norm = _normalise(text)
        if not norm:
            continue
        sig = _opening_signature(text)
        if norm in seen_norm or sig in seen_sig:
            continue
        seen_norm.add(norm)
        seen_sig.add(sig)
        out.append(text.strip())
    return out


def build_records(labelled: list[tuple[str, str]], *, seed_tag: str) -> list[dict[str, str]]:
    """Turn (label, text) pairs into the JSONL record shape the trainer consumes."""
    records = []
    for i, (label, text) in enumerate(labelled):
        records.append({"document_id": f"llm-{seed_tag}-{i:06d}", "text": text, "label": label})
    return records
