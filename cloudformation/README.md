# CloudFormation 版 Bedrock Agent スタック

`terraform/` の Terraform 版と同等の構成を CloudFormation で実装したテンプレートです。

## Terraform との最大の差異

| 比較項目 | Terraform | CloudFormation |
|---|---|---|
| Action Group の定義 | `aws_bedrockagent_agent_action_group` として**別リソース** | `AWS::Bedrock::Agent` の `ActionGroups:` に**インライン定義** |
| Agent の準備（PREPARE） | 変更後に手動 or CLI で実行が必要 | `AutoPrepare: true` で自動化 |
| Lambda コードのパッケージング | `data "archive_file"` で自動 zip 化 | S3 に手動アップロードが必要 |
| IAM ポリシー | `aws_iam_role_policy` × 3（別リソース） | `Policies:` リストで 1 リソースに集約 |

## 構成リソース

| リソース | CFn タイプ |
|---|---|
| Lambda 関数（FAQ 応答 + Bedrock 呼び出し） | `AWS::Lambda::Function` |
| Lambda Function URL（Slack Webhook 受け口） | `AWS::Lambda::Url` |
| DynamoDB テーブル（質問ログ） | `AWS::DynamoDB::Table` |
| IAM ロール（Lambda 実行用） | `AWS::IAM::Role` |
| IAM ロール（Bedrock Agent 実行用） | `AWS::IAM::Role` |
| Bedrock Agent + Action Groups × 2 | `AWS::Bedrock::Agent` |
| CloudWatch Logs グループ | `AWS::Logs::LogGroup` |

## デプロイ前の準備

### 1. SSM Parameter Store にシークレットを登録

```bash
# Slack Bot Token
aws ssm put-parameter \
  --name "/bedrock-agent/dev/slack-bot-token" \
  --value "xoxb-xxxx-xxxx" \
  --type SecureString

# Slack Signing Secret
aws ssm put-parameter \
  --name "/bedrock-agent/dev/slack-signing-secret" \
  --value "xxxx" \
  --type SecureString
```

### 2. Lambda コードを S3 にアップロード

`Code.ZipFile` はプレースホルダーです。実際のコードは S3 経由でデプロイします。

```bash
# zip 作成
cd lambda/
zip -r ../lambda.zip .

# S3 にアップロード
aws s3 cp ../lambda.zip s3://<YOUR_BUCKET>/bedrock-agent/lambda.zip
```

`template.yaml` の `Code:` セクションを以下に変更してください:

```yaml
Code:
  S3Bucket: <YOUR_BUCKET>
  S3Key: bedrock-agent/lambda.zip
```

### 3. Bedrock モデルのアクセス許可

AWS コンソール → Amazon Bedrock → モデルアクセス で `Claude 3.5 Haiku` を有効化してください。

## デプロイ方法

### テンプレートの検証

```bash
aws cloudformation validate-template \
  --template-body file://template.yaml
```

### スタックの作成

```bash
aws cloudformation create-stack \
  --stack-name bedrock-agent-dev \
  --template-body file://template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=ProjectName,ParameterValue=bedrock-agent \
    ParameterKey=Environment,ParameterValue=dev
```

> `--capabilities CAPABILITY_NAMED_IAM` は IAM リソース（named role）作成に必須です。

### スタックの更新

```bash
aws cloudformation update-stack \
  --stack-name bedrock-agent-dev \
  --template-body file://template.yaml \
  --capabilities CAPABILITY_NAMED_IAM
```

### スタックの削除

```bash
# DynamoDB 削除保護を先に解除
aws dynamodb update-table \
  --table-name bedrock-agent-dev-questions \
  --deletion-protection-enabled false

aws cloudformation delete-stack --stack-name bedrock-agent-dev
```

## トラブルシューティング

### `CAPABILITY_NAMED_IAM` エラー

IAM リソースに `RoleName` を指定しているため、このフラグが必須です。
`create-stack` / `update-stack` の引数に `--capabilities CAPABILITY_NAMED_IAM` を追加してください。

### Bedrock Agent が `NOT_PREPARED` 状態のまま

`AutoPrepare: true` を設定していますが、Action Group の Lambda ARN 変更後に
自動 PREPARE が走らないことがあります。その場合はコンソールまたは CLI で手動実行:

```bash
aws bedrock-agent prepare-agent \
  --agent-id <AGENT_ID>
```

### Lambda Function URL に接続できない

`FunctionUrlPublicPermission` リソースが作成されているか確認してください。
CFn スタックのイベントに `CREATE_COMPLETE` が表示されていれば問題ありません。
