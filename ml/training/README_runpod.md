# Phase 2 classifier bake-off on RunPod (GPU)

Fine-tuning the encoders (RoBERTa, DeBERTa-v3) is the only GPU-worthy step. Each
run is minutes on a single 24 GB GPU. Everything else (data gen, inference,
Phase 3) runs on CPU.

## 1. Create the pod
- GPU: any 24 GB card (RTX 4090 / A5000 / L4). 16 GB also works with
  `--batch-size 8`.
- Template: an official **PyTorch** image (ships CUDA-enabled torch), e.g.
  `runpod/pytorch:2.x-cuda12.x`.
- Disk: 20 GB is plenty.

## 2. Get the code + data
```bash
git clone https://github.com/CognizanterGroup/Data-governance.git
cd Data-governance
pip install -e .                                  # aiedge package (for imports)
pip install -r training/requirements-train.txt    # transformers, datasets, etc.

# Get the datasets on the pod (not committed). Prefer the LLM generator for the
# real bake-off; the template generator is the offline fallback.
#
# Option A (preferred) — LLM-generated (needs ANTHROPIC_API_KEY + the llm extra):
pip install -e ".[llm]"
python scripts/generate_content_llm.py --count 3000 --seed 42 --out data/raw/content/generated_train.jsonl
python scripts/generate_content_llm.py --count 750  --seed 7  --out data/raw/content/generated_test.jsonl \
    --dedupe-against data/raw/content/generated_train.jsonl
#
# Option B (fallback) — deterministic templates, no API key:
python scripts/generate_content_docs.py --count 3000 --seed 42 --output data/raw/content/generated_train.jsonl
python scripts/generate_content_docs.py --count 750  --seed 7  --output data/raw/content/generated_test.jsonl
```

## 3. Run the bake-off (both models)
```bash
python training/train_classifier.py --model roberta-base            --out models/nlp/roberta      --epochs 3
python training/train_classifier.py --model microsoft/deberta-v3-base --out models/nlp/deberta-v3   --epochs 3
```
Compare `models/nlp/*/metrics.json` (macro-F1, per-class F1, accuracy).

## 4. Bring the winner back
Pick the higher-macro-F1 model and copy its directory back to the workstation
(e.g. `runpodctl send`, `scp`, or push to S3):
```bash
# e.g. upload winner to our processed bucket for retrieval
aws s3 sync models/nlp/deberta-v3 s3://<processed-bucket>/models/classifier/
```
Then locally point the pipeline at it:
```powershell
$env:AIEDGE_CLASSIFIER_MODEL_DIR = "models/nlp/deberta-v3"
```
`aiedge.nlp.classifier.TransformerContentClassifier.load` reads the model +
`label_map.json`; the pipeline factory picks it up automatically.

## Notes
- The training script auto-detects CUDA; identical command runs on CPU (slow).
- DeBERTa-v3 needs `sentencepiece` + `protobuf` (in requirements-train.txt).
