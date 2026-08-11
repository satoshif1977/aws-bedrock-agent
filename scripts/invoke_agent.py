#!/usr/bin/env python3
"""
Bedrock Agent CLI 呼び出しスクリプト

Bedrock Agent Runtime を通じて Agent を CLI から呼び出す。
Streamlit UI を起動せずにコマンドラインから素早く動作確認できる。

使い方:
    aws-vault exec personal-dev-source -- \\
        AGENT_ID=XXXXXXXX AGENT_ALIAS_ID=YYYYYYYY \\
        python scripts/invoke_agent.py "有給の申請方法は？"

環境変数:
    AGENT_ID         : Bedrock Agent の ID（必須）
    AGENT_ALIAS_ID   : Agent Alias ID（必須）
    AWS_REGION       : リージョン（デフォルト: ap-northeast-1）
"""

from __future__ import annotations

import os
import sys
import uuid

import boto3
from botocore.exceptions import ClientError

# ── 設定 ─────────────────────────────────────────────────────

REGION: str = os.environ.get("AWS_REGION", "ap-northeast-1")
AGENT_ID: str = os.environ.get("AGENT_ID", "")
AGENT_ALIAS_ID: str = os.environ.get("AGENT_ALIAS_ID", "")


# ── コア関数 ──────────────────────────────────────────────────


def extract_answer(completion) -> str:
    """
    invoke_agent のストリーミングレスポンスから回答テキストを抽出する。

    Args:
        completion: response["completion"] のイテラブル

    Returns:
        結合した回答テキスト。チャンクが存在しない場合は空文字列を返す。
    """
    answer = ""
    for event in completion:
        if "chunk" in event:
            answer += event["chunk"]["bytes"].decode("utf-8")
    return answer


def build_session_id(session_id: str | None = None) -> str:
    """
    セッション ID を返す。未指定または空文字の場合は UUID v4 を自動生成する。

    Args:
        session_id: 既存のセッション ID（省略可）

    Returns:
        セッション ID 文字列
    """
    return session_id if session_id else str(uuid.uuid4())


def invoke_agent(
    question: str,
    agent_id: str,
    agent_alias_id: str,
    session_id: str | None = None,
    region: str = REGION,
) -> str:
    """
    Bedrock Agent に質問を送り、回答テキストを返す。

    Args:
        question       : ユーザーからの質問文
        agent_id       : Bedrock Agent ID
        agent_alias_id : Agent Alias ID
        session_id     : セッション ID（省略時は自動生成）
        region         : AWS リージョン

    Returns:
        Agent の回答テキスト。回答が空の場合はデフォルトメッセージを返す。

    Raises:
        ValueError  : question が空または空白のみの場合
        ClientError : AWS API 呼び出し失敗
    """
    if not question.strip():
        raise ValueError("question は空にできません")

    sid = build_session_id(session_id)
    client = boto3.client("bedrock-agent-runtime", region_name=region)

    response = client.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=sid,
        inputText=question,
    )

    answer = extract_answer(response["completion"])
    return answer if answer else "回答を取得できませんでした。"


def format_output(question: str, answer: str) -> str:
    """
    質問と回答を表示用にフォーマットする。

    Args:
        question: ユーザーの質問
        answer  : Agent の回答

    Returns:
        フォーマット済み文字列（区切り線付き）
    """
    sep = "─" * 50
    return f"\n{sep}\n質問: {question}\n{sep}\n回答:\n{answer}\n{sep}"


# ── エントリーポイント ────────────────────────────────────────


def main() -> None:
    if not AGENT_ID or not AGENT_ALIAS_ID:
        print("[ERROR] 環境変数 AGENT_ID と AGENT_ALIAS_ID が必要です", file=sys.stderr)
        print(
            "  例: AGENT_ID=XXXXXXXX AGENT_ALIAS_ID=YYYYYYYY "
            "python scripts/invoke_agent.py '有給の申請方法は？'",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(sys.argv) < 2:
        print("[ERROR] 質問を引数で指定してください", file=sys.stderr)
        print(
            "  例: python scripts/invoke_agent.py '有給の申請方法は？'",
            file=sys.stderr,
        )
        sys.exit(1)

    question = sys.argv[1]
    print(f"Bedrock Agent 呼び出し: AGENT_ID={AGENT_ID} / ALIAS={AGENT_ALIAS_ID}")

    try:
        answer = invoke_agent(question, AGENT_ID, AGENT_ALIAS_ID)
        print(format_output(question, answer))
    except ClientError as e:
        print(f"[ERROR] AWS エラー: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"[ERROR] 入力エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
