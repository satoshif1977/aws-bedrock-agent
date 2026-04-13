# aws-bedrock-agent

社内FAQや業務問い合わせの一次対応を自動化する PoC です。
**Amazon Bedrock Agent** と **Action Groups** を活用し、複数のツールを自律的に使い分けながら回答・記録まで自動化します。

---

## デモ画面

| Streamlit Web UI | Action Groups 構成 |
|---|---|
| ![Streamlit デモ画面](docs/screenshots/demo_streamlit.png) | ![Action Groups](docs/screenshots/demo_agent_action_groups.png) |

**DynamoDB への自動記録（質問ログ）**

![DynamoDB Records](docs/screenshots/demo_dynamodb_records.png)

---

## アーキテクチャ

```
ユーザー（ブラウザ）
  ↓
Streamlit Web UI（boto3）
  ↓
Amazon Bedrock Agent（Claude 3 Haiku）
  ├── Action Group 1: faq-search
  │     └── Lambda → FAQ キーワード検索 → DynamoDB に自動記録
  └── Action Group 2: log-question
        └── Lambda → DynamoDB に明示的に記録
```

### AWS 構成図

```mermaid
graph TD
    A[ユーザー ブラウザ] -->|質問| B[Streamlit Web UI]
    B -->|invoke_agent| C[Amazon Bedrock Agent]
    C -->|自律判断| D[Action Group 1: faq-search]
    C -->|自律判断| E[Action Group 2: log-question]
    D --> F[Lambda: FAQ キーワード検索]
    E --> F
    F -->|回答| C
    F -->|自動記録| G[(DynamoDB)]
    C -->|回答| B
    F --> H[CloudWatch Logs]
```

---

## 想定する社内業務

| 業務 | 現状の課題 | このシステムでの改善 |
|---|---|---|
| 社内FAQ問い合わせ | 担当者が毎回同じ質問に答える | 一次回答を自動化・担当者の工数削減 |
| 新入社員のオンボーディング | ルールや手続きが分散して探しにくい | Web UI で即座に回答 |
| IT ヘルプデスク | 問い合わせが集中して対応が遅れる | よくある質問を自動解決・ログで傾向分析 |

---

## 技術的なポイント・工夫

### Bedrock Agent の自律判断
LLM が「どのツールを使うか」を自律的に判断します。固定ロジックではなく、Agent が状況に応じて Action Group を選択します。

### Lambda 内での原子的処理
FAQ 検索と同時に DynamoDB への記録も Lambda 内で完結させる設計にしています。小さいモデル（Claude 3 Haiku）では複数ツールの連続呼び出しが不安定なケースがあるため、**信頼性を優先して Lambda 側で処理を完結**させています。

### IaC による再現性
Bedrock Agent・Action Groups・DynamoDB・Lambda・IAM をすべて Terraform で管理。コマンド一発で同じ環境を再現できます。

---

## プロジェクト構成

```
aws-bedrock-agent/
├── app/
│   ├── app.py              # Streamlit Web UI（Bedrock Agent Runtime 呼び出し）
│   └── requirements.txt
├── lambda/
│   └── index.py            # Action Group ハンドラー（FAQ検索 + DynamoDB記録）
├── terraform/
│   ├── main.tf             # Bedrock Agent / Action Groups / Lambda / DynamoDB / IAM
│   ├── variables.tf
│   ├── outputs.tf
│   ├── provider.tf
│   └── terraform.tfvars.example
├── docs/
│   ├── architecture.drawio
│   └── screenshots/
└── README.md
```

---

## セットアップ手順

### 1. Terraform でデプロイ

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

デプロイ後、以下が出力されます：

```
bedrock_agent_id    = "XXXXXXXXXX"
dynamodb_table_name = "bedrock-agent-dev-questions"
lambda_function_name = "bedrock-agent-dev"
```

### 2. Streamlit Web UI を起動

```bash
cd app
pip install -r requirements.txt
aws-vault exec <profile> -- streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。

---

## FAQ キーワード一覧

| キーワード | 回答内容 |
|---|---|
| 有給 | 有給休暇の申請方法（社内ポータル・3営業日前） |
| 経費 | 経費精算の締め日・提出先 |
| リモート | リモートワークのルール（週3日・事前報告） |
| パスワード | IT ヘルプデスクへの連絡方法 |
| 福利厚生 | 社内ポータルの参照先 |

---

## 推定コスト（月額）

| リソース | 月間想定 | 小計 |
|---|---|---|
| Bedrock Agent 呼び出し | 1,000回 | ~$1.00 |
| Lambda | 1,000回 | ~$0.01 |
| DynamoDB（オンデマンド） | 最小 | ~$0.01 |
| CloudWatch Logs | 最小 | ~$0.01 |
| **合計** | | **~$1〜3/月** |

---

## セキュリティ上の注意点

| 項目 | 対応状況 |
|---|---|
| IAM 最小権限 | Lambda・Bedrock Agent それぞれに専用ロールを付与 |
| DynamoDB アクセス制御 | Lambda ロールに PutItem/GetItem のみ許可 |
| ログの個人情報 | 質問の先頭50文字のみログ出力 |
| Bedrock Agent 権限 | 特定モデル ARN に限定したポリシーを適用 |

---

## 今後の拡張ポイント

| 拡張項目 | 内容 |
|---|---|
| Knowledge Base 連携 | Bedrock Knowledge Bases で社内ドキュメントを RAG 検索 |
| Slack 連携 | Webhook 受け口を追加するだけで対応可能 |
| AgentCore Policy | ツール呼び出しに細粒度アクセス制御を追加 |
| 未回答分析 | DynamoDB のログから未回答パターンを可視化 |
| Cognito 認証 | Web UI にログイン機能を追加 |

---

## 後片付け

```bash
cd terraform
terraform destroy
```

---

*このプロジェクトは学習・PoC 目的で作成しました。本番導入時は認証強化・監視・エラー通知の追加が必要です。*
