"""
aws-bedrock-agent: 社内FAQ自動応答 Lambda（MVP実装）

処理フロー:
  1. Slack から Webhook リクエストを受信
  2. 署名検証（セキュリティ）
  3. FAQ キーワード検索（ローカル辞書）
  4. FAQ で見つからない場合 → Bedrock に問い合わせ
  5. 回答不能な場合 → エスカレーション文言を返す
  6. Slack に返信

TODO:
  - FAQデータを S3 または DynamoDB に移行する
  - Bedrock Knowledge Bases（RAG）と連携して精度を上げる
  - 回答ログを DynamoDB に保存して改善サイクルを回す
  - PoCの評価指標（一次回答完結率）を計測する仕組みを追加
"""

import json
import logging
import os
import hashlib
import hmac
import time

import boto3
from botocore.exceptions import ClientError

# ── ロガー設定 ─────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ── 定数 ──────────────────────────────────────────────────
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
)
SLACK_BOT_TOKEN_SSM_PATH = os.environ.get(
    "SLACK_BOT_TOKEN_SSM_PATH", "/bedrock-agent/dev/slack-bot-token"
)
SLACK_SIGNING_SECRET_SSM_PATH = os.environ.get(
    "SLACK_SIGNING_SECRET_SSM_PATH", "/bedrock-agent/dev/slack-signing-secret"
)

# フォールバック文言（回答できない場合）
FALLBACK_MESSAGE = (
    "申し訳ありません、この質問にはお答えできませんでした。\n"
    "担当者にご確認ください。"
)

# ── FAQ データ（MVP: ローカル辞書） ────────────────────────
# TODO: S3 の CSV や DynamoDB に移行して、メンテナンスしやすくする
# TODO: FAQ 品質が回答品質を左右する。定期的に見直す
FAQ_DATA = {
    "有給": "有給休暇の申請は社内ポータル > 勤怠管理から行えます。申請は取得日の3営業日前までにお願いします。",
    "経費": "経費精算は月末締めです。領収書と申請フォームを総務部に提出してください。",
    "リモート": "リモートワークは週3日まで可能です。事前に上長への報告が必要です。",
    "パスワード": "パスワードリセットは IT ヘルプデスク（内線: 1234）までご連絡ください。",
    "福利厚生": "福利厚生の詳細は社内ポータル > 人事 > 福利厚生ページをご覧ください。",
}


# ── Bedrock クライアント ────────────────────────────────────
def get_bedrock_client():
    """
    Bedrock クライアントを生成する。
    TODO: リージョンを環境変数で切り替えられるようにする
    TODO: Bedrock が使えない場合は USE_DUMMY_BEDROCK=true で切り替える
    """
    use_dummy = os.environ.get("USE_DUMMY_BEDROCK", "false").lower() == "true"
    if use_dummy:
        return None  # ダミーモード（後述の invoke_bedrock でハンドリング）
    return boto3.client("bedrock-runtime", region_name="ap-northeast-1")


# ── SSM クライアント ───────────────────────────────────────
def get_ssm_parameter(ssm_client: boto3.client, path: str) -> str:
    """SSM Parameter Store から値を取得する"""
    try:
        response = ssm_client.get_parameter(Name=path, WithDecryption=True)
        return response["Parameter"]["Value"]
    except ClientError as e:
        logger.error(f"SSM パラメータ取得失敗: {path} / {e}")
        return ""


# ── FAQ 検索 ───────────────────────────────────────────────
def search_faq(question: str) -> str | None:
    """
    FAQ データからキーワードマッチで回答を検索する。
    見つかれば回答文字列を、見つからなければ None を返す。

    TODO: 完全一致ではなく類似度検索（embeddings）に切り替える
    TODO: FAQ データを外部ストレージ（S3/DynamoDB）から動的に読み込む
    """
    for keyword, answer in FAQ_DATA.items():
        if keyword in question:
            logger.info(f"FAQ ヒット: keyword={keyword}")
            return answer
    return None


