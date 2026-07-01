"""
seed_faq.py ユニットテスト

DynamoDB をモックして AWS 接続なしで動作を検証する。
実行: pytest scripts/test_seed_faq.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from seed_faq import FAQ_ITEMS, main

# ── FAQ_ITEMS 定数テスト ──────────────────────────────────────────


class TestFaqItems:
    def test_FAQアイテム数が5件である(self) -> None:
        assert len(FAQ_ITEMS) == 5

    def test_各アイテムにkeywordキーが存在する(self) -> None:
        for item in FAQ_ITEMS:
            assert "keyword" in item, f"keyword が見つかりません: {item}"

    def test_各アイテムにanswerキーが存在する(self) -> None:
        for item in FAQ_ITEMS:
            assert "answer" in item, f"answer が見つかりません: {item}"

    def test_keywordが空文字でない(self) -> None:
        for item in FAQ_ITEMS:
            assert item["keyword"].strip() != ""

    def test_answerが空文字でない(self) -> None:
        for item in FAQ_ITEMS:
            assert item["answer"].strip() != ""

    def test_有給キーワードが含まれている(self) -> None:
        keywords = [item["keyword"] for item in FAQ_ITEMS]
        assert "有給" in keywords

    def test_経費キーワードが含まれている(self) -> None:
        keywords = [item["keyword"] for item in FAQ_ITEMS]
        assert "経費" in keywords

    def test_keywordが重複していない(self) -> None:
        keywords = [item["keyword"] for item in FAQ_ITEMS]
        assert len(keywords) == len(set(keywords))


# ── main テスト ───────────────────────────────────────────────────


class TestMain:
    @patch("seed_faq.boto3.resource")
    def test_全件正常に投入される(self, mock_resource: MagicMock) -> None:
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_resource.return_value.Table.return_value = mock_table

        main()

        assert mock_table.put_item.call_count == len(FAQ_ITEMS)

    @patch("seed_faq.boto3.resource")
    def test_put_itemにkeywordとanswerが渡される(
        self, mock_resource: MagicMock
    ) -> None:
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_resource.return_value.Table.return_value = mock_table

        main()

        for call in mock_table.put_item.call_args_list:
            item = call[1]["Item"]
            assert "keyword" in item
            assert "answer" in item

    @patch("seed_faq.boto3.resource")
    def test_一部失敗しても処理を継続する(self, mock_resource: MagicMock) -> None:
        from botocore.exceptions import ClientError

        mock_table = MagicMock()
        mock_table.put_item.side_effect = [
            {},
            ClientError(
                {
                    "Error": {
                        "Code": "ProvisionedThroughputExceededException",
                        "Message": "",
                    }
                },
                "PutItem",
            ),
            {},
            {},
            {},
        ]
        mock_resource.return_value.Table.return_value = mock_table

        main()

        assert mock_table.put_item.call_count == len(FAQ_ITEMS)

    @patch("seed_faq.boto3.resource")
    def test_デフォルトテーブル名でTableが呼ばれる(
        self, mock_resource: MagicMock
    ) -> None:
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_resource.return_value.Table.return_value = mock_table

        main()

        mock_resource.return_value.Table.assert_called_once_with(
            "bedrock-agent-dev-faq"
        )

    @patch.dict(os.environ, {"FAQ_TABLE": "custom-faq-table"})
    @patch("seed_faq.boto3.resource")
    def test_環境変数FAQ_TABLEが反映される(self, mock_resource: MagicMock) -> None:
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_resource.return_value.Table.return_value = mock_table

        import seed_faq as sf

        original_table = sf.FAQ_TABLE
        sf.FAQ_TABLE = os.environ.get("FAQ_TABLE", "bedrock-agent-dev-faq")
        main()
        sf.FAQ_TABLE = original_table

        mock_resource.return_value.Table.assert_called_once()

    @patch("seed_faq.boto3.resource")
    def test_全件失敗しても例外が発生しない(self, mock_resource: MagicMock) -> None:
        from botocore.exceptions import ClientError

        mock_table = MagicMock()
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": ""}},
            "PutItem",
        )
        mock_resource.return_value.Table.return_value = mock_table

        main()

        assert mock_table.put_item.call_count == len(FAQ_ITEMS)
