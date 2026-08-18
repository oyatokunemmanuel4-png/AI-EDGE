# Assemble the Phase 1 Lambda deployment package.
#
# Produces infra/aws/lambda/package/ containing:
#   aiedge/        (our code)
#   schemas/       (JSON Schemas, referenced via AIEDGE_SCHEMA_DIR=/var/task/schemas)
#   jsonschema + deps  (Linux/py3.12 wheels so native rpds-py matches Lambda)
#
# boto3 is provided by the Lambda runtime, so it is NOT bundled.
# Terraform's archive_file zips package/ into the deployment zip.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path          # infra/aws/lambda
$root = Resolve-Path (Join-Path $here "..\..\..")                # repo root
$pkg = Join-Path $here "package"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "=== clean package dir ==="
if (Test-Path $pkg) { Remove-Item -Recurse -Force $pkg }
New-Item -ItemType Directory -Path $pkg | Out-Null

Write-Host "=== install runtime deps (Linux x86_64 / cp312 wheels) ==="
& $venvPy -m pip install `
  --target $pkg `
  --platform manylinux2014_x86_64 `
  --implementation cp `
  --python-version 3.12 `
  --only-binary=:all: `
  --upgrade `
  "jsonschema>=4.22" | Select-Object -Last 3

Write-Host "=== copy aiedge source ==="
Copy-Item -Recurse -Force (Join-Path $root "app\aiedge") (Join-Path $pkg "aiedge")

Write-Host "=== copy schemas ==="
Copy-Item -Recurse -Force (Join-Path $root "app\schemas") (Join-Path $pkg "schemas")

Write-Host "=== strip caches ==="
Get-ChildItem -Path $pkg -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "=== package ready: $pkg ==="
Get-ChildItem $pkg | Select-Object Name
