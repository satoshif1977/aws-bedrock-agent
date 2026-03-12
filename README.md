# aws-bedrock-agent

社内FAQや業務問い合わせの一次対応を自動化する PoC です。
Amazon Bedrock（Claude）と Lambda を使い、**Web UI（Streamlit）** からの質問に自動回答します。
Slack 連携は拡張オプションとして対応可能です。

---

## デモ画面（Streamlit Web UI）

![Streamlit デモ画面](docs/screenshots/demo_streamlit.png)

| Lambda コンソール | Lambda モニタリング |
|---|---|
| ![Lambda Console](docs/screenshots/lambda_console.png) | ![Lambda Monitoring](docs/screenshots/lambda_monitoring.png) |

---

## 想定する社内業務

| 業務 | 現状の課題 | このシステムでの改善 |
|-----|-----------|-------------------|
| 社内FAQ問い合わせ | 担当者が毎回同じ質問に答える | 一次回答を自動化。担当者の工数削減 |
| 新入社員のオンボーディング | ルールや手続きが分散していて探しにくい | Web UIで即座に回答 |
| IT ヘルプデスク | 問い合わせが集中して対応が遅れる | よくある質問を自動解決 |

---

## AWS 構成図

```mermaid
graph TD
    A[ユーザー（ブラウザ）] -->|質問| B[Streamlit Web UI]
    B -->|boto3 Invoke| C[AWS Lambda]
    C --> D{FAQ キーワード検索}
    D -->|ヒット| E[FAQ 回答を返す]
    D -->|ミス| F[Amazon Bedrock Claude]
    F -->|回答生成| G[回答を返す]
    F -->|回答不能| H[エスカレーション文言]
    C --> I[CloudWatch Logs]
    C --> J[SSM Parameter Store]
```

---

## フロントエンド構成

| フロントエンド | 状態 | 用途 |
|---|---|---|
| **Streamlit Web UI** | **実装済み（メイン）** | デモ・PoC・社内共有 |
| Slack ボット | 拡張オプション | 社内ツール・ヘルプデスク |

---

## 処理フロー

```
ユーザーが Web UI に質問を入力
  │
  ▼
Streamlit（boto3）→ Lambda を直接 Invoke
  │
  ├─ FAQ キーワード検索（ローカル辞書）
  │     ヒット → FAQ 回答を返す
  │
  ├─ Bedrock（Claude 3 Haiku）に問い合わせ
  │     成功 → AI 回答を返す
  │
  └─ フォールバック → エスカレーション文言
```

---

## セットアップ手順

### 1. SSM Parameter Store にトークンを保存

```bash
aws ssm put-parameter \
  --name "/bedrock-agent/dev/slack-bot-token" \
  --value "xoxb-xxxxxxxxxxxx" \
  --type SecureString

aws ssm put-parameter \
  --name "/bedrock-agent/dev/slack-signing-secret" \
  --value "xxxxxxxxxxxxxxxx" \
  --type SecureString
```

> Web UI のみで使う場合はダミー値（`xoxb-dummy` / `dummy-secret`）で OK

### 2. Terraform でデプロイ

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 3. Streamlit Web UI を起動

```bash
cd app
pip install -r requirements.txt
aws-vault exec <profile> -- streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。

---

## プロジェクト構成

```
aws-bedrock-agent/
├── app/
│   ├── app.py              # Streamlit Web UI（メインフロントエンド）
│   └── requirements.txt
├── lambda/
│   └── index.py            # Lambda 関数（FAQ検索 + Bedrock呼び出し）
├── terraform/
│   ├── main.tf             # Lambda / IAM / Function URL / CloudWatch
│   ├── variables.tf
│   ├── outputs.tf
│   ├── provider.tf
│   └── terraform.tfvars.example
├── docs/
│   ├── architecture.drawio
│   ├── architecture.drawio.png
│   └── screenshots/        # デモ画面スクショ
└── README.md
```

---

## セキュリティ上の注意点

| 項目 | 対応状況 | TODO |
|-----|---------|------|
| トークン管理 | SSM Parameter Store（SecureString） | ローテーション設定を追加 |
| IAM 最小権限 | Bedrock・SSM のみ許可 | モデル ARN を特定のものに絞る |
| Slack 署名検証 | 実装済み（Web UI使用時はスキップ） | Slack 連携時に有効化 |
| ログの個人情報 | 質問の先頭50文字のみ記録 | 本番では更に制限する |

---

## 推定コスト（月額）

| リソース | 単価 | 月間想定 | 小計 |
|---------|------|---------|------|
| Lambda | $0.0000002/リクエスト | 1,000回 | ~$0.01 |
| Bedrock Claude 3 Haiku | $0.00025/1K input tokens | 1,000回×200tokens | ~$0.05 |
| CloudWatch Logs | $0.76/GB | 最小 | ~$0.01 |
| **合計** | | | **~$0.10/月** |

---

## 今後の拡張ポイント

| 拡張項目 | 内容 |
|---------|------|
| RAG 連携 | Bedrock Knowledge Bases で社内ドキュメントを検索 |
| Slack 連携 | Webhook 受け口を追加するだけで対応可能 |
| FAQ 管理 | DynamoDB で FAQ を管理・更新 |
| 回答ログ | DynamoDB に保存して未回答パターンを分析 |
| 認証追加 | Cognito で Web UI にログイン機能を追加 |

---

## 後片付け

```bash
cd terraform
terraform destroy

# SSM パラメータは手動削除
aws ssm delete-parameter --name "/bedrock-agent/dev/slack-bot-token"
aws ssm delete-parameter --name "/bedrock-agent/dev/slack-signing-secret"
```

---

*このプロジェクトは学習・PoC 目的で作成しました。本番導入時は認証強化・監視・エラー通知の追加が必要です。*
