# aws-bedrock-agent

社内FAQや業務問い合わせの一次対応を自動化する PoC です。
Amazon Bedrock（Claude）と Lambda を使い、Slack からの質問に自動回答します。

---

## 想定する社内業務

| 業務 | 現状の課題 | このシステムでの改善 |
|-----|-----------|-------------------|
| 社内FAQ問い合わせ | 担当者が毎回同じ質問に答える | 一次回答を自動化。担当者の工数削減 |
| 新入社員のオンボーディング | ルールや手続きが分散していて探しにくい | Slackで即座に回答 |
| IT ヘルプデスク | 問い合わせが集中して対応が遅れる | よくある質問を自動解決 |

## 想定利用者

- 社内の全従業員（Slack ユーザー）
- 問い合わせ対応担当者（工数削減の受益者）

---

## AWS 構成図

```mermaid
graph TD
    A[Slack ユーザー] -->|質問| B[Lambda Function URL]
    B --> C{FAQ キーワード検索}
    C -->|ヒット| D[FAQ 回答を返す]
    C -->|ミス| E[Amazon Bedrock Claude]
    E -->|回答生成| F[回答を返す]
    E -->|回答不能| G[エスカレーション文言]
    B --> H[CloudWatch Logs]
    B --> I[SSM Parameter Store]
    I -->|Slack Token 取得| B
```

---

## ビジネス価値

- **一次対応の自動化**: FAQ に該当する問い合わせを即座に解決
- **担当者の工数削減**: 繰り返し質問への対応時間をゼロに
- **24時間対応**: 夜間・休日でも即座に回答
- **拡張性**: FAQ データを更新するだけで回答範囲を広げられる

## PoC の成功指標

| 指標 | 目標値 | 計測方法 |
|-----|-------|---------|
| 一次回答完結率 | 70% 以上 | FAQ ヒット数 / 全質問数 |
| 回答応答時間 | 5秒以内 | CloudWatch Lambda Duration |
| フォールバック率 | 30% 以下 | フォールバック返答数 / 全質問数 |

---

## 処理フロー

```
Slack 質問
  │
  ▼
Lambda Function URL で受信
  │
  ├─ Slack 署名検証（なりすまし防止）
  │
  ├─ FAQ キーワード検索（ローカル辞書）
  │     ヒット → FAQ 回答を返す
  │
  ├─ Bedrock（Claude）に問い合わせ
  │     成功 → AI 回答を返す
  │
  └─ フォールバック → エスカレーション文言
```

---

## セットアップ手順

### 1. Bedrock モデルのアクセス許可

AWS コンソール → Amazon Bedrock → モデルアクセス → **Claude 3 Haiku を有効化**

### 2. SSM Parameter Store にトークンを保存

```bash
# Slack Bot Token
aws ssm put-parameter \
  --name "/bedrock-agent/dev/slack-bot-token" \
  --value "xoxb-xxxxxxxxxxxx" \
  --type SecureString

# Slack Signing Secret
aws ssm put-parameter \
  --name "/bedrock-agent/dev/slack-signing-secret" \
  --value "xxxxxxxxxxxxxxxx" \
  --type SecureString
```

### 3. Terraform でデプロイ

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
# outputs に Lambda Function URL が表示される
```

### 4. Slack App の設定

1. `https://api.slack.com/apps` でアプリを作成
2. **Event Subscriptions** → Request URL に Lambda Function URL を貼り付け
3. `app_mention` イベントを Subscribe
4. アプリをワークスペースにインストール

### 5. 動作確認

```bash
# Lambda を直接テスト（Bedrock なしのダミーモード）
aws lambda invoke \
  --function-name bedrock-agent-dev \
  --payload '{"body": "{\"question\": \"有給の申請方法を教えてください\"}"}' \
  --cli-binary-format raw-in-base64-out \
  output.json && cat output.json
```

---

## セキュリティ上の注意点

| 項目 | 対応状況 | TODO |
|-----|---------|------|
| Slack 署名検証 | 実装済み | 本番で SKIP_SLACK_VERIFICATION=false に設定 |
| トークン管理 | SSM Parameter Store（SecureString） | ローテーション設定を追加 |
| IAM 最小権限 | Bedrock・SSM のみ許可 | モデル ARN を特定のものに絞る |
| ログの個人情報 | 質問の先頭50文字のみ記録 | 本番では更に制限する |

---

## 推定コスト（月額）

| リソース | 単価 | 月間想定 | 小計 |
|---------|------|---------|------|
| Lambda | $0.0000002/リクエスト | 1,000回 | ~$0.01 |
| Bedrock Claude 3 Haiku | $0.00025/1K input tokens | 1,000回×200tokens | ~$0.05 |
| CloudWatch Logs | $0.76/GB | 最小 | ~$0.01 |
| **合計** | | | **~$0.10/月** |

> ⚠️ Bedrock はリクエスト数に応じて課金。大量利用時はコスト増加に注意。

---

## 今後の拡張ポイント

| 拡張項目 | 内容 |
|---------|------|
| RAG 連携 | Bedrock Knowledge Bases で社内ドキュメントを検索 |
| FAQ 管理画面 | Google Sheets や DynamoDB で FAQ を管理 |
| 回答ログ | DynamoDB に保存して未回答パターンを分析 |
| 非同期処理 | SQS で Slack の 3 秒タイムアウトに対応 |
| LINE 連携 | Webhook の受け口を変えるだけで対応可能 |

---

## 後片付け

```bash
terraform destroy
# SSM パラメータは手動削除が必要
aws ssm delete-parameter --name "/bedrock-agent/dev/slack-bot-token"
aws ssm delete-parameter --name "/bedrock-agent/dev/slack-signing-secret"
```

> ⚠️ Lambda Function URL は destroy で削除されます。Slack の Webhook URL も無効になります。

---

*このプロジェクトは学習・PoC 目的で作成しました。本番導入時は認証強化・監視・エラー通知の追加が必要です。*
