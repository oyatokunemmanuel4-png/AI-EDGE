#!/usr/bin/env python3
"""AI-EDGE — one-command client setup.

Single entry point:  python setup/setup.py

Menu:
  1. Run locally with Docker
  2. Run locally with Docker + ML
  3. Deploy/start AI-EDGE on AWS
  4. Stop AWS
  5. Exit

AWS credentials are read automatically from "aiedge-admin-accessKeys.csv"
(the standard AWS access-keys export). Secrets are never printed, never written
into source/Terraform/.env, and never committed.

Uses only the project's existing implementation:
  - docker-compose.yml services `dashboard` (:8000) and `dashboard-ml` (:8001)
  - infra/docker/Dockerfile.dashboard-aws (real model) / Dockerfile.dashboard (lean)
  - infra/aws/terraform (S3 + Lambda pipeline, ECR repo, EC2 dashboard)
Stdlib only; works on Windows (PowerShell/CMD) and Git Bash/WSL.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------
# Project facts (derived from the existing repo, not invented)
# --------------------------------------------------------------------------
SETUP_DIR = Path(__file__).resolve().parent
ROOT = SETUP_DIR.parent
TF_DIR = ROOT / "infra" / "aws" / "terraform"
MODEL_DIR = ROOT / "models" / "nlp" / "roberta-base"
DOCKERFILE_AWS = "infra/docker/Dockerfile.dashboard-aws"   # real RoBERTa baked in
DOCKERFILE_LEAN = "infra/docker/Dockerfile.dashboard"      # stub classifier, no model

CSV_PRIMARY_NAME = "aiedge-admin-accessKeys.csv"
CSV_FALLBACK_GLOBS = ["*Admin Access*.csv", "*accessKeys*.csv", "credentials.csv"]

LOCAL_URL = "http://localhost:8000"
LOCAL_ML_URL = "http://localhost:8001"
HEALTH_PATH = "/healthz"
AWS_DASH_PORT = 8000
IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------------
# Small output helpers (never print secrets)
# --------------------------------------------------------------------------
def info(msg): print(f"  {msg}")
def ok(msg): print(f"  [ OK ] {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def err(msg): print(f"  [FAIL] {msg}")
def head(msg): print(f"\n=== {msg} ===")


class SetupError(Exception):
    pass


# --------------------------------------------------------------------------
# Command execution
# --------------------------------------------------------------------------
def _resolve(exe: str) -> str:
    path = shutil.which(exe)
    if not path:
        raise SetupError(
            f"'{exe}' was not found on PATH. Please install it and reopen the terminal."
        )
    return path


def run(cmd, cwd=None, env=None, check=True):
    """Run a command, streaming output. cmd[0] is resolved on PATH."""
    cmd = [_resolve(cmd[0])] + list(cmd[1:])
    proc = subprocess.run(cmd, cwd=cwd, env=env)
    if check and proc.returncode != 0:
        raise SetupError(f"command failed ({proc.returncode}): {cmd[0]} {' '.join(cmd[1:])}")
    return proc


def cap(cmd, cwd=None, env=None, check=True, stdin_text=None):
    """Run a command capturing stdout (used for parsing; output not echoed)."""
    cmd = [_resolve(cmd[0])] + list(cmd[1:])
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, input=stdin_text,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if check and proc.returncode != 0:
        raise SetupError(
            f"command failed ({proc.returncode}): {cmd[0]} {' '.join(cmd[1:])}\n{proc.stderr.strip()}"
        )
    return proc


def compose_base():
    """Return the docker compose invocation (v2 `docker compose` or v1 `docker-compose`)."""
    if shutil.which("docker"):
        p = subprocess.run(["docker", "compose", "version"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if p.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise SetupError("Docker Compose not found. Install Docker Desktop (includes Compose).")


def ensure_docker():
    _resolve("docker")
    p = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if p.returncode != 0:
        raise SetupError("Docker Engine is not running. Start Docker Desktop, wait for "
                         "'Engine running', then try again.")
    ok("Docker is installed and the engine is running.")


# --------------------------------------------------------------------------
# Health / URL wait
# --------------------------------------------------------------------------
def http_ok(url: str, timeout=4) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def wait_for(url: str, label: str, timeout=300, interval=6) -> bool:
    info(f"Waiting for {label} to become available ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if http_ok(url):
            ok(f"{label} is up.")
            return True
        time.sleep(interval)
    warn(f"{label} did not respond within {timeout}s. It may still be starting; "
         f"check the URL again shortly.")
    return False


# --------------------------------------------------------------------------
# CSV discovery + parsing (secrets never printed)
# --------------------------------------------------------------------------
def _skip(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return bool(parts & {".venv", "site-packages", "node_modules", ".git"})


def find_csv() -> Path:
    search_roots = [ROOT, SETUP_DIR, Path.cwd()]
    # 1) exact primary name at a search root
    for base in search_roots:
        cand = base / CSV_PRIMARY_NAME
        if cand.is_file():
            return cand
    # 2) exact primary name anywhere under the project
    for match in ROOT.rglob(CSV_PRIMARY_NAME):
        if not _skip(match):
            return match
    # 3) fallback patterns (AWS access-keys exports)
    for pattern in CSV_FALLBACK_GLOBS:
        for match in ROOT.rglob(pattern):
            if not _skip(match):
                return match
    raise SetupError(
        "Could not find the AWS credentials file.\n"
        f"        Please place '{CSV_PRIMARY_NAME}' in the project root:\n"
        f"          {ROOT}\n"
        "        (This is the standard AWS access-keys CSV, with the columns "
        "'Access key ID' and 'Secret access key'.)"
    )


def load_aws_credentials(csv_path: Path) -> dict:
    """Read AWS credentials from the CSV. Returns a dict; values are never printed."""
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SetupError(f"'{csv_path.name}' has no data rows.")
    row = rows[0]
    norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}

    def pick(*needles):
        for key, val in norm.items():
            if all(n in key for n in needles) and val:
                return val
        return ""

    key_id = pick("access", "key", "id")
    secret = pick("secret", "access", "key")
    region = pick("region")  # usually absent in the standard export
    if not key_id or not secret:
        raise SetupError(
            f"'{csv_path.name}' does not contain the expected columns.\n"
            f"        Found columns: {', '.join(row.keys())}\n"
            "        Expected an 'Access key ID' and a 'Secret access key' column."
        )
    return {"access_key_id": key_id, "secret_access_key": secret, "region": region}


# --------------------------------------------------------------------------
# Terraform vars (project_name / environment / aws_region) from tfvars or defaults
# --------------------------------------------------------------------------
def tf_settings() -> dict:
    settings = {"project_name": "aiedge", "environment": "dev", "aws_region": "us-east-1"}
    tfvars = TF_DIR / "terraform.tfvars"
    if tfvars.is_file():
        for line in tfvars.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in settings and v:
                    settings[k] = v
    settings["name_prefix"] = f"{settings['project_name']}-{settings['environment']}"
    settings["ecr_repo"] = f"{settings['name_prefix']}-dashboard"
    settings["ec2_tag_name"] = f"{settings['name_prefix']}-dashboard"
    return settings


def aws_env(creds: dict, region: str) -> dict:
    env = os.environ.copy()
    env.pop("AWS_PROFILE", None)  # ensure the CSV keys are used, not a stray profile
    env["AWS_ACCESS_KEY_ID"] = creds["access_key_id"]
    env["AWS_SECRET_ACCESS_KEY"] = creds["secret_access_key"]
    env["AWS_DEFAULT_REGION"] = region
    env["AWS_REGION"] = region
    return env


# --------------------------------------------------------------------------
# AWS helpers
# --------------------------------------------------------------------------
def aws_identity(env: dict) -> dict:
    p = cap(["aws", "sts", "get-caller-identity", "--output", "json"], env=env)
    return json.loads(p.stdout)


def find_instance(env: dict, tag_name: str, region: str):
    p = cap([
        "aws", "ec2", "describe-instances",
        "--filters", f"Name=tag:Name,Values={tag_name}",
        "Name=instance-state-name,Values=pending,running,stopping,stopped",
        "--query", "Reservations[].Instances[].{id:InstanceId,state:State.Name,"
                   "ip:PublicIpAddress,launch:LaunchTime}",
        "--output", "json", "--region", region,
    ], env=env)
    items = json.loads(p.stdout or "[]")
    if not items:
        return None
    # If more than one instance carries the tag, prefer a running one, then the
    # most recently launched, so start/stop always target the right server.
    items.sort(key=lambda i: (i["state"] == "running", i.get("launch") or ""), reverse=True)
    return items[0]


def instance_public_ip(env: dict, instance_id: str, region: str) -> str:
    p = cap([
        "aws", "ec2", "describe-instances", "--instance-ids", instance_id,
        "--query", "Reservations[0].Instances[0].PublicIpAddress",
        "--output", "text", "--region", region,
    ], env=env)
    ip = p.stdout.strip()
    return "" if ip in ("", "None") else ip


def ecr_has_image(env: dict, repo: str, region: str) -> bool:
    p = cap(["aws", "ecr", "describe-images", "--repository-name", repo,
             "--region", region, "--output", "json"], env=env, check=False)
    if p.returncode != 0:
        return False
    try:
        return bool(json.loads(p.stdout).get("imageDetails"))
    except Exception:
        return False


def build_and_push_image(env: dict, account: str, region: str, repo: str):
    ensure_docker()
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    repo_uri = f"{registry}/{repo}"
    if MODEL_DIR.is_file() or (MODEL_DIR / "model.safetensors").is_file():
        dockerfile = DOCKERFILE_AWS
        info("Model found: building the real-model dashboard image.")
    else:
        dockerfile = DOCKERFILE_LEAN
        warn("Trained model not found; building the lightweight (stub-classifier) image.")

    head("Authenticating Docker to ECR")
    pw = cap(["aws", "ecr", "get-login-password", "--region", region], env=env).stdout.strip()
    # Feed the token via stdin; it is never printed or stored.
    cap(["docker", "login", "--username", "AWS", "--password-stdin", registry],
        stdin_text=pw)
    ok("Docker authenticated to ECR.")

    head("Building the dashboard image (this can take several minutes)")
    run(["docker", "build", "-f", dockerfile, "-t", f"{repo_uri}:latest", "."], cwd=ROOT)
    head("Pushing the image to ECR")
    run(["docker", "push", f"{repo_uri}:latest"])
    ok("Image pushed.")


def terraform(env: dict, args: list, region: str):
    """Run terraform in TF_DIR, using the CSV env credentials.

    Callers pass `-var aws_profile=` on apply/plan so the AWS provider ignores any
    named profile in terraform.tfvars and falls back to the env credentials.
    """
    run(["terraform", "-chdir=" + str(TF_DIR)] + args, env=env)


# --------------------------------------------------------------------------
# Menu actions
# --------------------------------------------------------------------------
def action_local_docker():
    head("Option 1 — Run locally with Docker")
    ensure_docker()
    base = compose_base()
    head("Building and starting the 'dashboard' service")
    run(base + ["up", "-d", "--build", "dashboard"], cwd=ROOT)
    wait_for(LOCAL_URL + HEALTH_PATH, "the dashboard", timeout=240)
    print()
    ok(f"AI-EDGE dashboard is running at:  {LOCAL_URL}")
    info("Upload files from ml/samples/ to try it. Stop later with:  docker compose down")


def action_local_ml():
    head("Option 2 — Run locally with Docker + ML")
    ensure_docker()
    if not (MODEL_DIR / "config.json").is_file() or not (MODEL_DIR / "model.safetensors").is_file():
        raise SetupError(
            "The fine-tuned model was not found.\n"
            f"        Expected: {MODEL_DIR}\\config.json and model.safetensors\n"
            "        Train it (see ml/) or copy the model directory in, then retry. "
            "For a model-free run use Option 1."
        )
    ok("Model directory found.")
    base = compose_base()
    head("Building and starting the 'dashboard-ml' service")
    run(base + ["up", "-d", "--build", "dashboard-ml"], cwd=ROOT)
    wait_for(LOCAL_ML_URL + HEALTH_PATH, "the ML dashboard", timeout=420)
    print()
    ok(f"AI-EDGE ML dashboard is running at:  {LOCAL_ML_URL}")
    info("Stop later with:  docker compose down")


def _load_aws_context():
    csv_path = find_csv()
    ok(f"Using credentials file: {csv_path.name}")
    creds = load_aws_credentials(csv_path)
    cfg = tf_settings()
    region = creds["region"] or cfg["aws_region"]
    env = aws_env(creds, region)
    _resolve("aws")
    ident = aws_identity(env)
    account = ident.get("Account", "")
    arn = ident.get("Arn", "")
    ok(f"Authenticated to AWS account {account} as {arn.split('/')[-1] or arn}")
    return env, cfg, region, account


def action_aws_deploy():
    head("Option 3 — Deploy/start AI-EDGE on AWS")
    env, cfg, region, account = _load_aws_context()
    inst = find_instance(env, cfg["ec2_tag_name"], region)

    if inst is None:
        warn("No existing dashboard server found. Provisioning the infrastructure now.")
        _resolve("terraform")
        head("Initialising Terraform")
        terraform(env, ["init", "-input=false"], region)
        head("Creating the container registry")
        terraform(env, ["apply", "-auto-approve", "-input=false",
                        "-var", "aws_profile=",
                        "-target=aws_ecr_repository.dashboard"], region)
        if not ecr_has_image(env, cfg["ecr_repo"], region):
            build_and_push_image(env, account, region, cfg["ecr_repo"])
        head("Provisioning the pipeline and the dashboard server")
        terraform(env, ["apply", "-auto-approve", "-input=false", "-var", "aws_profile="], region)
        inst = find_instance(env, cfg["ec2_tag_name"], region)
        if inst is None:
            raise SetupError("Terraform completed but no dashboard instance was found.")
    else:
        ok(f"Found dashboard server {inst['id']} (state: {inst['state']}).")
        if not ecr_has_image(env, cfg["ecr_repo"], region):
            warn("The registry has no image; building and pushing it now.")
            build_and_push_image(env, account, region, cfg["ecr_repo"])

    instance_id = inst["id"]
    if inst["state"] != "running":
        head(f"Starting instance {instance_id}")
        cap(["aws", "ec2", "start-instances", "--instance-ids", instance_id,
             "--region", region], env=env)
        info("Waiting for the instance to reach 'running' ...")
        cap(["aws", "ec2", "wait", "instance-running", "--instance-ids", instance_id,
             "--region", region], env=env)
        ok("Instance is running.")
    else:
        ok("Instance is already running.")

    ip = instance_public_ip(env, instance_id, region)
    if not ip:
        raise SetupError("Instance is running but has no public IP yet. Retry Option 3 shortly.")
    url = f"http://{ip}:{AWS_DASH_PORT}"
    info(f"Current public IP: {ip}")
    wait_for(url + HEALTH_PATH, "the AWS dashboard", timeout=360)
    print()
    ok(f"AI-EDGE is live on AWS at:  {url}")
    info("Remember to run Option 4 (Stop AWS) when you are finished, to avoid charges.")


def action_aws_stop():
    head("Option 4 — Stop AWS")
    env, cfg, region, _ = _load_aws_context()
    inst = find_instance(env, cfg["ec2_tag_name"], region)
    if inst is None:
        warn("No dashboard server was found. Nothing to stop.")
        return
    instance_id = inst["id"]
    if inst["state"] == "stopped":
        ok(f"Instance {instance_id} is already stopped.")
        return
    head(f"Stopping instance {instance_id}")
    cap(["aws", "ec2", "stop-instances", "--instance-ids", instance_id,
         "--region", region], env=env)
    info("Waiting for AWS to confirm 'stopped' ...")
    cap(["aws", "ec2", "wait", "instance-stopped", "--instance-ids", instance_id,
         "--region", region], env=env)
    print()
    ok(f"The EC2 instance {instance_id} has been STOPPED. Compute charges have ceased.")
    info("Infrastructure was NOT destroyed. Use Option 3 to start it again later.")


MENU = """
AI-EDGE Setup
=============

1. Run locally with Docker
2. Run locally with Docker + ML
3. Deploy/start AI-EDGE on AWS
4. Stop AWS
5. Exit
"""

ACTIONS = {
    "1": action_local_docker,
    "2": action_local_ml,
    "3": action_aws_deploy,
    "4": action_aws_stop,
}


def main():
    while True:
        print(MENU)
        choice = input("Select an option [1-5]: ").strip()
        if choice == "5":
            print("Goodbye.")
            return 0
        action = ACTIONS.get(choice)
        if not action:
            warn("Invalid choice. Please enter a number from 1 to 5.")
            continue
        try:
            action()
        except SetupError as e:
            err(str(e))
        except KeyboardInterrupt:
            warn("Interrupted.")
        except Exception as e:  # unexpected: show type + message, never a secret
            err(f"Unexpected error: {type(e).__name__}: {e}")
        input("\nPress Enter to return to the menu ...")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nGoodbye.")
        sys.exit(0)
