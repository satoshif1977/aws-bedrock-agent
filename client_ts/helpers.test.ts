"use strict";

/**
 * aws-bedrock-agent helpers.ts 直接インポートテスト
 *
 * helpers.ts に分離したバリデーション・セッション管理・
 * FAQ ユーティリティ・パラメータ抽出を直接テストする。
 */

import {
  validateConfig,
  isValidConfig,
  generateSessionId,
  isValidSessionId,
  extractParams,
  DEFAULT_FAQ_KEYWORDS,
  formatFAQKeywords,
  containsFAQKeyword,
} from "./helpers";
import type { BedrockAgentConfig, ActionGroupEvent } from "./types";

// ── validateConfig（helpers 直接） ───────────────────────────

describe("validateConfig (from helpers)", () => {
  const valid: BedrockAgentConfig = {
    agentId: "VBIJQIUBUT",
    agentAliasId: "TSTALIASID",
    region: "ap-northeast-1",
  };

  test("有効な設定はエラーなし", () => {
    expect(validateConfig(valid)).toHaveLength(0);
  });

  test("agentId が空はエラー", () => {
    expect(validateConfig({ ...valid, agentId: "" })).toContain("agentId is required");
  });

  test("agentAliasId が空はエラー", () => {
    expect(validateConfig({ ...valid, agentAliasId: "" })).toContain("agentAliasId is required");
  });

  test("region が空はエラー", () => {
    expect(validateConfig({ ...valid, region: "" })).toContain("region is required");
  });

  test("全フィールド空で 3 件エラー", () => {
    expect(validateConfig({ agentId: "", agentAliasId: "", region: "" })).toHaveLength(3);
  });

  test("タブ文字のみも空と判定", () => {
    expect(validateConfig({ ...valid, agentId: "\t" })).toContain("agentId is required");
  });
});

// ── isValidConfig（helpers 直接） ────────────────────────────

describe("isValidConfig (from helpers)", () => {
  test("有効な設定は true", () => {
    expect(isValidConfig({ agentId: "A", agentAliasId: "B", region: "C" })).toBe(true);
  });

  test("空フィールドありは false", () => {
    expect(isValidConfig({ agentId: "A", agentAliasId: "", region: "C" })).toBe(false);
  });
});

// ── generateSessionId / isValidSessionId（helpers 直接） ────

describe("generateSessionId (from helpers)", () => {
  test("UUID v4 形式で生成される", () => {
    expect(isValidSessionId(generateSessionId())).toBe(true);
  });

  test("毎回異なる値が生成される", () => {
    const ids = new Set(Array.from({ length: 10 }, () => generateSessionId()));
    expect(ids.size).toBe(10);
  });

  test("長さは 36 文字", () => {
    expect(generateSessionId()).toHaveLength(36);
  });
});

describe("isValidSessionId (from helpers)", () => {
  test("有効な UUID v4 は true", () => {
    expect(isValidSessionId("550e8400-e29b-41d4-a716-446655440000")).toBe(true);
  });

  test("大文字も true（case insensitive）", () => {
    expect(isValidSessionId("F47AC10B-58CC-4372-A567-0E02B2C3D479")).toBe(true);
  });

  test("空文字は false", () => {
    expect(isValidSessionId("")).toBe(false);
  });

  test("ハイフンなしは false", () => {
    expect(isValidSessionId("550e8400e29b41d4a716446655440000")).toBe(false);
  });

  test("UUID v1 は false", () => {
    expect(isValidSessionId("550e8400-e29b-11d4-a716-446655440000")).toBe(false);
  });

  test("ランダム文字列は false", () => {
    expect(isValidSessionId("not-a-valid-uuid")).toBe(false);
  });
});

// ── extractParams（helpers 直接） ────────────────────────────

