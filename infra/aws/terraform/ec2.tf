# Public hosted dashboard on a single EC2 instance. The instance pulls the image
# from ECR and runs it on port 8000. URL is http://<public-ip>:8000.
# Stop the instance or `terraform destroy` when idle to avoid cost.
#
# Requires the AWS account to allow standard On-Demand instances (t3.medium).
# A brand-new account limited to Free Tier will reject this with
# InvalidParameterCombination; enable standard instances / full billing first.

data "aws_vpc" "default" {
  default = true
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "dashboard" {
  name_prefix = "${local.name_prefix}-dashboard-"
  description = "AI-EDGE dashboard: inbound 8000"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "dashboard HTTP"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project_name, Environment = var.environment }
}

# Instance role so the box can pull the image from ECR.
resource "aws_iam_role" "dashboard_ec2" {
  name_prefix = "${local.name_prefix}-dash-ec2-"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "dashboard_ecr_read" {
  role       = aws_iam_role.dashboard_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "dashboard" {
  name_prefix = "${local.name_prefix}-dash-"
  role        = aws_iam_role.dashboard_ec2.name
}

resource "aws_instance" "dashboard" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = "t3.medium" # 4 GB RAM: headroom for torch + RoBERTa
  iam_instance_profile        = aws_iam_instance_profile.dashboard.name
  vpc_security_group_ids      = [aws_security_group.dashboard.id]
  associate_public_ip_address = true
  user_data_replace_on_change = true

  # Default AL2023 root is 8 GB, too small to extract the torch + RoBERTa image
  # (the pull failed with "no space left on device"). 30 GB gives clear headroom.
  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  user_data = <<-EOT
    #!/bin/bash
    set -x
    dnf install -y docker
    systemctl enable --now docker
    IMAGE="${aws_ecr_repository.dashboard.repository_url}:latest"
    REGISTRY="${split("/", aws_ecr_repository.dashboard.repository_url)[0]}"
    for i in 1 2 3 4 5 6; do
      aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin "$REGISTRY" && break
      sleep 10
    done
    docker run -d --restart always -p 8000:8000 "$IMAGE"
  EOT

  tags = { Name = "${local.name_prefix}-dashboard", Project = var.project_name, Environment = var.environment }
}

output "dashboard_url" {
  value       = "http://${aws_instance.dashboard.public_ip}:8000"
  description = "Public URL of the hosted dashboard (allow a few minutes after apply for first boot and image pull)."
}
