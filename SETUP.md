# AI-EDGE — Setup Guide (Run It Yourself)

This guide takes you from a clean computer to a running copy of AI-EDGE. It has
two paths:

- **Path A — Run locally with Docker.** The fastest way to see the app working on
  your own PC. No cloud account needed.
- **Path B — Deploy to your own AWS.** Provision the cloud pipeline and a public
  dashboard in your own AWS account, then test it.

You can stop after Path A. Path B is only needed if you want the cloud version.

---

## 0. Prerequisites (install these first)

| Tool | Needed for | Download |
|---|---|---|
| **Git** | getting the code | https://git-scm.com/downloads |
| **Docker Desktop** | running the app (Path A) | https://www.docker.com/products/docker-desktop |
| **AWS CLI** | your own AWS (Path B) | https://aws.amazon.com/cli/ |
| **Terraform** | provisioning AWS (Path B) | https://developer.hashicorp.com/terraform/install |
| Python 3.12 *(optional)* | running the tests without Docker | https://www.python.org/downloads/ |

After installing, open a new terminal and confirm they work:

```powershell
git --version
docker --version
aws --version        # Path B only
terraform --version  # Path B only
```

Start **Docker Desktop** and wait until it shows **"Engine running"** before Path A.

---

## 1. Get the code

```powershell
git clone <your-repo-url> AI-EDGE
cd AI-EDGE
```

(Replace `<your-repo-url>` with the repository address. All commands below are run
from inside this `AI-EDGE` folder.)

---

## Path A — Run on your PC with Docker

This builds the app into a container and serves the dashboard. It uses a
lightweight, rule-based classifier, so it needs **no trained model and no cloud**.

### A1. Build and start the dashboard

```powershell
docker compose up -d --build dashboard
```

The first build takes a few minutes. When it finishes, open:

**http://localhost:8000**

### A2. Try it

1. Go to **Upload Documents**.
2. Upload a file from the `ml/samples/` folder:
   - `pii_employee_record.txt` — is classified as personal data and **flagged**.
   - `data_governance_policy.txt` — is **allowed**.
   - `access_events.jsonl` — contains access logs; produces an **alert** and a
     **block** that appear on the **Alerts** page.
3. Open **Analysis Results** to see the class, confidence, decision, and the rule
   that fired for each item.
4. Open **Alerts** to see the decisions that need attention.

### A3. Stop it

```powershell
docker compose down
```

### A4. (Optional) Run the real machine-learning model

The step above uses a simple keyword classifier so it runs anywhere. To serve the
**real fine-tuned RoBERTa** model instead, you need the trained model at
`models/nlp/roberta-base/` (produced by training in [`ml/`](ml/), or copied in).
Then:

```powershell
docker compose up -d --build dashboard-ml
```

Open **http://localhost:8001**. This image is larger because it includes PyTorch.

### A5. (Optional) Run the automated tests

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,dashboard]"
.\.venv\Scripts\python.exe -m pytest -q      # expect: all green
```

---

## Path B — Deploy to your own AWS

This provisions the event-driven pipeline (storage + a serverless function) and a
public dashboard on a small server, all in **your** AWS account.

### B1. Create an AWS account and credentials

1. Create an AWS account: https://aws.amazon.com/
2. **Important:** make sure the account is on a **paid plan** with a valid card.
   A brand-new "Free" account will refuse the server we need, with an error like
   *"instance type is not eligible for Free Tier"*.
3. In the AWS console, create an access key for your user (IAM → Users → Security
   credentials → Create access key).
4. Configure the AWS CLI with a named profile:

```powershell
aws configure --profile myaws
# paste your Access Key ID, Secret Access Key, region (e.g. us-east-1), format json
```

### B2. Point the project at your account

Open `infra/aws/terraform/terraform.tfvars` and set the profile to yours:

```hcl
aws_profile = "myaws"
aws_region  = "us-east-1"
```

(These are the only values you normally change. `project_name` and `environment`
just prefix the resource names.)

### B3. Provision the pipeline (storage + function)

```powershell
cd infra/aws/terraform
terraform init
terraform apply        # review the plan, type: yes
```

This creates two S3 buckets (raw input, processed output), a Lambda function, and
the trigger that runs the function whenever a file lands in the raw bucket. Note
the output bucket names.

### B4. Deploy the public dashboard (container image + server)

Still in `infra/aws/terraform`:

```powershell
# 1. create the image registry
terraform apply -target=aws_ecr_repository.dashboard

