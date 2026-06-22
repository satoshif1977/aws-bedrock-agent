"use strict";

import {
  validateConfig,
  isValidConfig,
  buildInvokeParams,
  generateSessionId,
  isValidSessionId,
  extractAnswer,
  extractParams,
  buildActionGroupResponse,
  formatFAQKeywords,
  containsFAQKeyword,
  DEFAULT_FAQ_KEYWORDS,
} from "./client";
import type { BedrockAgentConfig, ActionGroupEvent, CompletionEvent } from "./types";

// ── validateConfig ────────────────────────────────────────────

describe("validateConfig", () => {
  const valid: BedrockAgentConfig = {
    agentId: "VBIJQIUBUT",
    agentAliasId: "TSTALIASID",
    region: "ap-northeast-1",
  };

  test("有効な設定はエラーなし", () => {
    expect(validateConfig(valid)).toHaveLength(0);
  });

  test("agentId が空はエラー", () => {
    const errors = validateConfig({ ...valid, agentId: "" });
    expect(errors).toContain("agentId is required");
  });

  test("agentAliasId が空はエラー", () => {
    const errors = validateConfig({ ...valid, agentAliasId: "" });
    expect(errors).toContain("agentAliasId is required");
  });

  test("region が空はエラー", () => {
    const errors = validateConfig({ ...valid, region: "" });
    expect(errors).toContain("region is required");
  });

  test("スペースのみも空と判定", () => {
    const errors = validateConfig({ ...valid, agentId: "   " });
    expect(errors).toContain("agentId is required");
  });

  test("isValidConfig: 有効な設定は true", () => {
    expect(isValidConfig(valid)).toBe(true);
  });

  test("isValidConfig: 不正な設定は false", () => {
    expect(isValidConfig({ ...valid, agentAliasId: "" })).toBe(false);
  });
});

// ── buildInvokeParams ─────────────────────────────────────────

describe("buildInvokeParams", () => {
  const config: BedrockAgentConfig = {
    agentId: "AGENT01",
    agentAliasId: "ALIAS01",
    region: "ap-northeast-1",
  };

  test("agentId が正しくコピーされる", () => {
    const params = buildInvokeParams(config, "session-1", "質問です");
    expect(params.agentId).toBe("AGENT01");
  });

  test("agentAliasId が正しくコピーされる", () => {
    const params = buildInvokeParams(config, "session-1", "質問です");
    expect(params.agentAliasId).toBe("ALIAS01");
  });

  test("sessionId が渡される", () => {
    const params = buildInvokeParams(config, "my-session-id", "質問です");
    expect(params.sessionId).toBe("my-session-id");
  });

  test("inputText が渡される", () => {
    const params = buildInvokeParams(config, "session-1", "有給の申請方法は？");
    expect(params.inputText).toBe("有給の申請方法は？");
  });
});

// ── generateSessionId / isValidSessionId ─────────────────────

describe("generateSessionId", () => {
  test("UUID v4 形式で生成される", () => {
    const id = generateSessionId();
    expect(isValidSessionId(id)).toBe(true);
  });

  test("毎回異なる値が生成される", () => {
    const ids = new Set(Array.from({ length: 5 }, () => generateSessionId()));
    expect(ids.size).toBe(5);
  });
});

describe("isValidSessionId", () => {
  test("有効な UUID v4 は true", () => {
    expect(isValidSessionId("550e8400-e29b-41d4-a716-446655440000")).toBe(true);
  });

  test("UUID v4 形式（バージョン4）は true", () => {
    expect(isValidSessionId("f47ac10b-58cc-4372-a567-0e02b2c3d479")).toBe(true);
  });

  test("ハイフンなしは false", () => {
    expect(isValidSessionId("550e8400e29b41d4a716446655440000")).toBe(false);
  });

  test("空文字は false", () => {
    expect(isValidSessionId("")).toBe(false);
  });
});

// ── extractAnswer ─────────────────────────────────────────────

describe("extractAnswer", () => {
  test("単一チャンクの応答を返す", () => {
    const events: CompletionEvent[] = [
      { chunk: { bytes: Buffer.from("有給休暇の申請方法です。") } },
    ];
    expect(extractAnswer(events)).toBe("有給休暇の申請方法です。");
  });

  test("複数チャンクを結合する", () => {
    const events: CompletionEvent[] = [
      { chunk: { bytes: Buffer.from("有給は") } },
      { chunk: { bytes: Buffer.from("社内ポータルから") } },
      { chunk: { bytes: Buffer.from("申請します。") } },
    ];
    expect(extractAnswer(events)).toBe("有給は社内ポータルから申請します。");
  });

  test("空のイベント配列はフォールバックメッセージを返す", () => {
    expect(extractAnswer([])).toBe("回答を取得できませんでした。");
  });

  test("chunk なしイベントはスキップされる", () => {
    const events: CompletionEvent[] = [
      {},
      { chunk: { bytes: Buffer.from("回答") } },
    ];
    expect(extractAnswer(events)).toBe("回答");
  });

  test("Uint8Array も処理できる", () => {
    const encoder = new TextEncoder();
    const events: CompletionEvent[] = [
      { chunk: { bytes: encoder.encode("テスト回答") } },
    ];
    expect(extractAnswer(events)).toBe("テスト回答");
  });
});

