output "raw_bucket_name" {
  value = aws_s3_bucket.raw.bucket
}

output "processed_bucket_name" {
  value = aws_s3_bucket.processed.bucket
}

output "lambda_execution_role_arn" {
  value = aws_iam_role.lambda_execution.arn
}

output "ingest_function_name" {
  value = aws_lambda_function.ingest.function_name
}
