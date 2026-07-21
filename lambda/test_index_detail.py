"""
aws-bedrock-agent Lambda 詳細ユニットテスト

_load_faq / search_faq / log_question / route_function / handler の
境界値・フィールド内容・キャッシュ挙動を検証する。
"""

from __future__ import annotations

import re
from unittest.mock import patch

import index
import pytest
from botocore.exceptions import ClientError
from index import _load_faq, handler, log_question, route_function, search_faq

# ── フィクスチャ ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_faq_cache():
    """各テスト前後に _FAQ_CACHE をリセットしてテスト間の干渉を防ぐ"""
    index._FAQ_CACHE = None
    yield
    index._FAQ_CACHE = None


# ── _load_faq 詳細 ────────────────────────────────────────


class TestLoadFaqDetail:
    def test_キャッシュがある場合はDynamoDB呼び出しをスキップする(self):
        index._FAQ_CACHE = {"有給": "答え"}
        with patch("index._faq_table") as mock_table:
            result = _load_faq()
            mock_table.scan.assert_not_called()
        assert result == {"有給": "答え"}

    def test_スキャン結果がkeywordをキーとしたdictになる(self):
        mock_items = [
            {"keyword": "有給", "answer": "社内ポータルから"},
            {"keyword": "経費", "answer": "月末締め"},
        ]
        with patch("index._faq_table") as mock_table:
            mock_table.scan.return_value = {"Items": mock_items}
            result = _load_faq()
        assert result["有給"] == "社内ポータルから"
        assert result["経費"] == "月末締め"

    def test_スキャン後にキャッシュが設定される(self):
        mock_items = [{"keyword": "テスト", "answer": "答え"}]
        with patch("index._faq_table") as mock_table:
            mock_table.scan.return_value = {"Items": mock_items}
            _load_faq()
        assert index._FAQ_CACHE is not None

    def test_ClientErrorで空dictが返る(self):
        with patch("index._faq_table") as mock_table:
            mock_table.scan.side_effect = ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": ""}},
                "Scan",
            )
            result = _load_faq()
        assert result == {}


# ── search_faq 詳細 ───────────────────────────────────────


class TestSearchFaqDetail:
    @patch("index._load_faq", return_value={"有給": "有給回答"})
    @patch("index.log_question")
    def test_log_questionに正しい質問が渡される(self, mock_log, mock_faq):
        search_faq("有給を申請したい")
        call_question = mock_log.call_args[0][0]
        assert call_question == "有給を申請したい"

    @patch("index._load_faq", return_value={"有給": "有給回答"})
    @patch("index.log_question")
    def test_ヒット時のanswerがlog_questionに渡される(self, mock_log, mock_faq):
        search_faq("有給申請の方法")
        call_answer = mock_log.call_args[0][1]
        assert call_answer == "有給回答"

    @patch("index._load_faq", return_value={"有給": "有給回答"})
    @patch("index.log_question")
    def test_マッチしない場合はデフォルトメッセージがlog_questionに渡される(
        self, mock_log, mock_faq
    ):
        search_faq("全く関係ない質問")
        call_answer = mock_log.call_args[0][1]
        assert "該当するFAQが見つかりませんでした" in call_answer

    @patch("index._load_faq", return_value={"有給": "回答A"})
    @patch("index.log_question")
    def test_ヒット時は正しいanswerが返る(self, mock_log, mock_faq):
        result = search_faq("有給申請について")
        assert result == "回答A"

    @patch("index._load_faq", return_value={})
    @patch("index.log_question")
    def test_空文字の質問でもエラーなく動作する(self, mock_log, mock_faq):
        result = search_faq("")
        assert "該当するFAQが見つかりませんでした" in result


# ── log_question 詳細 ──────────────────────────────────────


class TestLogQuestionDetail:
    @patch("index._table")
    def test_question_idがUUID形式である(self, mock_table):
        mock_table.put_item.return_value = {}
        log_question("質問", "回答")
        item = mock_table.put_item.call_args[1]["Item"]
        assert re.match(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            item["question_id"],
        )

    @patch("index._table")
    def test_timestampがISO形式でUTCオフセットを含む(self, mock_table):
        mock_table.put_item.return_value = {}
        log_question("質問", "回答")
        item = mock_table.put_item.call_args[1]["Item"]
        assert re.match(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*\+00:00",
            item["timestamp"],
        )

    @patch("index._table")
    def test_返り値にIDが含まれる(self, mock_table):
        mock_table.put_item.return_value = {}
        result = log_question("質問", "回答")
        assert "記録しました" in result
        assert "ID:" in result

    @patch("index._table")
    def test_成功時はput_itemが1回だけ呼ばれる(self, mock_table):
        mock_table.put_item.return_value = {}
        log_question("質問A", "回答A")
        assert mock_table.put_item.call_count == 1

    @patch("index._table")
    def test_questionとanswerがItemに正しく格納される(self, mock_table):
        mock_table.put_item.return_value = {}
        log_question("テスト質問", "テスト回答")
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["question"] == "テスト質問"
        assert item["answer"] == "テスト回答"


# ── route_function 詳細 ────────────────────────────────────


class TestRouteFunctionDetail:
    @patch("index.search_faq", return_value="FAQ回答")
    def test_valueが省略された場合は空文字がデフォルト(self, mock_search):
        route_function("search-faq", [{"name": "question"}])
        mock_search.assert_called_once_with("")

    @patch("index.log_question", return_value="記録")
    def test_log_questionでquestionとanswerが正しく渡される(self, mock_log):
        params = [
            {"name": "question", "value": "Q"},
            {"name": "answer", "value": "A"},
        ]
        route_function("log-question", params)
        mock_log.assert_called_once_with("Q", "A")

    def test_未知functionは関数名を含むエラーメッセージを返す(self):
        result = route_function("nonexistent-function", [])
        assert "未対応の関数" in result
        assert "nonexistent-function" in result


# ── handler 詳細 ──────────────────────────────────────────


class TestHandlerDetail:
    @patch("index.route_function", return_value="テスト回答")
    def test_messageVersionのデフォルト値は1(self, mock_route):
        event = {
            "actionGroup": "test-group",
            "function": "search-faq",
            "parameters": [],
            # messageVersion なし
        }
        result = handler(event, None)
        assert result["messageVersion"] == 1

    @patch("index.route_function", return_value="回答")
    def test_parametersがroute_functionに渡される(self, mock_route):
        params = [{"name": "question", "value": "テスト"}]
        event = {
            "actionGroup": "group",
            "function": "search-faq",
            "parameters": params,
        }
        handler(event, None)
        mock_route.assert_called_once_with("search-faq", params)

    @patch("index.route_function", return_value="回答")
    def test_レスポンスのfunctionが入力と一致する(self, mock_route):
        event = {
            "actionGroup": "faq-group",
            "function": "log-question",
            "parameters": [],
        }
        result = handler(event, None)
        assert result["response"]["function"] == "log-question"

    def test_異常系でmessageVersionがeventからフォールバックされる(self):
        # actionGroup キーなし → KeyError → except で event.get() でフォールバック
        event = {"function": "search-faq", "messageVersion": 2}
        result = handler(event, None)
        assert result["messageVersion"] == 2
