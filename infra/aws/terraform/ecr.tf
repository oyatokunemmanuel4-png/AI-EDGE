# Container registry for the hosted dashboard image (built from
# infra/docker/Dockerfile.dashboard-aws, RoBERTa baked in).
resource "aws_ecr_repository" "dashboard" {
  name                 = "${local.name_prefix}-dashboard"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