# ── Bedrock 呼び出し ───────────────────────────────────────
def invoke_bedrock(client, question: str) -> str:
    """
    Bedrock（Claude）に質問を投げて回答を取得する。
    クライアントが None（ダミーモード）の場合はダミー応答を返す。

    TODO: system prompt を改善して回答品質を上げる
    TODO: 個人情報・機密情報を含む質問を事前にフィルタリングする
    TODO: トークン数を監視してコスト増加を検知する
    """
    # ダミーモード（Bedrock が使えない環境向け）
    if client is None:
        logger.warning("ダミーモードで応答します")
        return f"【ダミー応答】「{question}」についての回答です。（Bedrock 未接続）"

    system_prompt = """あなたは社内FAQアシスタントです。
社員からの質問に簡潔・丁寧に回答してください。
分からない場合は「担当部署にご確認ください」と伝えてください。
個人情報や機密情報には触れないでください。"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": question}
        ]
    })

    try:
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        answer = result["content"][0]["text"]
        logger.info(f"Bedrock 応答成功: model={BEDROCK_MODEL_ID}")
        return answer

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        logger.error(f"Bedrock 呼び出しエラー: {error_code} / {e}")

        if error_code == "AccessDeniedException":
            return "現在 AI 機能が利用できません。担当者にご連絡ください。"
        elif error_code == "ThrottlingException":
            return "現在リクエストが集中しています。しばらくしてから再度お試しください。"
        else:
            return FALLBACK_MESSAGE


# ── Slack 署名検証 ─────────────────────────────────────────
def verify_slack_signature(signing_secret: str, headers: dict, body: str) -> bool:
    """
    Slack からのリクエストが正規のものか署名で検証する。
    TODO: 本番では必ずこの検証を有効にする（なりすまし防止）
    """
    timestamp = headers.get("x-slack-request-timestamp", "")
    slack_signature = headers.get("x-slack-signature", "")

    # リプレイ攻撃防止: 5分以上古いリクエストを拒否
    if abs(time.time() - int(timestamp)) > 300:
        logger.warning("Slack リクエストのタイムスタンプが古すぎます")
        return False

    base_string = f"v0:{timestamp}:{body}"
    my_signature = (
        "v0="
        + hmac.new(
            signing_secret.encode(),
            base_string.encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(my_signature, slack_signature)


# ── メイン処理 ─────────────────────────────────────────────
def process_question(question: str) -> str:
    """
    質問を受け取り、以下の順で回答を生成する:
      1. FAQ キーワード検索
      2. Bedrock（LLM）への問い合わせ
      3. フォールバック（回答不能）

    TODO: 回答結果（質問・回答・ヒット種別）を DynamoDB に保存して
          一次回答完結率を計測する
    """
    logger.info(f"質問受信: {question[:50]}...")  # 先頭50文字のみログ出力

    # Step 1: FAQ 検索
    faq_answer = search_faq(question)
    if faq_answer:
        return f"📚 *FAQ より回答します*\n\n{faq_answer}"

    # Step 2: Bedrock に問い合わせ
    bedrock_client = get_bedrock_client()
    bedrock_answer = invoke_bedrock(bedrock_client, question)
    if bedrock_answer and bedrock_answer != FALLBACK_MESSAGE:
        return f"🤖 *AI が回答します*\n\n{bedrock_answer}"

    # Step 3: フォールバック
    logger.warning(f"回答不能: {question[:50]}...")
    return f"❓ {FALLBACK_MESSAGE}"


# ── Lambda ハンドラー ──────────────────────────────────────
def handler(event: dict, context) -> dict:
    """
    Lambda エントリーポイント。
    Slack の Event API / Slash Command からのリクエストを処理する。

    TODO: Slack の URL 確認（challenge）に対応する
    TODO: Slack の retry リクエストを検知して重複処理を防ぐ
    TODO: 処理を非同期化して Slack の 3 秒タイムアウトに対応する
          （SQS や Lambda の非同期呼び出しを使う）
    """
    logger.info("Lambda 起動")

    # ── Slack URL 確認（初回設定時） ───────────────────────
    body_str = event.get("body", "{}")
    try:
        body = json.loads(body_str)
    except json.JSONDecodeError:
        logger.error("リクエストボディの JSON パース失敗")
        return {"statusCode": 400, "body": "Bad Request"}

    # Slack URL 確認チャレンジ
    if body.get("type") == "url_verification":
        return {
            "statusCode": 200,
            "body": json.dumps({"challenge": body.get("challenge")}),
        }

    # ── 署名検証（本番では必ず有効化） ────────────────────
    # TODO: SSM からトークンを取得するコストを減らすため
    #       Lambda の初期化フェーズでキャッシュする
    skip_verification = os.environ.get("SKIP_SLACK_VERIFICATION", "false").lower() == "true"
    if not skip_verification:
        ssm_client = boto3.client("ssm", region_name="ap-northeast-1")
        signing_secret = get_ssm_parameter(ssm_client, SLACK_SIGNING_SECRET_SSM_PATH)
        headers = event.get("headers", {})
        if not verify_slack_signature(signing_secret, headers, body_str):
            logger.warning("Slack 署名検証失敗")
            return {"statusCode": 401, "body": "Unauthorized"}

    # ── 質問テキストの取得 ─────────────────────────────────
    # Slack Event API 形式
    question = ""
    if "event" in body:
        slack_event = body["event"]
        event_type = slack_event.get("type", "")

        # Bot 自身のメッセージは無視
        if slack_event.get("bot_id"):
            return {"statusCode": 200, "body": "ok"}

        if event_type == "message":
            question = slack_event.get("text", "")
        elif event_type == "app_mention":
            question = slack_event.get("text", "")

    # Slash Command 形式
    elif "text" in body:
        question = body.get("text", "")

    # テスト用（直接呼び出し）
    elif "question" in body:
        question = body.get("question", "")

    if not question:
        return {"statusCode": 200, "body": "ok"}

    # ── 回答生成 ───────────────────────────────────────────
    answer = process_question(question)

    # ── Slack への返信 ─────────────────────────────────────
    # TODO: slack_sdk を使って実際に Slack チャンネルに投稿する
    # import slack_sdk
    # ssm_client = boto3.client("ssm")
    # bot_token = get_ssm_parameter(ssm_client, SLACK_BOT_TOKEN_SSM_PATH)
    # slack_client = slack_sdk.WebClient(token=bot_token)
    # slack_client.chat_postMessage(
    #     channel=body["event"]["channel"],
    #     text=answer,
    #     thread_ts=body["event"].get("ts"),  # スレッド返信
    # )

    logger.info(f"回答生成完了: {answer[:50]}...")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"answer": answer}, ensure_ascii=False),
    }
