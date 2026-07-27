package main

import (
	"context"
	"strings"
	"testing"
	"unicode/utf8"
)

// FuzzGetEnvFallback は getEnv が任意のキーで
// 「環境変数が未設定なら必ず fallback を返す」ことを検証する。
// 不変条件: fallback は環境変数が空または未設定のときの安全な既定値として機能する。
func FuzzGetEnvFallback(f *testing.F) {
	f.Add("MISSING_VAR_XYZ", "fallback_value")
	f.Add("", "default")
	f.Add("NOT_SET_KEY", "")
	f.Add("ANOTHER_KEY", "my-fallback-123")

	f.Fuzz(func(t *testing.T, key, fallback string) {
		if !utf8.ValidString(key) || !utf8.ValidString(fallback) {
			t.Skip()
		}
		// テスト用の一意キーを使い、環境変数が設定されていない前提で検証
		uniqueKey := "FUZZ_UNSET_" + key
		result := getEnv(uniqueKey, fallback)

		// 不変条件: 未設定の環境変数は fallback を返す
		if result != fallback {
			t.Errorf("getEnv(%q, %q)=%q: 未設定キーは fallback %q を返すべき", uniqueKey, fallback, result, fallback)
		}
	})
}

// FuzzBuildResponseBodyPreserved は buildResponse が任意の body 文字列を
// 必ず TEXT キーの Body フィールドにそのまま保持することを検証する。
// 不変条件: Bedrock Action Group への応答 body は一切変換・切り捨てされない。
func FuzzBuildResponseBodyPreserved(f *testing.F) {
	f.Add("ag", "fn", "テスト回答")
	f.Add("faq-action-group", "search-faq", "")
	f.Add("ag", "fn", "日本語の回答テスト🎉")
	f.Add("ag", "fn", "<script>alert('xss')</script>")
	f.Add("ag", "fn", strings.Repeat("あいうえお", 100))

	f.Fuzz(func(t *testing.T, actionGroup, function, body string) {
		if !utf8.ValidString(actionGroup) || !utf8.ValidString(function) || !utf8.ValidString(body) {
			t.Skip()
		}
		event := ActionGroupEvent{
			ActionGroup: actionGroup,
			Function:    function,
		}
		resp := buildResponse(event, body)

		// 不変条件1: TEXT キーが存在する
		text, ok := resp.Response.FunctionResponse.ResponseBody["TEXT"]
		if !ok {
			t.Errorf("buildResponse: ResponseBody に 'TEXT' キーがない")
		}

		// 不変条件2: body がそのまま保持される
		if text.Body != body {
			t.Errorf("buildResponse: body=%q が保持されていない（got=%q）", body, text.Body)
		}
	})
}

// FuzzBuildResponseFieldsCopied は buildResponse が ActionGroup と Function を
// 必ずレスポンスに反映することを検証する。
// 不変条件: Bedrock ルーティングに必要なフィールドが欠落しない。
func FuzzBuildResponseFieldsCopied(f *testing.F) {
	f.Add("bedrock-action-group", "search-faq")
	f.Add("", "")
	f.Add("ag-with-日本語", "fn-name")
	f.Add("group", "log-question")

	f.Fuzz(func(t *testing.T, actionGroup, function string) {
		if !utf8.ValidString(actionGroup) || !utf8.ValidString(function) {
			t.Skip()
		}
		event := ActionGroupEvent{
			ActionGroup: actionGroup,
			Function:    function,
		}
		resp := buildResponse(event, "body")

		// 不変条件: ActionGroup と Function がそのままコピーされる
		if resp.Response.ActionGroup != actionGroup {
			t.Errorf("ActionGroup: 期待 %q, 実際 %q", actionGroup, resp.Response.ActionGroup)
		}
		if resp.Response.Function != function {
			t.Errorf("Function: 期待 %q, 実際 %q", function, resp.Response.Function)
		}
	})
}

// FuzzRouteFunctionNoPanic は routeFunction が任意の Function 名でパニックしないことを検証する。
// 不変条件: 未知の Function 名に対しては必ずエラーメッセージを返し、クラッシュしない。
// note: search-faq / log-question は DynamoDB PutItem を呼ぶため CI では接続エラーが出るが PASS する。
func FuzzRouteFunctionNoPanic(f *testing.F) {
	// DynamoDB を呼ばない未知の Function のみシードに含める（CI 高速化）
	f.Add("unknown-function", "")
	f.Add("", "")
	f.Add("delete-everything", "arbitrary question")

	f.Fuzz(func(t *testing.T, functionName, question string) {
		if !utf8.ValidString(functionName) || !utf8.ValidString(question) {
			t.Skip()
		}
		// faqCache をセットして DynamoDB アクセスを回避
		faqCache = map[string]string{"テスト": "テスト回答"}
		defer func() { faqCache = nil }()

		ctx := context.Background()
		event := ActionGroupEvent{
			Function: functionName,
			Parameters: []Parameter{
				{Name: "question", Value: question},
				{Name: "answer", Value: "fuzz-answer"},
			},
		}

		// 不変条件: どんな Function 名でもパニックしない
		defer func() {
			if r := recover(); r != nil {
				t.Errorf("routeFunction(%q) がパニック: %v", functionName, r)
			}
		}()
		result := routeFunction(ctx, event)

		// 不変条件: 未知の Function は関数名を含むエラーメッセージを返す
		if functionName != "search-faq" && functionName != "log-question" {
			if !strings.Contains(result, functionName) {
				// functionName が空の場合は含まれなくてもよい
				if functionName != "" {
					t.Errorf("routeFunction(%q): 関数名がエラーメッセージに含まれていない（got=%q）", functionName, result)
				}
			}
		}
	})
}

// FuzzSearchFAQNoPanic は searchFAQ が任意の質問文字列でパニックしないことを検証する。
// 不変条件: FAQ 検索は任意の入力に対して常に文字列を返す（空であっても）。
// note: logQuestion 内で DynamoDB PutItem を呼ぶため CI では接続エラーが出るが PASS する。
// シードを最小限にして CI 実行時間（タイムアウト待ち）を抑制する。
func FuzzSearchFAQNoPanic(f *testing.F) {
	f.Add("乗船時間を教えてください")
	f.Add("")

	f.Fuzz(func(t *testing.T, question string) {
		if !utf8.ValidString(question) {
			t.Skip()
		}
		// faqCache を直接セットして DynamoDB アクセスを回避
		faqCache = map[string]string{
			"乗船時間": "約2時間30分です。",
			"料金":   "大人片道2,890円です。",
		}
		defer func() { faqCache = nil }()

		ctx := context.Background()

		// 不変条件: パニックしない
		defer func() {
			if r := recover(); r != nil {
				t.Errorf("searchFAQ(%q) がパニック: %v", question, r)
			}
		}()
		_ = searchFAQ(ctx, question)
	})
}
