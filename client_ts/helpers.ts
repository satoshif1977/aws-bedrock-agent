/**
 * aws-bedrock-agent: 共通ヘルパー関数・定数
 *
 * client.ts から抽出したバリデーション・セッション管理・
 * FAQ ユーティリティ・パラメータ抽出の純粋関数群。
 */

import { randomUUID } from "crypto";
import type {
  BedrockAgentConfig,
  ActionGroupEvent,
  FAQKeyword,
} from "./types";

// ── 設定バリデーション ────────────────────────────────────────

/**
 * BedrockAgentConfig の必須フィールドを検証する
 * @returns エラーメッセージの配列（空なら valid）
 */
export function validateConfig(config: BedrockAgentConfig): string[] {
  const errors: string[] = [];
  if (!config.agentId || config.agentId.trim() === "") {
    errors.push("agentId is required");
  }
  if (!config.agentAliasId || config.agentAliasId.trim() === "") {
    errors.push("agentAliasId is required");
  }
  if (!config.region || config.region.trim() === "") {
    errors.push("region is required");
  }
  return errors;
}

export function isValidConfig(config: BedrockAgentConfig): boolean {
  return validateConfig(config).length === 0;
}

// ── セッション管理 ────────────────────────────────────────────

/**
 * UUID v4 形式のセッション ID を生成する
 * Python の uuid.uuid4() に対応
 */
export function generateSessionId(): string {
  return randomUUID();
}

/**
 * セッション ID が UUID v4 形式か検証する
 */
export function isValidSessionId(sessionId: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    sessionId
  );
}

// ── Action Group パラメータ抽出 ───────────────────────────────

/**
 * ActionGroupEvent のパラメータ配列を Map に変換する
 * Go 版 routeFunction() の params := make(map[string]string) に対応
 */
export function extractParams(event: ActionGroupEvent): Record<string, string> {
  const params: Record<string, string> = {};
  for (const p of event.parameters ?? []) {
    params[p.name] = p.value;
  }
  return params;
}

// ── FAQ キーワードユーティリティ ─────────────────────────────

/** デフォルト FAQ キーワード一覧（Python app/app.py のサイドバー表示と対応） */
export const DEFAULT_FAQ_KEYWORDS: FAQKeyword[] = [
  { keyword: "有給", description: "有給休暇の申請方法（社内ポータル・3営業日前）" },
  { keyword: "経費", description: "経費精算の締め日・提出先" },
  { keyword: "リモート", description: "リモートワークのルール（週3日・事前報告）" },
  { keyword: "パスワード", description: "ITヘルプデスクへの連絡方法" },
  { keyword: "福利厚生", description: "社内ポータルの参照先" },
];

/**
 * FAQ キーワード一覧をマークダウン形式にフォーマットする
 */
export function formatFAQKeywords(keywords: FAQKeyword[]): string {
  if (keywords.length === 0) return "";
  return keywords.map((k) => `- **${k.keyword}**: ${k.description}`).join("\n");
}

/**
 * 質問文に FAQ キーワードが含まれているか判定する
 * Go 版 searchFAQ() の strings.Contains に対応
 */
export function containsFAQKeyword(
  question: string,
  keywords: FAQKeyword[]
): FAQKeyword | undefined {
  return keywords.find((k) => question.includes(k.keyword));
}
