"""
validate_agent.py 詳細ユニットテスト

check_agent_status / check_action_groups / check_aliases / validate の
フィールド変換・引数確認・エラーハンドリングを検証する。
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))

import validate_agent as va

# ── check_agent_status 詳細 ───────────────────────────────


class TestCheckAgentStatusDetail:
    def test_agentIdが引数通りに呼び出される(self):
        mock_response = {
            "agent": {
                "agentId": "XXXX9999",
                "agentName": "my-agent",
                "agentStatus": "PREPARED",
            }
        }
        with patch.object(
            va.client, "get_agent", return_value=mock_response
        ) as mock_get:
            va.check_agent_status("XXXX9999")
            mock_get.assert_called_once_with(agentId="XXXX9999")

    def test_resultに5つのキーが含まれる(self):
        mock_response = {
            "agent": {
                "agentId": "A",
                "agentName": "B",
                "agentStatus": "PREPARED",
                "foundationModel": "claude-3",
                "description": "説明",
            }
        }
        with patch.object(va.client, "get_agent", return_value=mock_response):
            result = va.check_agent_status("A")
        assert set(result.keys()) == {
            "agentId",
            "agentName",
            "agentStatus",
            "foundationModel",
            "description",
        }

    def test_foundationModelが存在する場合は正しく返される(self):
        model_id = "anthropic.claude-3-5-haiku-20241022-v1:0"
        mock_response = {
            "agent": {
                "agentId": "A",
                "agentName": "B",
                "agentStatus": "PREPARED",
                "foundationModel": model_id,
            }
        }
        with patch.object(va.client, "get_agent", return_value=mock_response):
            result = va.check_agent_status("A")
        assert result["foundationModel"] == model_id


# ── check_action_groups 詳細 ─────────────────────────────


class TestCheckActionGroupsDetail:
    def test_agentIdとDRAFTバージョンが渡される(self):
        with patch.object(
            va.client,
            "list_agent_action_groups",
            return_value={"actionGroupSummaries": []},
        ) as mock_call:
            va.check_action_groups("MY-AGENT-ID")
            call_kwargs = mock_call.call_args.kwargs
            assert call_kwargs["agentId"] == "MY-AGENT-ID"
            assert call_kwargs["agentVersion"] == "DRAFT"

    def test_DISABLEDステータスも正しく変換される(self):
        mock_response = {
            "actionGroupSummaries": [
                {
                    "actionGroupId": "ag-001",
                    "actionGroupName": "disabled-group",
                    "actionGroupState": "DISABLED",
                }
            ]
        }
        with patch.object(
            va.client, "list_agent_action_groups", return_value=mock_response
        ):
            result = va.check_action_groups("AGENT")
        assert result[0]["actionGroupState"] == "DISABLED"

    def test_各アイテムに3つのキーが含まれる(self):
        mock_response = {
            "actionGroupSummaries": [
                {
                    "actionGroupId": "ag-001",
                    "actionGroupName": "faq",
                    "actionGroupState": "ENABLED",
                }
            ]
        }
        with patch.object(
            va.client, "list_agent_action_groups", return_value=mock_response
        ):
            result = va.check_action_groups("AGENT")
        assert set(result[0].keys()) == {
            "actionGroupId",
            "actionGroupName",
            "actionGroupState",
        }


# ── check_aliases 詳細 ────────────────────────────────────


class TestCheckAliasesDetail:
    def test_agentIdが引数通りに渡される(self):
        with patch.object(
            va.client,
            "list_agent_aliases",
            return_value={"agentAliasSummaries": []},
        ) as mock_call:
            va.check_aliases("TARGET-AGENT")
            call_kwargs = mock_call.call_args.kwargs
            assert call_kwargs["agentId"] == "TARGET-AGENT"

    def test_複数エイリアスが全件返る(self):
        mock_response = {
            "agentAliasSummaries": [
                {
                    "agentAliasId": "a1",
                    "agentAliasName": "prod",
                    "agentAliasStatus": "PREPARED",
                },
                {
                    "agentAliasId": "a2",
                    "agentAliasName": "staging",
                    "agentAliasStatus": "CREATING",
                },
            ]
        }
        with patch.object(va.client, "list_agent_aliases", return_value=mock_response):
            result = va.check_aliases("AGENT")
        assert len(result) == 2
        assert result[1]["aliasName"] == "staging"

    def test_aliasIdとaliasStatusがresultに含まれる(self):
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
            result = va.check_aliases("AGENT")
        assert result[0]["aliasId"] == "alias-001"
        assert result[0]["aliasStatus"] == "PREPARED"


# ── validate 詳細 ─────────────────────────────────────────


class TestValidateDetail:
    def _setup(
        self,
        status: str = "PREPARED",
        groups: list | None = None,
        aliases: list | None = None,
    ) -> None:
        if groups is None:
            groups = [
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
                    "agentId": "A",
                    "agentName": "test-agent",
                    "agentStatus": status,
                }
            }
        )
        va.client.list_agent_action_groups = MagicMock(
            return_value={"actionGroupSummaries": groups}
        )
        va.client.list_agent_aliases = MagicMock(
            return_value={"agentAliasSummaries": aliases}
        )

    def test_DISABLEDアクショングループがあってもTrueを返す(self):
        # DISABLED は WARN 表示のみ・ok フラグは変えない
        self._setup(
            groups=[
                {
                    "actionGroupId": "ag-1",
                    "actionGroupName": "faq",
                    "actionGroupState": "DISABLED",
                }
            ]
        )
        result = va.validate("A")
        assert result is True

    def test_FAILEDステータスでFalseを返す(self):
        self._setup(status="FAILED")
        result = va.validate("A")
        assert result is False

    def test_Action_GroupsのClientErrorでFalseを返す(self):
        self._setup()
        va.client.list_agent_action_groups = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": ""}},
                "ListAgentActionGroups",
            )
        )
        result = va.validate("A")
        assert result is False

    def test_AliasesのClientErrorでFalseを返す(self):
        self._setup()
        va.client.list_agent_aliases = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": ""}},
                "ListAgentAliases",
            )
        )
        result = va.validate("A")
        assert result is False

    def test_エイリアスのstatusがCREATINGでもFalseにならない(self):
        # エイリアスが存在する限り ok は変わらない（WARN 表示のみ）
        self._setup(
            aliases=[
                {
                    "agentAliasId": "a1",
                    "agentAliasName": "prod",
                    "agentAliasStatus": "CREATING",
                }
            ]
        )
        result = va.validate("A")
        assert result is True
