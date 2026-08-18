variable "project_name" {
  description = "Project prefix for provisioned resources."
  type        = string
  default     = "aiedge"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region for Phase 0 resources."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Named AWS CLI profile to use. Leave empty to use the default credential chain (env vars / default profile). Switching accounts = change this one value."
  type        = string
  default     = ""
}
