"""
aws-bedrock-agent: Bedrock Agent Action Group ハンドラー

Action Groups:
  - faq-search  / search-faq    : FAQ キーワード検索
  - log-question / log-question : 質問・回答を DynamoDB に記録
"""

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

# ── ロガー設定 ─────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ── 定数 ──────────────────────────────────────────────────
# AWS_REGION は Lambda 予約済み環境変数（AWS が自動でセット）
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "bedrock-agent-dev-questions")
FAQ_TABLE = os.environ.get("FAQ_TABLE", "bedrock-agent-dev-faq")

# ── AWS クライアント（モジュールレベルでキャッシュ・コールドスタート最適化） ──
_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE)
_faq_table = _dynamodb.Table(FAQ_TABLE)

# ── FAQ キャッシュ（ウォームスタート時は DynamoDB を省略） ──
_FAQ_CACHE: dict[str, str] | None = None


def _load_faq() -> dict[str, str]:
    """DynamoDB から FAQ データを取得してキャッシュする（コールドスタート時のみ実行）"""
    global _FAQ_CACHE
    if _FAQ_CACHE is not None:
        return _FAQ_CACHE
    try:
        response = _faq_table.scan()
        _FAQ_CACHE = {
            item["keyword"]: item["answer"] for item in response.get("Items", [])
        }
        logger.info(f"FAQ キャッシュ構築完了: {len(_FAQ_CACHE)} 件")
    except ClientError as e:
        logger.error(f"FAQ テーブル読み込みエラー: {e}")
        _FAQ_CACHE = {}
    return _FAQ_CACHE


# ── FAQ 検索 ───────────────────────────────────────────────
def search_faq(question: str) -> str:
    """キーワードマッチで FAQ を検索し、結果を DynamoDB に自動記録する"""
    answer = "該当するFAQが見つかりませんでした。担当部署にご確認ください。"
    for keyword, faq_answer in _load_faq().items():
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
    item = {
        "question_id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    try:
        _table.put_item(Item=item)
        logger.info(f"DynamoDB 記録完了: question_id={item['question_id']}")
        return f"記録しました（ID: {item['question_id']}）"
    except ClientError as e:
        logger.error(f"DynamoDB 書き込みエラー: {e}")
        return "記録に失敗しました。"


# ── Action Group ルーター ──────────────────────────────────
def route_function(function: str, parameters: list) -> str:
    """function 名に応じて処理を振り分ける（dict ルーティングテーブル方式）"""
    params = {p["name"]: p.get("value", "") for p in parameters}

    def _search_faq() -> str:
        question = params.get("question", "")
        logger.info(f"search-faq 呼び出し: question={question[:50]}")
        return search_faq(question)

    def _log_question() -> str:
        question = params.get("question", "")
        answer = params.get("answer", "")
        logger.info(f"log-question 呼び出し: question={question[:50]}")
        return log_question(question, answer)

    routes: dict[str, Any] = {
        "search-faq": _search_faq,
        "log-question": _log_question,
    }

    handler = routes.get(function)
    if handler:
        return handler()
    logger.warning(f"未知の function: {function}")
    return f"未対応の関数です: {function}"


# ── Lambda ハンドラー（Bedrock Agent Action Group 形式） ────
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
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
