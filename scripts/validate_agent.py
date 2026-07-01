#!/usr/bin/env python3
"""
Bedrock Agent 設定検証スクリプト

デプロイ済みの Bedrock Agent の状態・Action Groups・エイリアスを確認し、
期待通りに設定されているかを検証する。

使い方:
    aws-vault exec personal-dev-source -- python scripts/validate_agent.py

環境変数:
    AGENT_ID    : Bedrock Agent の ID（必須）
    AWS_REGION  : リージョン（デフォルト: ap-northeast-1）
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import ClientError

# ── 設定 ─────────────────────────────────────────────────────

REGION: str = os.environ.get("AWS_REGION", "ap-northeast-1")
AGENT_ID: str = os.environ.get("AGENT_ID", "")

# ── クライアント ──────────────────────────────────────────────

client = boto3.client("bedrock-agent", region_name=REGION)


# ── ヘルパー関数 ──────────────────────────────────────────────


def check_agent_status(agent_id: str) -> dict:
    """エージェントの基本情報と状態を取得する。"""
    response = client.get_agent(agentId=agent_id)
    agent = response["agent"]
    return {
        "agentId": agent["agentId"],
        "agentName": agent["agentName"],
        "agentStatus": agent["agentStatus"],
        "foundationModel": agent.get("foundationModel", "N/A"),
        "description": agent.get("description", ""),
    }


def check_action_groups(agent_id: str) -> list[dict]:
    """Action Groups の一覧と有効状態を取得する。"""
    response = client.list_agent_action_groups(
        agentId=agent_id,
        agentVersion="DRAFT",
    )
    groups = response.get("actionGroupSummaries", [])
    return [
        {
            "actionGroupId": g["actionGroupId"],
            "actionGroupName": g["actionGroupName"],
            "actionGroupState": g["actionGroupState"],
        }
        for g in groups
    ]


def check_aliases(agent_id: str) -> list[dict]:
    """エイリアス一覧と紐付くバージョンを取得する。"""
    response = client.list_agent_aliases(agentId=agent_id)
    aliases = response.get("agentAliasSummaries", [])
    return [
        {
            "aliasId": a["agentAliasId"],
            "aliasName": a["agentAliasName"],
            "aliasStatus": a["agentAliasStatus"],
        }
        for a in aliases
    ]


def print_section(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def validate(agent_id: str) -> bool:
    """
    エージェントの設定を検証し、結果をコンソールに出力する。

    Returns:
        True: すべてのチェックが通過
        False: 1つ以上のチェックが失敗
    """
    ok = True

    # ── エージェント基本情報 ──────────────────────────────────
    print_section("Agent 基本情報")
    try:
        info = check_agent_status(agent_id)
        for key, val in info.items():
            print(f"  {key:<20}: {val}")

        status = info["agentStatus"]
        if status in ("PREPARED", "VERSIONED"):
            print(f"\n  [OK] ステータス: {status}")
        else:
            print(
                f"\n  [WARN] ステータスが PREPARED / VERSIONED ではありません: {status}"
            )
            ok = False
    except ClientError as e:
        print(f"  [ERROR] エージェント取得失敗: {e}")
        return False

    # ── Action Groups ─────────────────────────────────────────
    print_section("Action Groups")
    try:
        groups = check_action_groups(agent_id)
        if not groups:
            print("  [WARN] Action Group が1件も登録されていません")
            ok = False
        else:
            for g in groups:
                state = g["actionGroupState"]
                mark = "[OK]  " if state == "ENABLED" else "[WARN]"
                print(f"  {mark} {g['actionGroupName']:<30} ({state})")
    except ClientError as e:
        print(f"  [ERROR] Action Group 取得失敗: {e}")
        ok = False

    # ── エイリアス ────────────────────────────────────────────
    print_section("Aliases")
    try:
        aliases = check_aliases(agent_id)
        if not aliases:
            print("  [WARN] エイリアスが1件も登録されていません")
            ok = False
        else:
            for a in aliases:
                status = a["aliasStatus"]
                mark = "[OK]  " if status == "PREPARED" else "[WARN]"
                print(f"  {mark} {a['aliasName']:<30} ({status})")
    except ClientError as e:
        print(f"  [ERROR] エイリアス取得失敗: {e}")
        ok = False

    # ── 総合結果 ──────────────────────────────────────────────
    print_section("総合結果")
    if ok:
        print("  [PASS] すべてのチェックが通過しました")
    else:
        print("  [FAIL] 一部チェックが失敗しました（上記 WARN / ERROR を確認）")

    return ok


# ── エントリーポイント ────────────────────────────────────────


def main() -> None:
    if not AGENT_ID:
        print("[ERROR] 環境変数 AGENT_ID が設定されていません")
        print("  例: AGENT_ID=XXXXXXXXXX python scripts/validate_agent.py")
        sys.exit(1)

    print(f"Bedrock Agent 検証開始: AGENT_ID={AGENT_ID} / REGION={REGION}")

    passed = validate(AGENT_ID)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
