"""
validate_agent.py ユニットテスト

Bedrock クライアントをモックして AWS 接続なしで動作を検証する。
実行: pytest scripts/test_validate_agent.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))

import validate_agent as va

# ── check_agent_status テスト ─────────────────────────────────────


class TestCheckAgentStatus:
    def test_正常系_エージェント情報が返る(self) -> None:
        mock_response = {
            "agent": {
                "agentId": "ABCD1234",
                "agentName": "test-agent",
                "agentStatus": "PREPARED",
                "foundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "description": "テスト用エージェント",
            }
        }
        with patch.object(va.client, "get_agent", return_value=mock_response):
            result = va.check_agent_status("ABCD1234")

        assert result["agentId"] == "ABCD1234"
        assert result["agentName"] == "test-agent"
        assert result["agentStatus"] == "PREPARED"
        assert result["foundationModel"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"

    def test_descriptionが未設定の場合は空文字が返る(self) -> None:
        mock_response = {
            "agent": {
                "agentId": "ABCD1234",
                "agentName": "test-agent",
                "agentStatus": "PREPARED",
            }
        }
        with patch.object(va.client, "get_agent", return_value=mock_response):
            result = va.check_agent_status("ABCD1234")

        assert result["description"] == ""
        assert result["foundationModel"] == "N/A"

    def test_ClientError発生時は例外が伝播する(self) -> None:
        with patch.object(
            va.client,
            "get_agent",
            side_effect=ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": ""}},
                "GetAgent",
            ),
        ):
            with pytest.raises(ClientError):
                va.check_agent_status("INVALID")


# ── check_action_groups テスト ────────────────────────────────────


class TestCheckActionGroups:
    def test_正常系_Action_Groupsリストが返る(self) -> None:
        mock_response = {
            "actionGroupSummaries": [
                {
                    "actionGroupId": "ag-001",
                    "actionGroupName": "faq-group",
                    "actionGroupState": "ENABLED",
                },
                {
                    "actionGroupId": "ag-002",
                    "actionGroupName": "search-group",
                    "actionGroupState": "DISABLED",
                },
            ]
        }
        with patch.object(
            va.client, "list_agent_action_groups", return_value=mock_response
        ):
            result = va.check_action_groups("ABCD1234")

        assert len(result) == 2
        assert result[0]["actionGroupName"] == "faq-group"
        assert result[0]["actionGroupState"] == "ENABLED"
        assert result[1]["actionGroupState"] == "DISABLED"

    def test_Action_Groupsが空の場合は空リストが返る(self) -> None:
        with patch.object(
            va.client,
            "list_agent_action_groups",
            return_value={"actionGroupSummaries": []},
        ):
            result = va.check_action_groups("ABCD1234")

        assert result == []

    def test_DRAFT_バージョンで呼ばれる(self) -> None:
        with patch.object(
            va.client,
            "list_agent_action_groups",
            return_value={"actionGroupSummaries": []},
        ) as mock_call:
            va.check_action_groups("ABCD1234")
            call_kwargs = mock_call.call_args[1]
            assert call_kwargs["agentVersion"] == "DRAFT"


# ── check_aliases テスト ──────────────────────────────────────────


class TestCheckAliases:
    def test_正常系_エイリアスリストが返る(self) -> None:
        mock_response = {
            "agentAliasSummaries": [
                {
                    "agentAliasId": "alias-001",
                    "agentAliasName": "prod",
                    "agentAliasStatus": "PREPARED",
                }
            ]
        }
        with patch.object(va.client, "list_agent_aliases", return_value=mock_response):
            result = va.check_aliases("ABCD1234")

        assert len(result) == 1
        assert result[0]["aliasName"] == "prod"
        assert result[0]["aliasStatus"] == "PREPARED"

    def test_エイリアスが空の場合は空リストが返る(self) -> None:
        with patch.object(
            va.client,
            "list_agent_aliases",
            return_value={"agentAliasSummaries": []},
        ):
            result = va.check_aliases("ABCD1234")

        assert result == []


# ── validate テスト ───────────────────────────────────────────────


class TestValidate:
    def _setup_mocks(
        self,
        status: str = "PREPARED",
        action_groups: list | None = None,
        aliases: list | None = None,
    ) -> None:
        if action_groups is None:
            action_groups = [
                {
                    "actionGroupId": "ag-1",
                    "actionGroupName": "faq",
                    "actionGroupState": "ENABLED",
                }
            ]
        if aliases is None:
            aliases = [
                {
                    "agentAliasId": "a-1",
                    "agentAliasName": "prod",
                    "agentAliasStatus": "PREPARED",
                }
            ]

        va.client.get_agent = MagicMock(
            return_value={
                "agent": {
                    "agentId": "ABCD1234",
                    "agentName": "test",
                    "agentStatus": status,
                }
            }
        )
        va.client.list_agent_action_groups = MagicMock(
            return_value={"actionGroupSummaries": action_groups}
        )
        va.client.list_agent_aliases = MagicMock(
            return_value={"agentAliasSummaries": aliases}
        )

    def test_PREPARED_ステータスで全チェック通過しTrueを返す(self) -> None:
        self._setup_mocks(status="PREPARED")
        result = va.validate("ABCD1234")
        assert result is True

    def test_VERSIONED_ステータスもTrueを返す(self) -> None:
        self._setup_mocks(status="VERSIONED")
        result = va.validate("ABCD1234")
        assert result is True

    def test_NOT_PREPARED_ステータスでFalseを返す(self) -> None:
        self._setup_mocks(status="CREATING")
        result = va.validate("ABCD1234")
        assert result is False

    def test_Action_Groupsが空の場合はFalseを返す(self) -> None:
        self._setup_mocks(action_groups=[])
        result = va.validate("ABCD1234")
        assert result is False

    def test_エイリアスが空の場合はFalseを返す(self) -> None:
        self._setup_mocks(aliases=[])
        result = va.validate("ABCD1234")
        assert result is False

    def test_get_agent_がClientErrorの場合はFalseを返す(self) -> None:
        va.client.get_agent = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": ""}},
                "GetAgent",
            )
        )
        result = va.validate("INVALID")
        assert result is False


# ── main テスト ───────────────────────────────────────────────────


class TestMain:
    def test_AGENT_IDが未設定の場合はSystemExitが発生する(self) -> None:
        with patch.dict(os.environ, {}, clear=True):

            with patch.object(va, "AGENT_ID", ""):
                with pytest.raises(SystemExit) as exc_info:
                    va.main()
                assert exc_info.value.code == 1

    def test_validateが成功した場合は終了コード0(self) -> None:
        with patch.object(va, "AGENT_ID", "ABCD1234"):
            with patch("validate_agent.validate", return_value=True):
                with pytest.raises(SystemExit) as exc_info:
                    va.main()
                assert exc_info.value.code == 0

    def test_validateが失敗した場合は終了コード1(self) -> None:
        with patch.object(va, "AGENT_ID", "ABCD1234"):
            with patch("validate_agent.validate", return_value=False):
                with pytest.raises(SystemExit) as exc_info:
                    va.main()
                assert exc_info.value.code == 1
