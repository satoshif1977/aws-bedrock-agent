"use strict";

/**
 * aws-bedrock-agent TypeScript クライアント 詳細ユニットテスト
 *
 * 境界値・エッジケース・構造検証を中心に検証する。
 */

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

// ── validateConfig 境界値詳細 ─────────────────────────────────

describe("validateConfig (境界値詳細)", () => {
  const valid: BedrockAgentConfig = {
    agentId: "VBIJQIUBUT",
    agentAliasId: "TSTALIASID",
    region: "ap-northeast-1",
  };

  test("agentId のみ空は 1 件のエラー", () => {
    const errors = validateConfig({ ...valid, agentId: "" });
    expect(errors).toHaveLength(1);
  });

  test("agentAliasId と region が空は 2 件のエラー", () => {
    const errors = validateConfig({ ...valid, agentAliasId: "", region: "" });
    expect(errors).toHaveLength(2);
  });

  test("長い agentId も有効（制限なし）", () => {
    const longId = "A".repeat(100);
    expect(isValidConfig({ ...valid, agentId: longId })).toBe(true);
  });

  test("エラー配列の先頭が agentId エラー", () => {
    const errors = validateConfig({ agentId: "", agentAliasId: "", region: "" });
    expect(errors[0]).toBe("agentId is required");
  });
});

// ── generateSessionId 詳細 ────────────────────────────────────

describe("generateSessionId (詳細)", () => {
  test("生成された ID の長さは 36 文字", () => {
    expect(generateSessionId()).toHaveLength(36);
  });

  test("ハイフンが 4 つ含まれる", () => {
    const id = generateSessionId();
    expect(id.split("-")).toHaveLength(5);
  });

  test("バージョンビット（3 番目のグループ先頭）が '4'", () => {
    const id = generateSessionId();
    // UUID v4: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
    expect(id.split("-")[2]).toMatch(/^4/);
  });
});

// ── extractAnswer 境界値詳細 ──────────────────────────────────

describe("extractAnswer (境界値詳細)", () => {
  test("空の Buffer はフォールバックメッセージを返す", () => {
    const events: CompletionEvent[] = [{ chunk: { bytes: Buffer.from("") } }];
    expect(extractAnswer(events)).toBe("回答を取得できませんでした。");
  });

  test("改行文字を含むチャンクも正しく処理される", () => {
    const events: CompletionEvent[] = [
      { chunk: { bytes: Buffer.from("1行目\n2行目\n3行目") } },
    ];
    expect(extractAnswer(events)).toBe("1行目\n2行目\n3行目");
  });

  test("絵文字を含むテキストも正しくデコードできる", () => {
    const events: CompletionEvent[] = [
      { chunk: { bytes: Buffer.from("申請完了です 🎉") } },
    ];
    expect(extractAnswer(events)).toBe("申請完了です 🎉");
  });

  test("長いテキストも 1 チャンクで正しく取得できる", () => {
    const longText = "あ".repeat(1000);
    const events: CompletionEvent[] = [
      { chunk: { bytes: Buffer.from(longText) } },
    ];
    expect(extractAnswer(events)).toBe(longText);
  });
});

// ── buildInvokeParams 境界値詳細 ──────────────────────────────

describe("buildInvokeParams (境界値詳細)", () => {
  const config: BedrockAgentConfig = {
    agentId: "AGENT01",
    agentAliasId: "ALIAS01",
    region: "ap-northeast-1",
  };

  test("返却オブジェクトは 4 フィールドのみ持つ", () => {
    const params = buildInvokeParams(config, "session-1", "質問");
    expect(Object.keys(params)).toHaveLength(4);
  });

  test("長い sessionId も正しく設定される", () => {
    const longSession = "session-" + "x".repeat(100);
    const params = buildInvokeParams(config, longSession, "質問");
    expect(params.sessionId).toBe(longSession);
  });

  test("特殊文字を含む inputText も正しく設定される", () => {
    const specialText = "有給の申請方法は？\n詳細を教えてください。";
    const params = buildInvokeParams(config, "sess", specialText);
    expect(params.inputText).toBe(specialText);
  });
});

// ── containsFAQKeyword 境界値詳細 ─────────────────────────────

describe("containsFAQKeyword (境界値詳細)", () => {
  test("福利厚生キーワードにヒット", () => {
    const hit = containsFAQKeyword(
      "福利厚生の詳細を知りたい",
      DEFAULT_FAQ_KEYWORDS
    );
    expect(hit?.keyword).toBe("福利厚生");
  });

  test("大文字小文字を区別する（ひらがな・カタカナ）", () => {
    // "りもーと"（ひらがな）はキーワード "リモート"（カタカナ）にはヒットしない
    const hit = containsFAQKeyword("りもーとわーく", DEFAULT_FAQ_KEYWORDS);
    expect(hit).toBeUndefined();
  });

  test("キーワードが文中に含まれていればヒット（完全一致不要）", () => {
    // "有給" が文中のどこかに含まれていれば OK
    const hit = containsFAQKeyword(
      "先月の有給残日数を確認したい",
      DEFAULT_FAQ_KEYWORDS
    );
    expect(hit?.keyword).toBe("有給");
  });
});

// ── formatFAQKeywords 境界値詳細 ─────────────────────────────

