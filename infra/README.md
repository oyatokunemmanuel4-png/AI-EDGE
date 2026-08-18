# `infra/` — Infrastructure & deployment

Everything needed to deploy and run AI-EDGE's infrastructure: the AWS cloud
pipeline, the container images, and the Hyperledger Fabric ledger. No application
logic lives here — it packages and deploys [`../app/`](../app/).

## Contents

```
infra/
  aws/
    terraform/       S3 (raw/processed) buckets, Lambda role + function, S3->Lambda
                     trigger; account/region switchable via aws_profile
    lambda/build.ps1 assembles the Lambda deployment package (app/aiedge + app/schemas
                     + jsonschema, Linux wheels)
  docker/
    Dockerfile.dashboard      lean dashboard image (stub classifier, torch-free)
    Dockerfile.dashboard-ml   dashboard serving the real fine-tuned RoBERTa (model mounted)
    Dockerfile.dashboard-aws  self-contained image (RoBERTa baked in) for AWS App Runner
  fabric/
    chaincode/governance/     Node governance-decision smart contract (+ CCaaS Dockerfile)
    wsl_network.sh            bring up the 2-org test network (WSL2 Ubuntu)
    deploy_governance_ccaas.sh deploy the chaincode as a service (CCaaS)
    invoke_decision.sh / query_decision.sh   record / read decisions on the ledger
```

`../docker-compose.yml` (repo root) builds the dashboard services from
`infra/docker/` and mounts the root `data/` and `models/` working dirs.

## How it fits the project

- **AWS** is the event-driven hot path: an object landing in the raw S3 bucket
  triggers the Lambda (`aiedge.handlers.s3_ingest`), which runs the pipeline and
  writes decisions to the processed bucket.
- **Docker** packages the dashboard for a reproducible, OS-agnostic run.
- **Fabric** provides the immutable audit ledger; the app's `FabricDecisionSink`
  writes to the deployed chaincode. CCaaS is used (peer connects to a chaincode
  container over gRPC) so it works with Docker's containerd image store and is the
  production/Kubernetes-standard model.

## Developer notes

- **AWS**: `aws configure --profile aiedge`, set `aws_profile` in
  `aws/terraform/terraform.tfvars`, then `terraform init && terraform apply`.
  Build/deploy the Lambda with `aws/lambda/build.ps1` (paths reference `app/`).
- **Fabric** runs under **WSL2 Ubuntu** (Hyperledger's supported env; on native
  Linux run the same scripts directly). Bring up: `wsl_network.sh up`, then
  `deploy_governance_ccaas.sh`. The org2 host port is remapped 9051→11051 to dodge
  a Windows reserved range — a dev-env detail that doesn't apply on Linux/K8s.
- **Dashboard**: `docker compose up -d --build dashboard` (or `dashboard-ml` for
  the real model). Full ledger deploy details: [`../docs/phase4.md`](../docs/phase4.md).
- **Public hosted demo (AWS EC2)** — so others can test via a URL without
  installing anything. `aws/terraform/ecr.tf` + `aws/terraform/ec2.tf` provision an
  ECR repo and a single t3.medium instance that pulls the image
  (`docker/Dockerfile.dashboard-aws`, RoBERTa baked in) and runs it on port 8000.
  Deploy:
  ```bash
  # 1. ECR repo
  terraform apply -target=aws_ecr_repository.dashboard
  # 2. build + push (model must be present at models/nlp/roberta-base)
  docker build -f infra/docker/Dockerfile.dashboard-aws -t <ecr-uri>:latest .
  aws ecr get-login-password | docker login --username AWS --password-stdin <registry>
  docker push <ecr-uri>:latest
  # 3. launch the instance -> prints dashboard_url (http://<ip>:8000)
  terraform apply
  ```
  Notes: the instance has a 30 GB root volume (the torch + RoBERTa image is too big
  for the default 8 GB). The decision store is ephemeral (resets if the container
  restarts) and shared across testers; there's no auth; the hosted demo runs the
  classifier + rule engine but not the local Fabric ledger. The account must be on
  a **paid** plan (a Free-plan account rejects non-micro instances). A t3.medium
  bills while running — **stop the instance** or `terraform destroy` when idle:
  ```bash
  aws ec2 stop-instances  --instance-ids <id>   # pause (keeps the IP config)
  aws ec2 start-instances --instance-ids <id>   # resume (public IP changes)
  terraform destroy -target=aws_instance.dashboard   # remove entirely
  ```
  App Runner was attempted first but is not enabled on this account; App Runner and
  ECS Fargate both require a paid account as well.
