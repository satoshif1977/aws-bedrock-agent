"""
aws-bedrock-agent: Bedrock Agent Action Group ハンドラー

Action Groups:
  - faq-search  / search-faq    : FAQ キーワード検索
  - log-question / log-question : 質問・回答を DynamoDB に記録

ログとメトリクスは同梱の共通ユーティリティ（logger.py / metrics.py）を通す。
標準 logging のままだと機密情報のマスキングが効かず、利用者の質問文が
そのまま CloudWatch Logs に残ってしまうため、構造化ロガーに統一している。
リトライの発生も on_retry フック経由でログ・メトリクス化する。
"""

import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError
from logger import StructuredLogger, create_logger_from_env, retry_logger
from metrics import MetricsCollector, create_metrics_from_env, retry_metrics
from retry import RetryConfig, retry_call

# ── 定数 ──────────────────────────────────────────────────
# AWS_REGION は Lambda 予約済み環境変数（AWS が自動でセット）
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "bedrock-agent-dev-questions")
FAQ_TABLE = os.environ.get("FAQ_TABLE", "bedrock-agent-dev-faq")

# 名前空間は環境変数で上書きできるが、未設定でも本リポジトリの値に落ちるようにする
DEFAULT_METRICS_NAMESPACE = "AwsBedrockAgent/ActionGroup"

# ── AWS クライアント（モジュールレベルでキャッシュ・コールドスタート最適化） ──
_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE)
_faq_table = _dynamodb.Table(FAQ_TABLE)

# ── リトライ設定 ──────────────────────────────────────────
# DynamoDB のスロットリング・一時的なサーバエラーに対する再試行設定。
# 指数バックオフ + フルジッターで最大3回まで試行する。
# テストからは RETRY_SLEEP を差し替えることで実待機なしに検証できる。
RETRY_CONFIG = RetryConfig(max_attempts=3, base_delay=0.2, max_delay=2.0)
RETRY_SLEEP = time.sleep


# ── ロガー / メトリクス ────────────────────────────────────
def _default_logger() -> StructuredLogger:
    """環境変数 LOG_LEVEL から構造化ロガーを組み立てる。"""
    return create_logger_from_env()


def _default_metrics() -> MetricsCollector:
    """EMF メトリクスコレクタを組み立てる。

    METRICS_NAMESPACE 未設定でも本ハンドラーの名前空間に落ちるようにしておく。
    """
    env = dict(os.environ)
    env["METRICS_NAMESPACE"] = env.get("METRICS_NAMESPACE") or DEFAULT_METRICS_NAMESPACE
    return create_metrics_from_env(env, Handler="bedrock-agent-action-group")


def _make_retry_hook(
    log: StructuredLogger,
    mx: MetricsCollector,
    operation: str,
) -> Callable[[int, float, BaseException], None]:
    """retry_call の on_retry に渡すコールバックを作る。

    ログとメトリクスの両方に流す。片方だけだと「件数は見えるが原因が分からない」
    「原因は分かるが頻度が追えない」のどちらかになるため。
    """
    to_log = retry_logger(log, operation)
    to_metrics = retry_metrics(mx, operation)

    def on_retry(attempt: int, delay_seconds: float, exc: BaseException) -> None:
        to_log(attempt, delay_seconds, exc)
        to_metrics(attempt, delay_seconds, exc)

    return on_retry


def call_aws(
    func,
    *args,
    operation: str = "aws",
    log: StructuredLogger | None = None,
    mx: MetricsCollector | None = None,
    **kwargs,
):
    """AWS API 呼び出しを共通のリトライ設定で実行する。

    リトライ不能なエラーと、試行回数を使い切った場合の失敗は、
    元の例外をそのまま送出する（呼び出し側の except ClientError を変えないため）。
    log / mx を渡すとリトライの発生が記録される。
    """
    on_retry = None
    if log is not None and mx is not None:
        on_retry = _make_retry_hook(log, mx, operation)
    return retry_call(
        func,
        *args,
        config=RETRY_CONFIG,
        sleep=RETRY_SLEEP,
        on_retry=on_retry,
        **kwargs,
    )


# ── FAQ キャッシュ（ウォームスタート時は DynamoDB を省略） ──
_FAQ_CACHE: dict[str, str] | None = None


def _load_faq(
    log: StructuredLogger | None = None,
    mx: MetricsCollector | None = None,
) -> dict[str, str]:
    """DynamoDB から FAQ データを取得してキャッシュする（コールドスタート時のみ実行）"""
    global _FAQ_CACHE
    log = log or _default_logger()
    mx = mx or _default_metrics()

    if _FAQ_CACHE is not None:
        mx.add_metric("FaqCacheHit", 1, unit="Count")
        return _FAQ_CACHE

    try:
        with mx.timer("FaqScanLatency"):
            response = call_aws(_faq_table.scan, operation="faq_scan", log=log, mx=mx)
        _FAQ_CACHE = {
            item["keyword"]: item["answer"] for item in response.get("Items", [])
        }
        log.info("FAQ キャッシュ構築完了", faq_count=len(_FAQ_CACHE))
        mx.add_metric("FaqCacheBuilt", 1, unit="Count")
        mx.add_metric("FaqCacheSize", len(_FAQ_CACHE), unit="Count")
    except ClientError as e:
        log.error("FAQ テーブル読み込みエラー", error=e)
        mx.add_metric("FaqLoadError", 1, unit="Count")
        _FAQ_CACHE = {}
    return _FAQ_CACHE


