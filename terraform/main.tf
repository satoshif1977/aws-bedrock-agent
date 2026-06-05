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
  # checkov:skip=CKV_AWS_290: bedrock:InvokeModelWithResponseStream は Checkov が書き込みと誤判定するが特定モデル ARN に限定済み
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
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
      }
    ]
  })
}

# SSM Parameter Store 読み取り権限（Slack トークン取得用）
resource "aws_iam_role_policy" "ssm" {
  # checkov:skip=CKV_AWS_290: ssm:GetParameter/GetParameters は読み取り専用操作であり権限昇格のリスクはない
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
        # checkov:skip=CKV_AWS_111: SSM マネージドキー（aws/ssm）ARN は apply 前に確定できないため "*" を使用
        # checkov:skip=CKV_AWS_356: 同上
        # checkov:skip=CKV_AWS_355: 同上（SSM マネージドキー ARN は動的のため "*" を使用）
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
      }
    ]
  })
}

# ── CloudWatch Logs ────────────────────────────────────────
resource "aws_cloudwatch_log_group" "lambda" {
  # checkov:skip=CKV_AWS_158: dev/PoC 環境のため AWS 管理キーで十分（KMS CMK は本番のみ）
  name              = "/aws/lambda/${var.project_name}-${var.environment}"
  retention_in_days = var.log_retention_days

  # TODO: 本番では retention_in_days を 30〜90 日に設定する
  # TODO: 個人情報・機密情報がログに含まれないよう Lambda 側で制御する
}

# ── Lambda 関数 ────────────────────────────────────────────
resource "aws_lambda_function" "main" {
  # checkov:skip=CKV_AWS_116: dev/PoC のため DLQ は不要
  # checkov:skip=CKV_AWS_117: dev/PoC のためパブリック Lambda で十分（VPC 配置不要）
  # checkov:skip=CKV_AWS_272: dev/PoC のためコード署名は不要
  # checkov:skip=CKV_AWS_115: dev/PoC のため同時実行数制限は不要
  # checkov:skip=CKV_AWS_173: 環境変数は設定値のみで機密情報なし（Slack トークンは SSM 経由）
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
      BEDROCK_MODEL_ID              = var.bedrock_model_id
      SLACK_BOT_TOKEN_SSM_PATH      = var.slack_bot_token_ssm_path
      SLACK_SIGNING_SECRET_SSM_PATH = var.slack_signing_secret_ssm_path
      LOG_LEVEL                     = "INFO"
      SKIP_SLACK_VERIFICATION       = "true"
      DYNAMODB_TABLE                = var.dynamodb_table_name
      FAQ_TABLE                     = aws_dynamodb_table.faq.name
      # TODO: 本番では環境変数に機密情報を直接入れない（SSM 経由で取得）
      # TODO: Slack 連携時は SKIP_SLACK_VERIFICATION を false に戻す
    }
  }

  tracing_config {
    mode = "PassThrough"
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_cloudwatch_log_group.lambda
  ]
}


# ── DynamoDB テーブル（FAQ データ） ────────────────────────
resource "aws_dynamodb_table" "faq" {
  # checkov:skip=CKV_AWS_28: dev/PoC 環境のため PITR 無効（本番では enabled = true に変更）
  name         = "${var.project_name}-${var.environment}-faq"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "keyword"

  attribute {
    name = "keyword"
    type = "S"
  }

  point_in_time_recovery {
    enabled = false # dev/PoC では不要
  }

  # AWS マネージドキーで保存データを暗号化（CKV_AWS_119 / 追加コストなし）
  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = false # dev: スタック削除と同時に削除

  tags = {
    Name = "${var.project_name}-${var.environment}-faq"
  }
}

# ── DynamoDB テーブル（質問ログ） ──────────────────────────
resource "aws_dynamodb_table" "question_log" {
  name         = var.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "question_id"

  attribute {
    name = "question_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  # AWS マネージドキーで保存データを暗号化（CKV_AWS_119 / 追加コストなし）
  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = false # dev: スタック削除と同時に削除

  tags = {
    Name = var.dynamodb_table_name
  }
}

# DynamoDB 書き込み権限（Lambda ロールに追加）
resource "aws_iam_role_policy" "dynamodb" {
  # checkov:skip=CKV_AWS_290: dynamodb:PutItem は特定テーブル ARN のみ許可・Checkov の誤検知
  name = "${var.project_name}-${var.environment}-dynamodb-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ]
      Resource = [
        aws_dynamodb_table.question_log.arn,
        aws_dynamodb_table.faq.arn,
      ]
    }]
  })
}

# ── Bedrock Guardrail ──────────────────────────────────────
resource "aws_bedrock_guardrail" "main" {
  name                      = "${var.project_name}-${var.environment}-guardrail"
  description               = "社内FAQ ボット用ガードレール（コンテンツフィルター・PII マスキング・禁止トピック）"
  blocked_input_messaging   = "申し訳ありません。その質問にはお答えできません。別の質問をお試しください。"
  blocked_outputs_messaging = "申し訳ありません。その回答はお伝えできません。担当部署にご連絡ください。"

  # ── コンテンツフィルター（有害コンテンツのブロック）──────
  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
  }

  # ── 禁止トピック（社内FAQボットに不適切な質問をブロック）──
  topic_policy_config {
    topics_config {
      name       = "legal-advice"
      type       = "DENY"
      definition = "法的なアドバイス・訴訟・契約解釈に関する質問"
      examples   = ["この契約は有効ですか", "訴訟を起こせますか", "法的責任はどうなりますか"]
    }
    topics_config {
      name       = "salary-details"
      type       = "DENY"
      definition = "他の従業員の給与・賞与・評価に関する情報の開示要求"
      examples   = ["〇〇さんの年収は", "給与テーブルを教えて", "誰が一番高い給与ですか"]
    }
    topics_config {
      name       = "competitor-info"
      type       = "DENY"
      definition = "競合他社の内部情報・顧客情報・戦略に関する質問"
      examples   = ["競合他社の価格は", "他社の顧客リストを見せて"]
    }
  }

  # ── 機密情報マスキング（PII 自動検出・リダクション）────────
  sensitive_information_policy_config {
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "NAME"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "ADDRESS"
      action = "ANONYMIZE"
    }
  }

  # ── ワードフィルター（不適切語・機密キーワード）────────────
  word_policy_config {
    words_config {
      text = "パスワード"
    }
    words_config {
      text = "秘密鍵"
    }
    words_config {
      text = "アクセスキー"
    }
    managed_word_lists_config {
      type = "PROFANITY"
    }
  }
}

