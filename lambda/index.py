"""
aws-bedrock-agent: Bedrock Agent Action Group ハンドラー

Action Groups:
  - faq-search  / search-faq    : FAQ キーワード検索
  - log-question / log-question : 質問・回答を DynamoDB に記録
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

# ── ロガー設定 ─────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ── 定数 ──────────────────────────────────────────────────
# AWS_REGION は Lambda 予約済み環境変数（AWS が自動でセット）
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "bedrock-agent-dev-questions")

# ── FAQ データ ─────────────────────────────────────────────
FAQ_DATA = {
    "有給": "有給休暇の申請は社内ポータル > 勤怠管理から行えます。申請は取得日の3営業日前までにお願いします。",
    "経費": "経費精算は月末締めです。領収書と申請フォームを総務部に提出してください。",
    "リモート": "リモートワークは週3日まで可能です。事前に上長への報告が必要です。",
    "パスワード": "パスワードリセットは IT ヘルプデスク（内線: 1234）までご連絡ください。",
    "福利厚生": "福利厚生の詳細は社内ポータル > 人事 > 福利厚生ページをご覧ください。",
}


# ── FAQ 検索 ───────────────────────────────────────────────
def search_faq(question: str) -> str:
    """キーワードマッチで FAQ を検索し、結果を DynamoDB に自動記録する"""
    answer = "該当するFAQが見つかりませんでした。担当部署にご確認ください。"
    for keyword, faq_answer in FAQ_DATA.items():
        if keyword in question:
            logger.info(f"FAQ ヒット: keyword={keyword}")
            answer = faq_answer
            break

    # FAQ 検索結果を自動記録
    log_question(question, answer)
    return answer


# ── DynamoDB 記録 ──────────────────────────────────────────
def log_question(question: str, answer: str) -> str:
    """質問と回答を DynamoDB に記録する"""
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)

    item = {
        "question_id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        table.put_item(Item=item)
        logger.info(f"DynamoDB 記録完了: question_id={item['question_id']}")
        return f"記録しました（ID: {item['question_id']}）"
    except ClientError as e:
        logger.error(f"DynamoDB 書き込みエラー: {e}")
        return "記録に失敗しました。"


# ── Action Group ルーター ──────────────────────────────────
def route_function(function: str, parameters: list) -> str:
    """function 名に応じて処理を振り分ける"""
    params = {p["name"]: p.get("value", "") for p in parameters}

    if function == "search-faq":
        question = params.get("question", "")
        logger.info(f"search-faq 呼び出し: question={question[:50]}")
        return search_faq(question)

    elif function == "log-question":
        question = params.get("question", "")
        answer = params.get("answer", "")
        logger.info(f"log-question 呼び出し: question={question[:50]}")
        return log_question(question, answer)

    else:
        logger.warning(f"未知の function: {function}")
        return f"未対応の関数です: {function}"


# ── Lambda ハンドラー（Bedrock Agent Action Group 形式） ────
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Bedrock Agent Action Group のエントリーポイント"""
    logger.info(
        f"Action Group 呼び出し: {event.get('actionGroup')} / {event.get('function')}"
    )

    try:
        action_group = event["actionGroup"]
        function = event["function"]
        message_version = event.get("messageVersion", 1)
        parameters = event.get("parameters", [])

        answer = route_function(function, parameters)

        response = {
            "response": {
                "actionGroup": action_group,
                "function": function,
                "functionResponse": {"responseBody": {"TEXT": {"body": answer}}},
            },
            "messageVersion": message_version,
        }

        logger.info(f"応答完了: {answer[:50]}")
        return response

    except Exception as e:
        logger.error(f"エラー: {str(e)}")
        return {
            "response": {
                "actionGroup": event.get("actionGroup", ""),
                "function": event.get("function", ""),
                "functionResponse": {
                    "responseBody": {
                        "TEXT": {
                            "body": "エラーが発生しました。担当部署にご確認ください。"
                        }
                    }
                },
            },
            "messageVersion": event.get("messageVersion", 1),
        }
