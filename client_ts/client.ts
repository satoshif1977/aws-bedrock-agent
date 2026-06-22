/**
 * aws-bedrock-agent: TypeScript クライアントユーティリティ
 *
 * Python 版 app/app.py の invoke_bedrock_agent() に対応する
 * 型安全なユーティリティ関数群。
 * AWS 呼び出し部分を分離し、ビジネスロジックをテスト可能に設計。
 */

import { randomUUID } from "crypto";
import type {
  BedrockAgentConfig,
  InvokeAgentParams,
  CompletionEvent,
  ActionGroupEvent,
  ActionGroupResponse,
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

// ── InvokeAgent パラメータ構築 ────────────────────────────────

/**
 * Bedrock Agent Runtime invoke_agent の呼び出しパラメータを組み立てる
 * Python の invoke_agent() 引数に対応
 */
export function buildInvokeParams(
  config: BedrockAgentConfig,
  sessionId: string,
  inputText: string
): InvokeAgentParams {
  return {
    agentId: config.agentId,
    agentAliasId: config.agentAliasId,
    sessionId,
    inputText,
  };
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

// ── ストリーミングレスポンス処理 ──────────────────────────────

/**
 * Bedrock Agent のストリーミングレスポンス chunks を結合して文字列にする
 * Python の for event in response["completion"] ループに対応
 */
export function extractAnswer(events: CompletionEvent[]): string {
  const parts: string[] = [];
  for (const event of events) {
    if (event.chunk?.bytes) {
      const bytes = event.chunk.bytes;
      if (bytes instanceof Buffer) {
        parts.push(bytes.toString("utf-8"));
      } else if (bytes instanceof Uint8Array) {
        parts.push(Buffer.from(bytes).toString("utf-8"));
      }
    }
  }
  const answer = parts.join("");
  return answer || "回答を取得できませんでした。";
}

// ── Action Group ユーティリティ ───────────────────────────────

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

/**
 * ActionGroupResponse を組み立てる
 * Go 版 buildResponse() に対応
 */
export function buildActionGroupResponse(
  event: ActionGroupEvent,
  body: string
): ActionGroupResponse {
  return {
    response: {
      actionGroup: event.actionGroup,
      function: event.function,
      functionResponse: {
        responseBody: {
          TEXT: { body },
        },
      },
    },
    messageVersion: event.messageVersion,
  };
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