# ── FAQ 検索 ───────────────────────────────────────────────
def search_faq(
    question: str,
    log: StructuredLogger | None = None,
    mx: MetricsCollector | None = None,
) -> str:
    """キーワードマッチで FAQ を検索し、結果を DynamoDB に自動記録する"""
    log = log or _default_logger()
    mx = mx or _default_metrics()

    answer = "該当するFAQが見つかりませんでした。担当部署にご確認ください。"
    hit = False
    for keyword, faq_answer in _load_faq(log=log, mx=mx).items():
        if keyword in question:
            # keyword は自社で登録した FAQ の見出しなので出してよい。
            # question は利用者の入力なので長さだけに留める。
            log.info("FAQ ヒット", keyword=keyword)
            answer = faq_answer
            hit = True
            break

    mx.add_metric("FaqHit" if hit else "FaqMiss", 1, unit="Count")

    # FAQ 検索結果を自動記録
    log_question(question, answer, log=log, mx=mx)
    return answer


# ── DynamoDB 記録 ──────────────────────────────────────────
def log_question(
    question: str,
    answer: str,
    log: StructuredLogger | None = None,
    mx: MetricsCollector | None = None,
) -> str:
    """質問と回答を DynamoDB に記録する"""
    log = log or _default_logger()
    mx = mx or _default_metrics()

    item = {
        "question_id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    try:
        with mx.timer("PutItemLatency"):
            call_aws(
                _table.put_item,
                operation="put_item",
                log=log,
                mx=mx,
                Item=item,
            )
        log.info("DynamoDB 記録完了", question_id=item["question_id"])
        mx.add_metric("QuestionLogged", 1, unit="Count")
        return f"記録しました（ID: {item['question_id']}）"
    except ClientError as e:
        log.error("DynamoDB 書き込みエラー", question_id=item["question_id"], error=e)
        mx.add_metric("QuestionLogError", 1, unit="Count")
        return "記録に失敗しました。"


# ── Action Group ルーター ──────────────────────────────────
def route_function(
    function: str,
    parameters: list,
    log: StructuredLogger | None = None,
    mx: MetricsCollector | None = None,
) -> str:
    """function 名に応じて処理を振り分ける（dict ルーティングテーブル方式）"""
    log = log or _default_logger()
    mx = mx or _default_metrics()
    params = {p["name"]: p.get("value", "") for p in parameters}

    def _search_faq() -> str:
        question = params.get("question", "")
        # 利用者の質問文はログに残さない（長さだけ記録する）
        log.info("search-faq 呼び出し", question_length=len(question))
        return search_faq(question, log=log, mx=mx)

    def _log_question() -> str:
        question = params.get("question", "")
        answer = params.get("answer", "")
        log.info("log-question 呼び出し", question_length=len(question))
        return log_question(question, answer, log=log, mx=mx)

    routes: dict[str, Any] = {
        "search-faq": _search_faq,
        "log-question": _log_question,
    }

    handler = routes.get(function)
    if handler:
        return handler()
    log.warn("未知の function", function=function)
    mx.add_metric("UnknownFunction", 1, unit="Count")
    return f"未対応の関数です: {function}"


# ── Lambda ハンドラー（Bedrock Agent Action Group 形式） ────
def handler(
    event: dict[str, Any],
    context: Any,
    logger: StructuredLogger | None = None,
    metrics: MetricsCollector | None = None,
) -> dict[str, Any]:
    """Bedrock Agent Action Group のエントリーポイント

    logger / metrics は差し替え可能にしてある（テストから出力を検証するため）。
    """
    log = logger or _default_logger()
    mx = metrics or _default_metrics()

    try:
        invocation_log = log.child(
            action_group=event.get("actionGroup", ""),
            function=event.get("function", ""),
        )
        invocation_log.info("Action Group 呼び出し")
        mx.add_metric("Invocations", 1, unit="Count")

        action_group = event["actionGroup"]
        function = event["function"]
        message_version = event.get("messageVersion", 1)
        parameters = event.get("parameters", [])

        answer = route_function(function, parameters, log=invocation_log, mx=mx)

        response = {
            "response": {
                "actionGroup": action_group,
                "function": function,
                "functionResponse": {"responseBody": {"TEXT": {"body": answer}}},
            },
            "messageVersion": message_version,
        }

        # 応答本文は FAQ の回答＝社内情報なので、長さだけ残す
        invocation_log.info("応答完了", answer_length=len(answer))
        mx.add_metric("Success", 1, unit="Count")
        return response

    except Exception as e:
        log.error("ハンドラーでエラー", error=e)
        mx.add_metric("HandlerError", 1, unit="Count")
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
    finally:
        # 1 実行につき 1 回だけ EMF ドキュメントを吐く
        mx.flush()
