terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Empty profile falls back to the default credential chain (env vars /
  # default profile). Set aws_profile to switch accounts in one place.
  profile = var.aws_profile != "" ? var.aws_profile : null
}
