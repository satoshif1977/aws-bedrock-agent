/**
 * aws-bedrock-agent: TypeScript 型定義
 *
 * Python 版（app/app.py）・Go 版（lambda_go/main.go）との対応:
 *   - BedrockAgentConfig  ← Python の agent_id / agent_alias_id / aws_region
 *   - InvokeAgentParams   ← Python の invoke_agent() 引数
 *   - ActionGroupEvent    ← Go の ActionGroupEvent 構造体
 *   - ActionGroupResponse ← Go の ActionGroupResponse 構造体
 */

// ── Bedrock Agent クライアント設定 ────────────────────────────

export interface BedrockAgentConfig {
  agentId: string;
  agentAliasId: string;
  region: string;
}

// ── invoke_agent パラメータ ───────────────────────────────────

export interface InvokeAgentParams {
  agentId: string;
  agentAliasId: string;
  sessionId: string;
  inputText: string;
}

// ── ストリーミングレスポンス チャンク ─────────────────────────

export interface ResponseChunk {
  bytes?: Uint8Array | Buffer;
}

export interface CompletionEvent {
  chunk?: ResponseChunk;
}

// ── Action Group イベント / レスポンス型 ─────────────────────
// Go 版 lambda_go/main.go の構造体と対応

export interface Parameter {
  name: string;
  value: string;
}

export interface ActionGroupEvent {
  actionGroup: string;
  function: string;
  messageVersion?: string;
  parameters?: Parameter[];
}

export interface TextBody {
  body: string;
}

export interface FunctionResponse {
  responseBody: Record<string, TextBody>;
}

export interface ActionGroupResult {
  actionGroup: string;
  function: string;
  functionResponse: FunctionResponse;
}

export interface ActionGroupResponse {
  response: ActionGroupResult;
  messageVersion?: string;
}

// ── FAQ キーワード ────────────────────────────────────────────

export interface FAQKeyword {
  keyword: string;
  description: string;
}
