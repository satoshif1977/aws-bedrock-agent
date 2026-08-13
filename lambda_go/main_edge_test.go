package main

import (
	"context"
	"strings"
	"testing"
)

// ── Handler 直接テスト（DynamoDB 不要なケース） ────────────────────

func TestHandler_UnknownFunctionReturnsNoError(t *testing.T) {
	ctx := context.Background()
	event := ActionGroupEvent{
		ActionGroup: "test-group",
		Function:    "no-such-function",
	}

	_, err := Handler(ctx, event)
	if err != nil {
		t.Errorf("Handler should never return error, got: %v", err)
	}
}

func TestHandler_ResponseBodyContainsUnknownFunctionMessage(t *testing.T) {
	ctx := context.Background()
	event := ActionGroupEvent{
		ActionGroup: "test-group",
		Function:    "undefined-fn",
	}

	resp, _ := Handler(ctx, event)
	body := resp.Response.FunctionResponse.ResponseBody["TEXT"].Body
	if !strings.Contains(body, "undefined-fn") {
		t.Errorf("response body should contain function name, got: %s", body)
	}
}

func TestHandler_ResponseEchoesActionGroup(t *testing.T) {
	ctx := context.Background()
	event := ActionGroupEvent{
		ActionGroup:    "my-action-group",
		Function:       "not-exist",
		MessageVersion: "1.0",
	}

	resp, _ := Handler(ctx, event)
	if resp.Response.ActionGroup != "my-action-group" {
		t.Errorf("ActionGroup not echoed: got %s", resp.Response.ActionGroup)
	}
}

func TestHandler_MessageVersionPreserved(t *testing.T) {
	ctx := context.Background()
	event := ActionGroupEvent{
		ActionGroup:    "ag",
		Function:       "unknown",
		MessageVersion: "2",
	}

	resp, _ := Handler(ctx, event)
	if resp.MessageVersion != "2" {
		t.Errorf("MessageVersion not preserved: got %v", resp.MessageVersion)
	}
}

// ── buildResponse エッジケース ────────────────────────────────────

func TestBuildResponse_EmptyActionGroup(t *testing.T) {
	event := ActionGroupEvent{ActionGroup: "", Function: "fn"}
	resp := buildResponse(event, "body")
	if resp.Response.ActionGroup != "" {
		t.Errorf("expected empty ActionGroup, got %q", resp.Response.ActionGroup)
	}
}

func TestBuildResponse_EmptyFunction(t *testing.T) {
	event := ActionGroupEvent{ActionGroup: "ag", Function: ""}
	resp := buildResponse(event, "body")
	if resp.Response.Function != "" {
		t.Errorf("expected empty Function, got %q", resp.Response.Function)
	}
}

func TestBuildResponse_FloatMessageVersion(t *testing.T) {
	event := ActionGroupEvent{ActionGroup: "ag", Function: "fn", MessageVersion: 1.5}
	resp := buildResponse(event, "body")
	if resp.MessageVersion != 1.5 {
		t.Errorf("float MessageVersion not preserved: got %v", resp.MessageVersion)
	}
}

func TestBuildResponse_ResponseBodyKeyIsTEXT(t *testing.T) {
	event := ActionGroupEvent{ActionGroup: "ag", Function: "fn"}
	resp := buildResponse(event, "hello")
	if _, ok := resp.Response.FunctionResponse.ResponseBody["TEXT"]; !ok {
		t.Error("ResponseBody must have 'TEXT' key")
	}
}

// ── getEnv エッジケース ───────────────────────────────────────────

func TestGetEnv_WhitespaceValueIsNotFallback(t *testing.T) {
	// スペースのみの値は「空ではない」ので fallback にならない
	t.Setenv("SPACE_VAR", " ")
	got := getEnv("SPACE_VAR", "fallback")
	if got != " " {
		t.Errorf("whitespace value should not trigger fallback, got %q", got)
	}
}

func TestGetEnv_UnicodeFallback(t *testing.T) {
	got := getEnv("UNICODE_MISSING_VAR_XYZ", "デフォルト値")
	if got != "デフォルト値" {
		t.Errorf("Unicode fallback not returned, got %q", got)
	}
}

func TestGetEnv_VeryLongValue(t *testing.T) {
	long := strings.Repeat("a", 1000)
	t.Setenv("LONG_VAR", long)
	got := getEnv("LONG_VAR", "fallback")
	if len(got) != 1000 {
		t.Errorf("long value truncated: len=%d", len(got))
	}
}

func TestGetEnv_EmptyStringFallback(t *testing.T) {
	got := getEnv("EMPTY_FALLBACK_MISSING_VAR", "")
	if got != "" {
		t.Errorf("empty fallback should be returned as empty, got %q", got)
	}
}