describe("extractParams (from helpers)", () => {
  test("パラメータを Record に変換", () => {
    const event: ActionGroupEvent = {
      actionGroup: "ag",
      function: "fn",
      parameters: [
        { name: "key1", value: "val1" },
        { name: "key2", value: "val2" },
      ],
    };
    const params = extractParams(event);
    expect(params["key1"]).toBe("val1");
    expect(params["key2"]).toBe("val2");
  });

  test("parameters undefined で空オブジェクト", () => {
    expect(extractParams({ actionGroup: "ag", function: "fn" })).toEqual({});
  });

  test("空配列で空オブジェクト", () => {
    expect(extractParams({ actionGroup: "ag", function: "fn", parameters: [] })).toEqual({});
  });

  test("重複パラメータは後の値が勝つ", () => {
    const event: ActionGroupEvent = {
      actionGroup: "ag",
      function: "fn",
      parameters: [
        { name: "dup", value: "first" },
        { name: "dup", value: "second" },
      ],
    };
    expect(extractParams(event)["dup"]).toBe("second");
  });
});

// ── DEFAULT_FAQ_KEYWORDS（helpers 直接） ─────────────────────

describe("DEFAULT_FAQ_KEYWORDS (from helpers)", () => {
  test("5 件のキーワードが定義されている", () => {
    expect(DEFAULT_FAQ_KEYWORDS).toHaveLength(5);
  });

  test("各キーワードに keyword と description がある", () => {
    for (const kw of DEFAULT_FAQ_KEYWORDS) {
      expect(kw.keyword).toBeDefined();
      expect(kw.description).toBeDefined();
      expect(kw.keyword.length).toBeGreaterThan(0);
      expect(kw.description.length).toBeGreaterThan(0);
    }
  });

  test("有給・経費・リモート・パスワード・福利厚生を含む", () => {
    const keywords = DEFAULT_FAQ_KEYWORDS.map((k) => k.keyword);
    expect(keywords).toContain("有給");
    expect(keywords).toContain("経費");
    expect(keywords).toContain("リモート");
    expect(keywords).toContain("パスワード");
    expect(keywords).toContain("福利厚生");
  });
});

// ── formatFAQKeywords（helpers 直接） ────────────────────────

describe("formatFAQKeywords (from helpers)", () => {
  test("空配列は空文字", () => {
    expect(formatFAQKeywords([])).toBe("");
  });

  test("単一キーワードをマークダウン形式でフォーマット", () => {
    expect(formatFAQKeywords([{ keyword: "有給", description: "申請方法" }]))
      .toBe("- **有給**: 申請方法");
  });

  test("複数キーワードが改行で結合される", () => {
    const result = formatFAQKeywords([
      { keyword: "有給", description: "申請" },
      { keyword: "経費", description: "精算" },
    ]);
    expect(result.split("\n")).toHaveLength(2);
  });

  test("DEFAULT_FAQ_KEYWORDS で 5 行出力", () => {
    expect(formatFAQKeywords(DEFAULT_FAQ_KEYWORDS).split("\n")).toHaveLength(5);
  });
});

// ── containsFAQKeyword（helpers 直接） ───────────────────────

describe("containsFAQKeyword (from helpers)", () => {
  test("含まれるキーワードを返す", () => {
    expect(containsFAQKeyword("有給の申請方法", DEFAULT_FAQ_KEYWORDS)?.keyword).toBe("有給");
  });

  test("含まれない場合は undefined", () => {
    expect(containsFAQKeyword("天気はどう", DEFAULT_FAQ_KEYWORDS)).toBeUndefined();
  });

  test("空の質問は undefined", () => {
    expect(containsFAQKeyword("", DEFAULT_FAQ_KEYWORDS)).toBeUndefined();
  });

  test("空のキーワード配列は undefined", () => {
    expect(containsFAQKeyword("有給", [])).toBeUndefined();
  });

  test("パスワードキーワードにヒット", () => {
    expect(containsFAQKeyword("パスワードを忘れた", DEFAULT_FAQ_KEYWORDS)?.keyword).toBe("パスワード");
  });

  test("福利厚生キーワードにヒット", () => {
    expect(containsFAQKeyword("福利厚生の詳細", DEFAULT_FAQ_KEYWORDS)?.keyword).toBe("福利厚生");
  });
});
