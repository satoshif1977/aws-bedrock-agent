#!/usr/bin/env python3
"""
FAQ DynamoDB シードスクリプト

DynamoDB の FAQ テーブルに初期データを投入する。
terraform apply 後に一度だけ実行すればよい。

使い方:
    aws-vault exec personal-dev-source -- python scripts/seed_faq.py

環境変数:
    FAQ_TABLE   : FAQ テーブル名（デフォルト: bedrock-agent-dev-faq）
    AWS_REGION  : リージョン（デフォルト: ap-northeast-1）
"""

import os
import sys

import boto3
from botocore.exceptions import ClientError

FAQ_TABLE = os.environ.get("FAQ_TABLE", "bedrock-agent-dev-faq")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

FAQ_ITEMS = [
    {
        "keyword": "有給",
        "answer": "有給休暇の申請は社内ポータル > 勤怠管理から行えます。申請は取得日の3営業日前までにお願いします。",
    },
    {
        "keyword": "経費",
        "answer": "経費精算は月末締めです。領収書と申請フォームを総務部に提出してください。",
    },
    {
        "keyword": "リモート",
        "answer": "リモートワークは週3日まで可能です。事前に上長への報告が必要です。",
    },
    {
        "keyword": "パスワード",
        "answer": "パスワードリセットは IT ヘルプデスク（内線: 1234）までご連絡ください。",
    },
    {
        "keyword": "福利厚生",
        "answer": "福利厚生の詳細は社内ポータル > 人事 > 福利厚生ページをご覧ください。",
    },
]


def main() -> None:
    print(f"FAQ シード開始: テーブル={FAQ_TABLE} / リージョン={REGION}")
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(FAQ_TABLE)

    success = 0
    for item in FAQ_ITEMS:
        try:
            table.put_item(Item=item)
            print(f"  [OK] {item['keyword']}")
            success += 1
        except ClientError as e:
            print(f"  [NG] {item['keyword']}: {e}", file=sys.stderr)

    print(f"\n完了: {success}/{len(FAQ_ITEMS)} 件を {FAQ_TABLE} に登録しました。")


if __name__ == "__main__":
    main()