// ── extractParams ─────────────────────────────────────────────

describe("extractParams", () => {
  test("パラメータを Record に変換できる", () => {
    const event: ActionGroupEvent = {
      actionGroup: "faq-action-group",
      function: "search-faq",
      parameters: [
        { name: "question", value: "有給の申請方法は？" },
        { name: "category", value: "hr" },
      ],
    };
    const params = extractParams(event);
    expect(params["question"]).toBe("有給の申請方法は？");
    expect(params["category"]).toBe("hr");
  });

  test("parameters が undefined のとき空の Record を返す", () => {
    const event: ActionGroupEvent = { actionGroup: "ag", function: "fn" };
    expect(extractParams(event)).toEqual({});
  });

  test("parameters が空配列のとき空の Record を返す", () => {
    const event: ActionGroupEvent = { actionGroup: "ag", function: "fn", parameters: [] };
    expect(extractParams(event)).toEqual({});
  });
});

// ── buildActionGroupResponse ──────────────────────────────────

describe("buildActionGroupResponse", () => {
  const event: ActionGroupEvent = {
    actionGroup: "faq-action-group",
    function: "search-faq",
    messageVersion: "1.0",
  };

  test("actionGroup がコピーされる", () => {
    const resp = buildActionGroupResponse(event, "テスト回答");
    expect(resp.response.actionGroup).toBe("faq-action-group");
  });

  test("function がコピーされる", () => {
    const resp = buildActionGroupResponse(event, "テスト回答");
    expect(resp.response.function).toBe("search-faq");
  });

  test("TEXT キーに body が設定される", () => {
    const resp = buildActionGroupResponse(event, "FAQ の回答です");
    expect(resp.response.functionResponse.responseBody["TEXT"].body).toBe("FAQ の回答です");
  });

  test("messageVersion がコピーされる", () => {
    const resp = buildActionGroupResponse(event, "body");
    expect(resp.messageVersion).toBe("1.0");
  });

  test("空の body も設定できる", () => {
    const resp = buildActionGroupResponse(event, "");
    expect(resp.response.functionResponse.responseBody["TEXT"].body).toBe("");
  });
});

// ── formatFAQKeywords ─────────────────────────────────────────

describe("formatFAQKeywords", () => {
  test("空配列は空文字を返す", () => {
    expect(formatFAQKeywords([])).toBe("");
  });

  test("単一キーワードを正しくフォーマット", () => {
    const result = formatFAQKeywords([{ keyword: "有給", description: "申請方法" }]);
    expect(result).toBe("- **有給**: 申請方法");
  });

  test("複数キーワードが改行で結合される", () => {
    const keywords = [
      { keyword: "有給", description: "申請方法" },
      { keyword: "経費", description: "精算方法" },
    ];
    const result = formatFAQKeywords(keywords);
    expect(result).toContain("- **有給**: 申請方法");
    expect(result).toContain("- **経費**: 精算方法");
    expect(result.split("\n")).toHaveLength(2);
  });

  test("DEFAULT_FAQ_KEYWORDS が 5 件ある", () => {
    expect(DEFAULT_FAQ_KEYWORDS).toHaveLength(5);
  });
});

// ── containsFAQKeyword ────────────────────────────────────────

describe("containsFAQKeyword", () => {
  test("質問に含まれるキーワードを返す", () => {
    const hit = containsFAQKeyword("有給の申請方法を教えてください", DEFAULT_FAQ_KEYWORDS);
    expect(hit?.keyword).toBe("有給");
  });

  test("含まれない場合は undefined を返す", () => {
    const hit = containsFAQKeyword("天気はどうですか", DEFAULT_FAQ_KEYWORDS);
    expect(hit).toBeUndefined();
  });

  test("空の質問は undefined を返す", () => {
    const hit = containsFAQKeyword("", DEFAULT_FAQ_KEYWORDS);
    expect(hit).toBeUndefined();
  });

  test("パスワードキーワードを含む質問にヒット", () => {
    const hit = containsFAQKeyword("パスワードを忘れました", DEFAULT_FAQ_KEYWORDS);
    expect(hit?.keyword).toBe("パスワード");
  });
});