describe("formatFAQKeywords (境界値詳細)", () => {
  test("出力に ': ' が含まれる（keyword: description 形式）", () => {
    const result = formatFAQKeywords([
      { keyword: "テスト", description: "説明文" },
    ]);
    expect(result).toContain(": ");
  });

  test("各行に keyword が含まれる", () => {
    const result = formatFAQKeywords(DEFAULT_FAQ_KEYWORDS);
    for (const k of DEFAULT_FAQ_KEYWORDS) {
      expect(result).toContain(k.keyword);
    }
  });

  test("単一キーワードの場合は改行なし", () => {
    const result = formatFAQKeywords([
      { keyword: "有給", description: "申請方法" },
    ]);
    expect(result).not.toContain("\n");
  });

  test("2 件のキーワードで改行が 1 つ含まれる", () => {
    const result = formatFAQKeywords([
      { keyword: "有給", description: "申請方法" },
      { keyword: "経費", description: "精算方法" },
    ]);
    expect(result.split("\n")).toHaveLength(2);
  });

  test("各行が '- **' で始まるマークダウン形式", () => {
    const result = formatFAQKeywords(DEFAULT_FAQ_KEYWORDS);
    for (const line of result.split("\n")) {
      expect(line).toMatch(/^- \*\*/);
    }
  });
});

// ── extractParams 詳細 ──────────────────────────────────────────

describe("extractParams (詳細)", () => {
  test("パラメータが 3 件のとき 3 つのキーが返る", () => {
    const event: ActionGroupEvent = {
      actionGroup: "TestGroup",
      function: "testFunc",
      messageVersion: "1.0",
      parameters: [
        { name: "a", value: "1" },
        { name: "b", value: "2" },
        { name: "c", value: "3" },
      ],
    };
    const params = extractParams(event);
    expect(Object.keys(params)).toHaveLength(3);
    expect(params.a).toBe("1");
    expect(params.c).toBe("3");
  });

  test("parameters が undefined のとき空オブジェクトを返す", () => {
    const event: ActionGroupEvent = {
      actionGroup: "TestGroup",
      function: "testFunc",
      messageVersion: "1.0",
    };
    expect(extractParams(event)).toEqual({});
  });

  test("同名パラメータは後の値で上書きされる", () => {
    const event: ActionGroupEvent = {
      actionGroup: "TestGroup",
      function: "testFunc",
      messageVersion: "1.0",
      parameters: [
        { name: "key", value: "first" },
        { name: "key", value: "second" },
      ],
    };
    expect(extractParams(event).key).toBe("second");
  });
});

// ── buildActionGroupResponse 詳細 ──────────────────────────────

describe("buildActionGroupResponse (詳細)", () => {
  const event: ActionGroupEvent = {
    actionGroup: "HRGroup",
    function: "getLeaveBalance",
    messageVersion: "1.0",
    parameters: [{ name: "employeeId", value: "E001" }],
  };

  test("response.actionGroup がイベントと一致する", () => {
    const resp = buildActionGroupResponse(event, "残り5日");
    expect(resp.response.actionGroup).toBe("HRGroup");
  });

  test("response.function がイベントと一致する", () => {
    const resp = buildActionGroupResponse(event, "残り5日");
    expect(resp.response.function).toBe("getLeaveBalance");
  });

  test("messageVersion がイベントと一致する", () => {
    const resp = buildActionGroupResponse(event, "残り5日");
    expect(resp.messageVersion).toBe("1.0");
  });

  test("body に日本語テキストが正しく設定される", () => {
    const resp = buildActionGroupResponse(event, "有給残り5日です");
    expect(resp.response.functionResponse.responseBody.TEXT.body).toBe(
      "有給残り5日です"
    );
  });

  test("空の body でもレスポンスが構築される", () => {
    const resp = buildActionGroupResponse(event, "");
    expect(resp.response.functionResponse.responseBody.TEXT.body).toBe("");
  });
});

// ── isValidSessionId 詳細 ───────────────────────────────────────

describe("isValidSessionId (詳細)", () => {
  test("UUID v4 以外のバージョン（v1）は false", () => {
    // UUID v1 はバージョンビットが '1'
    expect(isValidSessionId("550e8400-e29b-11d4-a716-446655440000")).toBe(false);
  });

  test("ハイフンなし UUID は false", () => {
    expect(isValidSessionId("550e8400e29b41d4a716446655440000")).toBe(false);
  });

  test("空文字は false", () => {
    expect(isValidSessionId("")).toBe(false);
  });

  test("大文字 UUID v4 も有効", () => {
    expect(isValidSessionId("550E8400-E29B-41D4-A716-446655440000")).toBe(true);
  });
});

// ── validateConfig + isValidConfig 追加 ─────────────────────────

describe("validateConfig + isValidConfig (追加)", () => {
  test("空白のみの agentId はエラー", () => {
    const errors = validateConfig({
      agentId: "   ",
      agentAliasId: "ALIAS",
      region: "us-east-1",
    });
    expect(errors).toContain("agentId is required");
  });

  test("全フィールド有効のとき isValidConfig が true", () => {
    expect(
      isValidConfig({
        agentId: "AGT",
        agentAliasId: "ALS",
        region: "ap-northeast-1",
      })
    ).toBe(true);
  });

  test("region のみ空のとき 1 件エラー", () => {
    const errors = validateConfig({
      agentId: "AGT",
      agentAliasId: "ALS",
      region: "",
    });
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("region");
  });
});

// ── extractAnswer 追加 ──────────────────────────────────────────

describe("extractAnswer (追加)", () => {
  test("chunk が undefined のイベントはスキップされる", () => {
    const events: CompletionEvent[] = [
      { chunk: undefined },
      { chunk: { bytes: Buffer.from("有効") } },
    ];
    expect(extractAnswer(events)).toBe("有効");
  });

  test("Uint8Array でも正しくデコードされる", () => {
    const text = "Uint8Arrayテスト";
    const events: CompletionEvent[] = [
      { chunk: { bytes: new Uint8Array(Buffer.from(text)) } },
    ];
    expect(extractAnswer(events)).toBe(text);
  });
});
