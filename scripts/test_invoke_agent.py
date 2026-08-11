"""
invoke_agent.py ユニットテスト

Bedrock Agent Runtime クライアントをモックして AWS 接続なしで動作を検証する。
実行: pytest scripts/test_invoke_agent.py -v
"""

from __future__ import annotations

import os
import re
import sys
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))

import invoke_agent as ia

# ── extract_answer テスト ─────────────────────────────────────────


class TestExtractAnswer:
    def test_単一チャンクのテキストを抽出できる(self) -> None:
        completion = [{"chunk": {"bytes": "有給の申請方法です。".encode()}}]
        result = ia.extract_answer(completion)
        assert result == "有給の申請方法です。"

    def test_複数チャンクを順に結合できる(self) -> None:
        completion = [
            {"chunk": {"bytes": b"Hello "}},
            {"chunk": {"bytes": b"World"}},
        ]
        result = ia.extract_answer(completion)
        assert result == "Hello World"

    def test_chunkキーのないイベントはスキップされる(self) -> None:
        completion = [
            {"trace": {"some": "trace_data"}},
            {"chunk": {"bytes": "回答".encode()}},
        ]
        result = ia.extract_answer(completion)
        assert result == "回答"

    def test_空のcompletionは空文字列を返す(self) -> None:
        result = ia.extract_answer([])
        assert result == ""

    def test_日本語バイト列を正しくデコードできる(self) -> None:
        text = "社内ポータルから申請できます。"
        completion = [{"chunk": {"bytes": text.encode("utf-8")}}]
        result = ia.extract_answer(completion)
        assert result == text


# ── build_session_id テスト ──────────────────────────────────────


class TestBuildSessionId:
    def test_Noneの場合はUUID形式のIDが返る(self) -> None:
        result = ia.build_session_id(None)
        assert re.match(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            result,
        )

    def test_指定したsession_idをそのまま返す(self) -> None:
        sid = "my-session-123"
        result = ia.build_session_id(sid)
        assert result == "my-session-123"

    def test_空文字の場合もUUIDが生成される(self) -> None:
        result = ia.build_session_id("")
        # UUID 形式は "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"（36文字）
        assert len(result) == 36


# ── invoke_agent テスト ──────────────────────────────────────────


class TestInvokeAgent:
    def _make_mock_client(self, chunks: list[bytes]) -> MagicMock:
        """invoke_agent のレスポンスを返す mock クライアントを作成する"""
        mock_client = MagicMock()
        completion = [{"chunk": {"bytes": c}} for c in chunks]
        mock_client.invoke_agent.return_value = {"completion": iter(completion)}
        return mock_client

    def test_正常系_回答テキストが返る(self) -> None:
        mock_client = self._make_mock_client(["有給".encode()])
        with patch("invoke_agent.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            result = ia.invoke_agent("有給の申請は？", "agent-id", "alias-id")
        assert result == "有給"

    def test_空文字の質問はValueErrorを発生させる(self) -> None:
        with pytest.raises(ValueError, match="空にできません"):
            ia.invoke_agent("", "agent-id", "alias-id")

    def test_スペースのみの質問はValueErrorを発生させる(self) -> None:
        with pytest.raises(ValueError):
            ia.invoke_agent("   ", "agent-id", "alias-id")

    def test_空の回答はデフォルトメッセージを返す(self) -> None:
        mock_client = self._make_mock_client([])
        with patch("invoke_agent.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            result = ia.invoke_agent("テスト", "agent-id", "alias-id")
        assert result == "回答を取得できませんでした。"

    def test_ClientErrorは再raiseされる(self) -> None:
        mock_client = MagicMock()
        mock_client.invoke_agent.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": ""}},
            "InvokeAgent",
        )
        with patch("invoke_agent.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            with pytest.raises(ClientError):
                ia.invoke_agent("有給", "agent-id", "alias-id")

    def test_session_id省略時にUUIDがAgentに渡される(self) -> None:
        mock_client = self._make_mock_client([b"ok"])
        with patch("invoke_agent.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            ia.invoke_agent("テスト", "agent-id", "alias-id", session_id=None)
        call_kwargs = mock_client.invoke_agent.call_args[1]
        assert re.match(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            call_kwargs["sessionId"],
        )


# ── format_output テスト ─────────────────────────────────────────


class TestFormatOutput:
    def test_質問が出力に含まれる(self) -> None:
        result = ia.format_output(
            "有給の申請方法は？", "社内ポータルから申請できます。"
        )
        assert "有給の申請方法は？" in result

    def test_回答が出力に含まれる(self) -> None:
        result = ia.format_output("質問", "回答テキスト")
        assert "回答テキスト" in result

    def test_区切り線が含まれる(self) -> None:
        result = ia.format_output("Q", "A")
        assert "─" in result

    def test_日本語が含まれても正常動作する(self) -> None:
        result = ia.format_output("リモートワークの規定は？", "週3日まで可能です。")
        assert isinstance(result, str)
        assert "リモートワークの規定は？" in result
