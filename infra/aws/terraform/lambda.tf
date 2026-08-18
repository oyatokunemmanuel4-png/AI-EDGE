# Phase 1 ingest Lambda + S3 event trigger.
# Run infra/aws/lambda/build.ps1 first to produce the package/ directory.

data "archive_file" "ingest_pkg" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/package"
  output_path = "${path.module}/../lambda/dist/ingest.zip"
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${local.name_prefix}-ingest"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "aiedge.handlers.s3_ingest.handler"
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  timeout          = 60
  memory_size      = 256
  filename         = data.archive_file.ingest_pkg.output_path
  source_code_hash = data.archive_file.ingest_pkg.output_base64sha256

  environment {
    variables = {
      AIEDGE_PROCESSED_BUCKET = aws_s3_bucket.processed.bucket
      AIEDGE_SCHEMA_DIR       = "/var/task/schemas"
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_lambda_permission" "allow_raw_bucket" {
  statement_id  = "AllowExecutionFromS3Raw"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.raw.arn
}

resource "aws_s3_bucket_notification" "raw_ingest" {
  bucket = aws_s3_bucket.raw.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
    filter_suffix       = ".jsonl"
  }

  depends_on = [aws_lambda_permission.allow_raw_bucket]
}
