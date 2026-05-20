# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.2.0] - 2026-05-19

### Added
- Action Group の追加方法・Lambda 単体テスト手順を README に追記
- CONTRIBUTING.md 追加（PR プロセス・スタイルガイド）

### Changed
- Claude 3 Haiku → Claude 3.5 Haiku（`anthropic.claude-3-5-haiku-20241022-v1:0`）に移行（EOL: 2026-09-10）

## [1.1.0] - 2026-05-13

### Added
- FAQ データを Lambda コードから切り離し DynamoDB で管理する構成に変更（v1.1.0〜）
  - `scripts/seed_faq.py` で初期データ投入
  - モジュールレベルキャッシュによる高速応答（コールドスタート時 1 回のみ Scan）
- CloudFormation テンプレート追加（`cloudformation/template.yaml`）
  - Bedrock Agent / Action Groups / Lambda / DynamoDB / IAM を CFn で一括管理
  - `AutoPrepare: true` で Agent 変更後の自動 PREPARE を実現
- SECURITY.md 追加
- README にトラブルシューティング・ローカル開発テスト方法セクション追加

### Fixed
- `boto3.resource("dynamodb")` を呼び出しごとに生成していた問題を修正
  → モジュールトップレベルで初期化するように変更
- `route_function()` の `if/elif` チェーンをディスパッチテーブル（dict）にリファクタリング
- `.gitignore` に `.ruff_cache` / `.pytest_cache` を追加

## [1.0.0] - 2026-03-18

### Added
- 初回実装：Amazon Bedrock Agent + Action Groups による社内 FAQ ボット
  - Action Group 1: `faq-search`（FAQ キーワード検索 + DynamoDB 記録）
  - Action Group 2: `log-question`（DynamoDB に明示的記録）
- Streamlit Web UI（boto3 経由で Bedrock Agent Runtime を呼び出し）
- Terraform IaC（Bedrock Agent / Lambda / DynamoDB / IAM）
- GitHub Actions CI（Python lint + Checkov セキュリティスキャン）
