# ── Bedrock Agent PoC ─────────────────────────────────────
# 構成:
#   Lambda（FAQ応答・Bedrock呼び出し）
#   IAM Role（Lambda 実行権限 + Bedrock 権限）
#   CloudWatch Logs（ログ保存）
#   Lambda Function URL（Slack Webhook の受け口）
#   SSM Parameter Store（Slack トークン管理）
# ──────────────────────────────────────────────────────────

# ── Lambda デプロイパッケージ ──────────────────────────────
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/../lambda.zip"
}

# ── IAM ロール ─────────────────────────────────────────────
resource "aws_iam_role" "lambda" {
  name        = "${var.project_name}-${var.environment}-lambda-role"
  description = "IAM role for Bedrock Agent Lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Lambda 基本実行ポリシー（CloudWatch Logs への書き込み）
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Bedrock 呼び出し権限
resource "aws_iam_role_policy" "bedrock" {
  name = "${var.project_name}-${var.environment}-bedrock-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        # TODO: 本番では使用するモデル ARN に絞る（最小権限の原則）
        # Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
        Resource = "*"
      }
    ]
  })
}

# SSM Parameter Store 読み取り権限（Slack トークン取得用）
resource "aws_iam_role_policy" "ssm" {
  name = "${var.project_name}-${var.environment}-ssm-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:*:parameter${var.slack_bot_token_ssm_path}",
          "arn:aws:ssm:${var.aws_region}:*:parameter${var.slack_signing_secret_ssm_path}"
        ]
      },
      {
        # SSM の KMS 復号権限（SecureString の場合）
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        # TODO: 本番では特定の KMS キー ARN に絞る
      }
    ]
  })
}

# ── CloudWatch Logs ────────────────────────────────────────
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}"
  retention_in_days = var.log_retention_days

  # TODO: 本番では retention_in_days を 30〜90 日に設定する
  # TODO: 個人情報・機密情報がログに含まれないよう Lambda 側で制御する
}

# ── Lambda 関数 ────────────────────────────────────────────
resource "aws_lambda_function" "main" {
  function_name = "${var.project_name}-${var.environment}"
  description   = "社内FAQ自動応答 PoC - Bedrock + Slack 連携"
  role          = aws_iam_role.lambda.arn
  handler       = "index.handler"
  runtime       = "python3.11"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      BEDROCK_MODEL_ID             = var.bedrock_model_id
      SLACK_BOT_TOKEN_SSM_PATH     = var.slack_bot_token_ssm_path
      SLACK_SIGNING_SECRET_SSM_PATH = var.slack_signing_secret_ssm_path
      LOG_LEVEL                    = "INFO"
      # TODO: FAQ データのパス（S3 or SSM）を追加する
      # TODO: 本番では環境変数に機密情報を直接入れない（SSM 経由で取得）
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_cloudwatch_log_group.lambda
  ]
}

# ── Lambda Function URL（Slack Webhook の受け口） ───────────
resource "aws_lambda_function_url" "main" {
  function_name      = aws_lambda_function.main.function_name
  authorization_type = "NONE" # Slack からの Webhook を受け付けるため公開

  cors {
    allow_origins = ["https://slack.com"]
    allow_methods = ["POST"]
  }

  # TODO: 本番では Slack の署名検証を Lambda 内で必ず実装する
  # TODO: IP 制限や WAF の追加を検討する
}