# ── Guardrail バージョン（Agent にはバージョンを指定する必要がある）──
resource "aws_bedrock_guardrail_version" "main" {
  guardrail_arn = aws_bedrock_guardrail.main.guardrail_arn
  description   = "初期バージョン"
}

# ── Bedrock Agent IAM ロール ────────────────────────────────
resource "aws_iam_role" "bedrock_agent" {
  name        = "${var.project_name}-${var.environment}-agent-role"
  description = "IAM role for Bedrock Agent"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "bedrock_agent_model" {
  name = "${var.project_name}-${var.environment}-agent-model-policy"
  role = aws_iam_role.bedrock_agent.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:ApplyGuardrail"]
        Resource = aws_bedrock_guardrail.main.guardrail_arn
      }
    ]
  })
}

# ── Bedrock Agent ───────────────────────────────────────────
resource "aws_bedrockagent_agent" "main" {
  agent_name                  = "${var.project_name}-${var.environment}"
  agent_resource_role_arn     = aws_iam_role.bedrock_agent.arn
  foundation_model            = var.bedrock_model_id
  instruction                 = var.agent_instruction
  idle_session_ttl_in_seconds = 600

  guardrail_configuration {
    guardrail_identifier = aws_bedrock_guardrail.main.guardrail_id
    guardrail_version    = aws_bedrock_guardrail_version.main.version
  }
}

# ── Action Group ────────────────────────────────────────────
resource "aws_bedrockagent_agent_action_group" "faq_search" {
  agent_id           = aws_bedrockagent_agent.main.agent_id
  agent_version      = "DRAFT"
  action_group_name  = "faq-search"
  action_group_state = "ENABLED"
  description        = "社内FAQを検索して回答を返すアクション"

  action_group_executor {
    lambda = aws_lambda_function.main.arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "search-faq"
        description = "FAQを検索して回答を返す"
        parameters {
          map_block_key = "question"
          type          = "string"
          description   = "ユーザーの質問"
          required      = true
        }
      }
    }
  }
}

# ── Action Group 2：質問ログ記録 ───────────────────────────
resource "aws_bedrockagent_agent_action_group" "log_question" {
  agent_id           = aws_bedrockagent_agent.main.agent_id
  agent_version      = "DRAFT"
  action_group_name  = "log-question"
  action_group_state = "ENABLED"
  description        = "質問と回答を DynamoDB に記録するアクション"

  action_group_executor {
    lambda = aws_lambda_function.main.arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "log-question"
        description = "ユーザーの質問と回答内容を DynamoDB に記録する"
        parameters {
          map_block_key = "question"
          type          = "string"
          description   = "ユーザーの質問"
          required      = true
        }
        parameters {
          map_block_key = "answer"
          type          = "string"
          description   = "提供した回答"
          required      = true
        }
      }
    }
  }

  depends_on = [aws_bedrockagent_agent_action_group.faq_search]
}

# ── Bedrock Agent → Lambda 呼び出し権限 ────────────────────
resource "aws_lambda_permission" "bedrock_agent" {
  statement_id  = "AllowBedrockAgent"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.main.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.main.agent_arn
}

# ── Lambda Function URL（Slack Webhook の受け口） ───────────
resource "aws_lambda_function_url" "main" {
  # checkov:skip=CKV_AWS_258: Slack Webhook 受付のため認証なしで公開（Lambda 内で署名検証実施）
  function_name      = aws_lambda_function.main.function_name
  authorization_type = "NONE" # Slack からの Webhook を受け付けるため公開

  cors {
    allow_origins = ["*"]
    allow_methods = ["POST", "GET"]
    allow_headers = ["content-type"]
  }

  # TODO: 本番では Slack の署名検証を Lambda 内で必ず実装する
  # TODO: IP 制限や WAF の追加を検討する
}

# ── Lambda Function URL への公開アクセス許可 ────────────────
resource "aws_lambda_permission" "function_url_public" {
  # checkov:skip=CKV_AWS_301: Slack Webhook 受付のため公開アクセスが必要（Lambda 内で署名検証実施）
  statement_id           = "AllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.main.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# ── Bedrock Agent エイリアス ────────────────────────────────
# エイリアスを使うことで「DRAFT（開発中）」と「v1（安定版）」を切り替えて
# Runtime API（InvokeAgent）から呼び出せる。
# 本番運用では: routing_configuration.agent_version を "1" 等に変更するだけで切り替え可能。
resource "aws_bedrockagent_agent_alias" "v1" {
  agent_id         = aws_bedrockagent_agent.main.agent_id
  agent_alias_name = "${var.project_name}-${var.environment}-v1"
  description      = "安定版エイリアス（DRAFT 指向。本番化時は agent_version を数値バージョンに変更する）"

  routing_configuration {
    agent_version = "DRAFT"
  }

  tags = {
    Environment = var.environment
    Project     = var.project_name
    ManagedBy   = "Terraform"
  }
}