// ── loadFAQ キャッシュ詳細 ────────────────────────────────────────

func TestLoadFAQ_MultipleEntriesInCache(t *testing.T) {
	faqCache = map[string]string{
		"乗船時間": "約2時間30分です。",
		"料金":   "大人片道2,890円です。",
		"駐車場":  "新潟港に有料駐車場があります。",
		"予約":   "公式サイトまたはお電話でご予約できます。",
	}
	defer func() { faqCache = nil }()

	ctx := context.Background()
	result, err := loadFAQ(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(result) != 4 {
		t.Errorf("expected 4 entries, got %d", len(result))
	}
	if result["料金"] != "大人片道2,890円です。" {
		t.Errorf("unexpected value for 料金: %s", result["料金"])
	}
}

func TestLoadFAQ_CacheIsSameReference(t *testing.T) {
	faqCache = map[string]string{"key": "val"}
	defer func() { faqCache = nil }()

	ctx := context.Background()
	r1, _ := loadFAQ(ctx)
	r2, _ := loadFAQ(ctx)
	// 同一マップを返すこと（DynamoDB を2回スキャンしないこと）
	if len(r1) != len(r2) {
		t.Errorf("cache should return consistent results")
	}
}

// ── routeFunction エッジケース ────────────────────────────────────

func TestRouteFunction_ErrorMessageFormat(t *testing.T) {
	ctx := context.Background()
	result := routeFunction(ctx, ActionGroupEvent{Function: "xyz-function"})
	if !strings.Contains(result, "xyz-function") {
		t.Errorf("error message should contain function name: %s", result)
	}
}

func TestRouteFunction_VeryLongFunctionName(t *testing.T) {
	ctx := context.Background()
	longName := strings.Repeat("a", 200)
	event := ActionGroupEvent{Function: longName}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("routeFunction panicked with long function name: %v", r)
		}
	}()
	result := routeFunction(ctx, event)
	if !strings.Contains(result, "未対応") {
		t.Logf("result: %s", result)
	}
}

// ── searchFAQ エッジケース ────────────────────────────────────────

func TestSearchFAQ_EmptyQuestion(t *testing.T) {
	faqCache = map[string]string{"key": "answer"}
	defer func() { faqCache = nil }()

	ctx := context.Background()
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("searchFAQ panicked with empty question: %v", r)
		}
	}()
	result := searchFAQ(ctx, "")
	_ = result
}

func TestSearchFAQ_LargeCache(t *testing.T) {
	cache := make(map[string]string, 50)
	for i := range 50 {
		cache[strings.Repeat("k", i+1)] = "answer"
	}
	faqCache = cache
	defer func() { faqCache = nil }()

	ctx := context.Background()
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("searchFAQ panicked with large cache: %v", r)
		}
	}()
	_ = searchFAQ(ctx, "question")
}

// ── Parameter 構造体 ──────────────────────────────────────────────

func TestParameter_EmptyNameAndValue(t *testing.T) {
	p := Parameter{Name: "", Value: ""}
	if p.Name != "" || p.Value != "" {
		t.Errorf("empty Parameter fields unexpected: name=%q value=%q", p.Name, p.Value)
	}
}

func TestParameter_UnicodeNameValue(t *testing.T) {
	p := Parameter{Name: "質問", Value: "佐渡汽船の時刻表を教えてください"}
	if p.Name != "質問" {
		t.Errorf("Name mismatch: %q", p.Name)
	}
	if p.Value != "佐渡汽船の時刻表を教えてください" {
		t.Errorf("Value mismatch: %q", p.Value)
	}
}

// ── ベンチマーク ─────────────────────────────────────────────────

func BenchmarkBuildResponse(b *testing.B) {
	event := ActionGroupEvent{
		ActionGroup:    "faq-action-group",
		Function:       "search-faq",
		MessageVersion: "1.0",
		Parameters:     []Parameter{{Name: "question", Value: "テスト質問"}},
	}
	b.ResetTimer()
	for range b.N {
		buildResponse(event, "テスト回答本文")
	}
}

func BenchmarkGetEnv(b *testing.B) {
	b.Setenv("BENCH_KEY", "bench_value")
	b.ResetTimer()
	for range b.N {
		getEnv("BENCH_KEY", "fallback")
	}
}

func BenchmarkRouteFunctionUnknown(b *testing.B) {
	ctx := context.Background()
	event := ActionGroupEvent{Function: "unknown-function"}
	b.ResetTimer()
	for range b.N {
		routeFunction(ctx, event)
	}
}
