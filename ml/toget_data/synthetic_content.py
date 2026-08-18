"""Synthetic labelled governance-document generator for the Phase 2 classifier.

Produces documents across the five governance classes (PII, financial, policy,
internal, public). Each document mixes class-specific sentences with occasional
shared/generic sentences, so no single keyword trivially separates the classes
(the classifier must learn distributed patterns). Deterministic given a seed.

Real enterprise documents would replace this; it exists so the RoBERTa vs
DeBERTa-v3 bake-off has labelled data to train and evaluate on.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

LABELS = ("PII", "financial", "policy", "internal", "public")

# Class-specific sentence templates with {slot} variety.
_TEMPLATES: dict[str, list[str]] = {
    "PII": [
        "Employee record for {person} lists home address, {gov_id}, and next-of-kin contact.",
        "The onboarding form captured {person}'s date of birth, personal phone number and bank account.",
        "Patient {person} medical history and insurance identifiers are attached for review.",
        "This dataset contains customer names, email addresses and {gov_id} for {count} individuals.",
        "Please redact {person}'s passport number and residential address before sharing.",
    ],
    "financial": [
        "The Q{q} revenue forecast assumes a {pct}% margin and includes budget variance notes.",
        "Invoice {num} from {vendor} covers accounts payable and banking settlement details.",
        "Quarterly results show EBITDA, cash flow and the reconciled general ledger balances.",
        "The pricing model spreadsheet contains cost of goods, discounts and profit projections.",
        "Payroll run for period {q} totals salary, bonus and tax withholding figures.",
    ],
    "policy": [
        "This data governance policy defines retention schedules and access control under {std}.",
        "The acceptable use procedure mandates {std} compliance and annual staff attestation.",
        "Section {num} of the information security charter sets breach-notification requirements.",
        "The records management standard specifies classification, handling and disposal rules.",
        "Per {std}, data subject access requests must be fulfilled within the stated timeframe.",
    ],
    "internal": [
        "Meeting notes from the {team} sync outline the sprint roadmap and open action items.",
        "The internal project plan for {project} lists milestones, owners and target dates.",
        "This wiki page documents the deployment runbook for the {team} service.",
        "Internal announcement: the {team} team will migrate tooling next {q}.",
        "Draft roadmap for {project} shared for internal feedback before the review.",
    ],
    "public": [
        "Press release: the company today announced the public launch of {project}.",
        "Our published blog post explains how customers can get started with {project}.",
        "The marketing brochure highlights product benefits for prospective customers.",
        "This is the public FAQ answering common questions about {project} availability.",
        "Website copy describing our mission, values and openly shared roadmap.",
    ],
}

# Generic sentences that appear in any class (adds realistic noise / overlap).
_GENERIC = [
    "This document was last reviewed by the data owner.",
    "Distribution is subject to the organisation's handling guidelines.",
    "Refer to the appendix for version history and change log.",
    "Contact the governance office with any questions about this material.",
]

_PERSONS = ["Jane Doe", "John Smith", "Maria Garcia", "Wei Chen", "Amina Bello", "Tom Lee"]
_GOV_IDS = ["national insurance number", "social security number", "passport number", "tax ID"]
_VENDORS = ["Acme Ltd", "Globex", "Initech", "Umbrella Corp", "Soylent Inc"]
_STDS = ["GDPR", "ISO 27001", "the Data Protection Act", "SOC 2"]
_TEAMS = ["platform", "data", "security", "finance-ops", "sales-eng"]
_PROJECTS = ["Project Atlas", "Project Beacon", "the analytics portal", "the mobile app"]


@dataclass(frozen=True)
class ContentDocument:
    document_id: str
    text: str
    label: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def _fill(rng: random.Random, template: str) -> str:
    return template.format(
        person=rng.choice(_PERSONS),
        gov_id=rng.choice(_GOV_IDS),
        vendor=rng.choice(_VENDORS),
        std=rng.choice(_STDS),
        team=rng.choice(_TEAMS),
        project=rng.choice(_PROJECTS),
        q=rng.randint(1, 4),
        pct=rng.randint(5, 45),
        num=rng.randint(100, 999),
        count=rng.choice([50, 120, 500, 1000, 2500]),
    )


def generate_content_documents(
    count: int, *, seed: int = 740, generic_rate: float = 0.45, hard_rate: float = 0.35
) -> list[ContentDocument]:
    """Generate balanced labelled documents.

    ``generic_rate``: chance of inserting a class-neutral sentence (noise).
    ``hard_rate``: chance of inserting one *distractor* sentence drawn from a
    different class, so the label remains the majority signal but the document is
    ambiguous. Both keep the benchmark non-trivial (so RoBERTa vs DeBERTa-v3 are
    actually distinguishable).
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    rng = random.Random(seed)

    docs: list[ContentDocument] = []
    for index in range(count):
        label = LABELS[index % len(LABELS)]  # balanced classes
        n_sentences = rng.randint(2, 4)
        sentences = [_fill(rng, rng.choice(_TEMPLATES[label])) for _ in range(n_sentences)]
        if rng.random() < hard_rate:
            other = rng.choice([lab for lab in LABELS if lab != label])
            sentences.append(_fill(rng, rng.choice(_TEMPLATES[other])))  # distractor (minority)
        if rng.random() < generic_rate:
            sentences.insert(rng.randint(0, len(sentences)), rng.choice(_GENERIC))
        rng.shuffle(sentences)
        docs.append(
            ContentDocument(
                document_id=f"doc-{seed}-{index:05d}",
                text=" ".join(sentences),
                label=label,
            )
        )
    return docs


def write_jsonl(docs: Iterable[ContentDocument], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for doc in docs:
            handle.write(doc.to_json())
            handle.write("\n")
    return path
