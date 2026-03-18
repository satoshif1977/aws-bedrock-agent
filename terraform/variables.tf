variable "project_name" {
  description = "プロジェクト名（リソース命名に使用）"
  type        = string
  default     = "bedrock-agent"
}

variable "environment" {
  description = "環境名（dev / stg / prod）"
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "デプロイ先 AWS リージョン"
  type        = string
  default     = "ap-northeast-1"
}

# ── Bedrock 設定 ───────────────────────────────────────────
variable "bedrock_model_id" {
  description = "使用する Bedrock モデル ID"
  type        = string
  default     = "anthropic.claude-3-haiku-20240307-v1:0"
  # 候補:
  #   anthropic.claude-3-haiku-20240307-v1:0   （高速・低コスト）
  #   anthropic.claude-3-sonnet-20240229-v1:0  （バランス型）
  #   amazon.titan-text-lite-v1                （低コスト）
  # TODO: 本番では用途に応じてモデルを選定する
}

# ── Lambda 設定 ────────────────────────────────────────────
variable "lambda_timeout" {
  description = "Lambda タイムアウト秒数"
  type        = number
  default     = 30
  # TODO: Bedrock の応答時間に応じて調整する（通常 10〜20 秒）
}

variable "lambda_memory_size" {
  description = "Lambda メモリサイズ（MB）"
  type        = number
  default     = 256
}

variable "log_retention_days" {
  description = "CloudWatch Logs の保持日数"
  type        = number
  default     = 3
  # TODO: 本番では 30〜90 日に延長する
}

# ── DynamoDB 設定 ──────────────────────────────────────────
variable "dynamodb_table_name" {
  description = "質問ログを保存する DynamoDB テーブル名"
  type        = string
  default     = "bedrock-agent-dev-questions"
}

# ── Bedrock Agent 設定 ─────────────────────────────────────
variable "agent_instruction" {
  description = "Bedrock Agent への指示文"
  type        = string
  default     = <<-EOT
    あなたは社内FAQ自動応答アシスタントです。
    ユーザーからの質問に対して、必ず以下の順番で処理してください。

    ステップ1: faq-search アクショングループの search-faq 関数を使って FAQ を検索し、回答を取得する。
    ステップ2: 取得した回答をユーザーに日本語で簡潔に伝える。
    ステップ3: 必ず log-question アクショングループの log-question 関数を使って、質問と回答を記録する。

    記録は省略せず、必ず実行すること。
    個人情報や機密情報には触れないでください。
  EOT
}

# ── Slack 設定 ─────────────────────────────────────────────
variable "slack_bot_token_ssm_path" {
  description = "Slack Bot Token を保存した SSM Parameter Store のパス"
  type        = string
  default     = "/bedrock-agent/dev/slack-bot-token"
  # TODO: SSM Parameter Store に SecureString として保存すること
  # aws ssm put-parameter --name "/bedrock-agent/dev/slack-bot-token" \
  #   --value "xoxb-xxxx" --type SecureString
}

variable "slack_signing_secret_ssm_path" {
  description = "Slack Signing Secret を保存した SSM Parameter Store のパス"
  type        = string
  default     = "/bedrock-agent/dev/slack-signing-secret"
}
