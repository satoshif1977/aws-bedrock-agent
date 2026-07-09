# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.9.0] - 2026-07-10

### Added
- `lambda_go/` Go ユニットテスト 13 件 → 24 件に拡充（詳細ケース追加）
- `scripts/test_seed_faq.py`: pytest 14 件追加（seed_faq スクリプト検証）
- `scripts/test_validate_agent.py`: pytest 17 件追加（validate_agent スクリプト検証）
- `pytest.ini`: `testpaths = lambda scripts` を設定（CI テスト収集範囲を明示）

### Fixed
- `scripts/validate_agent.py`: black フォーマット適用

### Changed
- CI: 全ワークフローの `branches` を `[master]` に統一・Node.js 20 → 22
- Dependabot: `boto3` / `actions/setup-node` v4 → v6 更新

## [1.8.0] - 2026-06-18

### Added
- README に Terraform CI バッジを追加

## [1.7.0] - 2026-06-16

### Changed
- boto3 >=1.43.19 -> >=1.43.29
- codecov/codecov-action v6 -> v7

## [1.6.0] - 2026-06-08

### Added
- `scripts/validate_agent.py`: Bedrock Agent 設定検証スクリプト（Python）
  - エージェント status（PREPARED / VERSIONED）確認・Action Groups 有効状態一覧・エイリアス登録状況を確認
  - 全チェック結果を PASS / FAIL で総合判定
  - 実行: `AGENT_ID=xxx python scripts/validate_agent.py`

### Fixed
- `app/app.py`・`lambda/test_index.py`: black フォーマット適用（コードスタイル統一）

## [1.5.0] - 2026-06-05

### Fixed

- `app/app.py`: import ブロック後の空行を修正（ruff I001）
- `lambda/test_index.py`: 未使用の `MagicMock` import を削除（ruff F401）
- `terraform/main.tf`: `aws_iam_role_policy.ssm` に Checkov `CKV_AWS_290` インラインスキップを追加

## [1.4.0] - 2026-05-27

### Changed

- CI: `actions/setup-python` v5 → v6（Node.js 24 対応）
- CI: `actions/checkout` v4 → v6（Node.js 24 対応）
- CI: `codecov/codecov-action` v5 → v6
- `app/requirements.txt`: `streamlit>=1.32.0` → `>=1.57.0`
- `app/requirements.txt`: `boto3>=1.34.0` → `>=1.43.14`

### Note

- `hashicorp/aws ~> 5.0 → ~> 6.46`（PR#11）は major version のため保留中。v6 移行は動作確認後に適用予定。

## [1.3.0] - 2026-05-25

### Added
- **Bedrock Agent Alias 追加**（DRAFT/バージョン切り替え対応）
  - `aws_bedrockagent_agent_alias.v1`：DRAFT を指向する安定版エイリアス
  - 本番化時は `routing_configuration.agent_version` を数値バージョンに変更するだけで切り替え可能
  - outputs: `bedrock_agent_alias_id` / `bedrock_agent_alias_arn` / `bedrock_agent_alias_invoke_example`
  - InvokeAgent API サンプルコマンドを output に追加

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
