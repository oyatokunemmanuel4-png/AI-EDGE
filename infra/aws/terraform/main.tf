locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_s3_bucket" "raw" {
  bucket_prefix = "${local.name_prefix}-raw-"

  tags = {
    Project     = var.project_name
    Environment = var.environment
    DataPlane   = "raw"
  }
}

resource "aws_s3_bucket" "processed" {
  bucket_prefix = "${local.name_prefix}-processed-"

  tags = {
    Project     = var.project_name
    Environment = var.environment
    DataPlane   = "processed"
  }
}

resource "aws_iam_role" "lambda_execution" {
  name_prefix = "${local.name_prefix}-lambda-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_s3_access" {
  name = "${local.name_prefix}-lambda-s3-access"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.raw.arn,
          "${aws_s3_bucket.raw.arn}/*",
          aws_s3_bucket.processed.arn,
          "${aws_s3_bucket.processed.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}
