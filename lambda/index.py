"""
aws-bedrock-agent: Bedrock Agent Action Group ハンドラー

処理フロー:
  1. Bedrock Agent から Action Group の関数呼び出しを受信
  2. parameters から question を取得
  3. FAQ キーワード検索
  4. 結果を Bedrock Agent の形式で返す
"""

import logging
import os
from typing import Any, Dict

import boto3

# ── ロガー設定 ─────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ── FAQ データ ─────────────────────────────────────────────
# TODO: S3 または DynamoDB に移行してメンテナンス性を上げる
FAQ_DATA = {
    "有給": "有給休暇の申請は社内ポータル > 勤怠管理から行えます。申請は取得日の3営業日前までにお願いします。",
    "経費": "経費精算は月末締めです。領収書と申請フォームを総務部に提出してください。",
    "リモート": "リモートワークは週3日まで可能です。事前に上長への報告が必要です。",
    "パスワード": "パスワードリセットは IT ヘルプデスク（内線: 1234）までご連絡ください。",
    "福利厚生": "福利厚生の詳細は社内ポータル > 人事 > 福利厚生ページをご覧ください。",
}


# ── FAQ 検索 ───────────────────────────────────────────────
def search_faq(question: str) -> str:
    """キーワードマッチで FAQ を検索する"""
    for keyword, answer in FAQ_DATA.items():
        if keyword in question:
            logger.info(f"FAQ ヒット: keyword={keyword}")
            return answer
    return "該当するFAQが見つかりませんでした。担当部署にご確認ください。"


# ── Lambda ハンドラー（Bedrock Agent Action Group 形式） ────
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Bedrock Agent Action Group のエントリーポイント。
    Agent が search-faq 関数を呼び出す際にこのハンドラーが実行される。
    """
    logger.info(f"Action Group 呼び出し: {event.get('actionGroup')} / {event.get('function')}")

    try:
        action_group = event["actionGroup"]
        function = event["function"]
        message_version = event.get("messageVersion", 1)
        parameters = event.get("parameters", [])

        # パラメータから question を取得
        question = ""
        for param in parameters:
            if param.get("name") == "question":
                question = param.get("value", "")
                break

        logger.info(f"質問受信: {question[:50]}")
        answer = search_faq(question)

        response = {
            "response": {
                "actionGroup": action_group,
                "function": function,
                "functionResponse": {
                    "responseBody": {"TEXT": {"body": answer}}
                },
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
                        "TEXT": {"body": "エラーが発生しました。担当部署にご確認ください。"}
                    }
                },
            },
            "messageVersion": event.get("messageVersion", 1),
        }
