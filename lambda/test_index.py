"""
aws-bedrock-agent Lambda ユニットテスト

DynamoDB 呼び出しをモックし、AWS 接続なしでビジネスロジックを検証する。
"""

from unittest.mock import patch

import index
import pytest
from botocore.exceptions import ClientError
from index import handler, log_question, route_function, search_faq

# ── テスト用 FAQ データ ────────────────────────────────────
MOCK_FAQ = {
    "有給": "有給休暇の申請は社内ポータル > 勤怠管理から行えます。申請は取得日の3営業日前までにお願いします。",
    "経費": "経費精算は月末締めです。領収書と申請フォームを総務部に提出してください。",
    "リモート": "リモートワークは週3日まで可能です。事前に上長への報告が必要です。",
    "パスワード": "パスワードリセットは IT ヘルプデスク（内線: 1234）までご連絡ください。",
    "福利厚生": "福利厚生の詳細は社内ポータル > 人事 > 福利厚生ページをご覧ください。",
}


@pytest.fixture(autouse=True)
def reset_faq_cache():
    """各テスト前後に _FAQ_CACHE をリセットしてテスト間の干渉を防ぐ"""
    index._FAQ_CACHE = None
    yield
    index._FAQ_CACHE = None


# ── search_faq テスト ─────────────────────────────────────
class TestSearchFaq:
    @patch("index._load_faq", return_value=MOCK_FAQ)
    @patch("index.log_question")
    def test_有給キーワードでFAQが返る(self, mock_log, mock_faq):
        result = search_faq("有給休暇を申請したい")
        assert "社内ポータル" in result
        assert "勤怠管理" in result
        mock_log.assert_called_once()

    @patch("index._load_faq", return_value=MOCK_FAQ)
    @patch("index.log_question")
    def test_経費キーワードでFAQが返る(self, mock_log, mock_faq):
        result = search_faq("経費精算の方法を教えて")
        assert "月末締め" in result
        mock_log.assert_called_once()

    @patch("index._load_faq", return_value=MOCK_FAQ)
    @patch("index.log_question")
    def test_マッチしない場合はデフォルトメッセージ(self, mock_log, mock_faq):
        result = search_faq("全く関係ない質問")
        assert "該当するFAQが見つかりませんでした" in result
        mock_log.assert_called_once()

    @patch("index._load_faq", return_value={})
    @patch("index.log_question")
    def test_FAQテーブルが空でもデフォルトメッセージを返す(self, mock_log, mock_faq):
        result = search_faq("有給を申請したい")
        assert "該当するFAQが見つかりませんでした" in result


# ── route_function テスト ─────────────────────────────────
class TestRouteFunction:
    @patch("index.search_faq", return_value="FAQ回答")
    def test_search_faqルーティング(self, mock_search):
        result = route_function("search-faq", [{"name": "question", "value": "有給"}])
        assert result == "FAQ回答"
        mock_search.assert_called_once_with("有給")

    @patch("index.log_question", return_value="記録しました")
    def test_log_questionルーティング(self, mock_log):
        params = [
            {"name": "question", "value": "質問"},
            {"name": "answer", "value": "回答"},
        ]
        result = route_function("log-question", params)
        assert result == "記録しました"
        mock_log.assert_called_once_with("質問", "回答")

    def test_未知のfunctionはエラーメッセージ(self):
        result = route_function("unknown-function", [])
        assert "未対応の関数" in result


# ── handler テスト ────────────────────────────────────────
class TestHandler:
    @patch("index.route_function", return_value="テスト回答")
    def test_正常系レスポンス構造(self, mock_route):
        event = {
            "actionGroup": "faq-group",
            "function": "search-faq",
            "messageVersion": 1,
            "parameters": [{"name": "question", "value": "有給"}],
        }
        result = handler(event, None)

        assert result["response"]["actionGroup"] == "faq-group"
        assert result["response"]["function"] == "search-faq"
        assert result["messageVersion"] == 1
        body = result["response"]["functionResponse"]["responseBody"]["TEXT"]["body"]
        assert body == "テスト回答"

    def test_異常系はエラーメッセージを返す(self):
        # actionGroup キーが欠けたイベントで KeyError を発生させる
        event = {"function": "search-faq"}
        result = handler(event, None)
        body = result["response"]["functionResponse"]["responseBody"]["TEXT"]["body"]
        assert "エラー" in body


# ── log_question テスト ───────────────────────────────────
class TestLogQuestion:
    @patch("index._table")
    def test_正常系_DynamoDBに記録される(self, mock_table):
        mock_table.put_item.return_value = {}
        result = log_question("有給申請の方法は？", "社内ポータルから申請できます。")
        assert "記録しました" in result
        mock_table.put_item.assert_called_once()
        # put_item に渡されたアイテムの構造を検証
        call_args = mock_table.put_item.call_args[1]["Item"]
        assert call_args["question"] == "有給申請の方法は？"
        assert call_args["answer"] == "社内ポータルから申請できます。"
        assert "question_id" in call_args
        assert "timestamp" in call_args

    @patch("index._table")
    def test_DynamoDB書き込みエラーは失敗メッセージを返す(self, mock_table):
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": ""}},
            "PutItem",
        )
        result = log_question("質問", "回答")
        assert "失敗" in result
