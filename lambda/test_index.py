"""
aws-bedrock-agent Lambda ユニットテスト

DynamoDB 呼び出しをモックし、AWS 接続なしでビジネスロジックを検証する。
"""

from unittest.mock import patch

from index import handler, route_function, search_faq


# ── search_faq テスト ─────────────────────────────────────
class TestSearchFaq:
    @patch("index.log_question")
    def test_有給キーワードでFAQが返る(self, mock_log):
        result = search_faq("有給休暇を申請したい")
        assert "社内ポータル" in result
        assert "勤怠管理" in result
        mock_log.assert_called_once()

    @patch("index.log_question")
    def test_経費キーワードでFAQが返る(self, mock_log):
        result = search_faq("経費精算の方法を教えて")
        assert "月末締め" in result
        mock_log.assert_called_once()

    @patch("index.log_question")
    def test_マッチしない場合はデフォルトメッセージ(self, mock_log):
        result = search_faq("全く関係ない質問")
        assert "該当するFAQが見つかりませんでした" in result
        mock_log.assert_called_once()


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