# 2. build the dashboard image and push it (run from the project root)
cd ../../..
$ACCOUNT = aws sts get-caller-identity --profile myaws --query Account --output text
$REGION  = "us-east-1"
$REPO    = "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/aiedge-dev-dashboard"
aws ecr get-login-password --profile myaws --region $REGION | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
docker build -f infra/docker/Dockerfile.dashboard-aws -t "$REPO:latest" .
docker push "$REPO:latest"

# 3. launch the server; it prints the dashboard URL
cd infra/aws/terraform
terraform apply        # type: yes -> outputs dashboard_url
```

> **Model note:** `Dockerfile.dashboard-aws` bakes in the real RoBERTa model, so it
> expects `models/nlp/roberta-base/` to be present when you build. If you do not
> have the trained model, build the lightweight image instead
> (`-f infra/docker/Dockerfile.dashboard`), which uses the keyword classifier and
> needs no model.

### B5. Test it on AWS

**The dashboard.** Open the `dashboard_url` from the previous step (it looks like
`http://<ip>:8000`). Give it two or three minutes on first boot, then upload files
from `ml/samples/` exactly as in Path A. The behaviour is identical to local,
because it is the same application.

**The event-driven pipeline.** Upload an access-log file to the **raw** bucket
under an `raw/access/` prefix, then check the **processed** bucket:

```powershell
terraform output        # shows raw_bucket_name and processed_bucket_name
aws s3 cp ../../../ml/samples/access_events.jsonl s3://<raw_bucket_name>/raw/access/demo.jsonl --profile myaws
# a few seconds later:
aws s3 ls s3://<processed_bucket_name>/decisions/access/ --profile myaws
```

Seeing a `decisions/access/demo.jsonl` object appear proves the full hot path:
a file arrived, the function ran automatically, the pipeline made governance
decisions, and the results were written back. No manual step was involved.

### B6. Shut it down to avoid cost

The server bills while it runs. When you are finished:

```powershell
# stop the dashboard server (keeps everything, cheapest)
aws ec2 stop-instances --instance-ids <instance-id> --profile myaws --region us-east-1

# or remove everything you created
terraform destroy
```

(You can find the instance id with
`aws ec2 describe-instances --profile myaws --query "Reservations[].Instances[].InstanceId" --output text`.)

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker` command not found / cannot connect | Start Docker Desktop; wait for "Engine running". |
| Port 8000 already in use | Stop the other program, or change the port mapping in `docker-compose.yml`. |
| AWS error: *instance type not eligible for Free Tier* | Your AWS account is on the Free plan. Upgrade it to a paid plan in the Billing console. |
| Dashboard image build fails on `COPY models/...` | You are building the real-model image without the model. Build `Dockerfile.dashboard` instead, or add the model at `models/nlp/roberta-base/`. |
| Dashboard URL does not load immediately after `apply` | The server needs a few minutes to boot and pull the image. Retry `http://<ip>:8000/healthz`. |

---

## What each path proves

- **Path A** shows that AI-EDGE is a self-contained, reproducible application: one
  command builds and runs the whole governance dashboard on any machine with Docker.
- **Path B** shows that the same application is cloud-native: it deploys to real AWS
  services, reacts to events automatically, and serves a public dashboard, which is
  how such a system would be used in practice.
