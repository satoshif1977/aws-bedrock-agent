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
});
