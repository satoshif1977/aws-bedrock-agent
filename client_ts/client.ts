/**
 * aws-bedrock-agent: TypeScript クライアントユーティリティ
 *
 * Python 版 app/app.py の invoke_bedrock_agent() に対応する
 * 型安全なユーティリティ関数群。
 * AWS 呼び出し部分を分離し、ビジネスロジックをテスト可能に設計。
 *
 * バリデーション・セッション管理・FAQ ユーティリティは helpers.ts に分離。
 */

import type {
  BedrockAgentConfig,
  InvokeAgentParams,
  CompletionEvent,
  ActionGroupEvent,
  ActionGroupResponse,
} from "./types";

// ── re-export（テスト互換） ─────────────────────────────────
export {
  validateConfig,
  isValidConfig,
  generateSessionId,
  isValidSessionId,
  extractParams,
  DEFAULT_FAQ_KEYWORDS,
  formatFAQKeywords,
  containsFAQKeyword,
} from "./helpers";

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

// ── ActionGroupResponse 構築 ──────────────────────────────────

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
