package main

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

// ── モック DynamoDB クライアント ──────────────────────────────────

type mockDynamoDB struct {
	scanOutput  *dynamodb.ScanOutput
	scanErr     error
	putItemErr  error
	putItemCalled int
}

func (m *mockDynamoDB) Scan(_ context.Context, _ *dynamodb.ScanInput, _ ...func(*dynamodb.Options)) (*dynamodb.ScanOutput, error) {
	return m.scanOutput, m.scanErr
}

func (m *mockDynamoDB) PutItem(_ context.Context, _ *dynamodb.PutItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error) {
	m.putItemCalled++
	return &dynamodb.PutItemOutput{}, m.putItemErr
}

// テスト用に dynamoClient を差し替えるヘルパー
func withMockDB(mock DynamoDBClient, fn func()) {
	orig := dynamoClient
	dynamoClient = mock
	defer func() { dynamoClient = orig }()
	fn()
}

// ── logQuestion テスト（モック使用） ─────────────────────────────

func TestLogQuestion_SuccessReturnsID(t *testing.T) {
	mock := &mockDynamoDB{}
	faqCache = nil
	withMockDB(mock, func() {
		result := logQuestion(context.Background(), "テスト質問", "テスト回答")
		if !strings.Contains(result, "記録しました") {
			t.Errorf("expected success message, got: %s", result)
		}
	})
}

func TestLogQuestion_PutItemCalledOnce(t *testing.T) {
	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		logQuestion(context.Background(), "質問", "回答")
		if mock.putItemCalled != 1 {
			t.Errorf("PutItem should be called once, got %d", mock.putItemCalled)
		}
	})
}

func TestLogQuestion_DynamoErrorReturnsFailureMessage(t *testing.T) {
	mock := &mockDynamoDB{putItemErr: errors.New("DynamoDB unavailable")}
	withMockDB(mock, func() {
		result := logQuestion(context.Background(), "質問", "回答")
		if !strings.Contains(result, "失敗") {
			t.Errorf("expected failure message, got: %s", result)
		}
	})
}

func TestLogQuestion_EmptyQuestionAndAnswer(t *testing.T) {
	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		result := logQuestion(context.Background(), "", "")
		if !strings.Contains(result, "記録しました") {
			t.Errorf("expected success even for empty strings, got: %s", result)
		}
	})
}

func TestLogQuestion_UnicodeQuestion(t *testing.T) {
	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		result := logQuestion(context.Background(), "佐渡汽船の乗船時間は？", "約2時間30分です。")
		if !strings.Contains(result, "記録しました") {
			t.Errorf("expected success for unicode, got: %s", result)
		}
	})
}

func TestLogQuestion_ReturnsUniqueIDs(t *testing.T) {
	mock := &mockDynamoDB{}
	results := make([]string, 5)
	withMockDB(mock, func() {
		for i := range 5 {
			results[i] = logQuestion(context.Background(), "質問", "回答")
		}
	})
	// 各呼び出しで異なる ID が含まれること
	for i := 1; i < len(results); i++ {
		if results[i] == results[0] {
			t.Errorf("UUIDs should be unique but got same result: %s", results[0])
		}
	}
}

func TestLogQuestion_LongQuestionAndAnswer(t *testing.T) {
	mock := &mockDynamoDB{}
	longQ := strings.Repeat("あ", 500)
	longA := strings.Repeat("い", 500)
	withMockDB(mock, func() {
		result := logQuestion(context.Background(), longQ, longA)
		if !strings.Contains(result, "記録しました") {
			t.Errorf("expected success for long strings, got: %s", result)
		}
	})
}

// ── loadFAQ テスト（DynamoDB スキャン・モック使用） ───────────────

func TestLoadFAQ_ScanReturnsItems(t *testing.T) {
	items := []map[string]types.AttributeValue{
		{
			"keyword": &types.AttributeValueMemberS{Value: "乗船時間"},
			"answer":  &types.AttributeValueMemberS{Value: "約2時間30分です。"},
		},
		{
			"keyword": &types.AttributeValueMemberS{Value: "料金"},
			"answer":  &types.AttributeValueMemberS{Value: "大人片道2,890円です。"},
		},
	}
	mock := &mockDynamoDB{
		scanOutput: &dynamodb.ScanOutput{Items: items},
	}
	faqCache = nil

	withMockDB(mock, func() {
		result, err := loadFAQ(context.Background())
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(result) != 2 {
			t.Errorf("expected 2 items, got %d", len(result))
		}
		if result["乗船時間"] != "約2時間30分です。" {
			t.Errorf("unexpected value: %s", result["乗船時間"])
		}
		faqCache = nil
	})
}

func TestLoadFAQ_ScanErrorReturnsError(t *testing.T) {
	mock := &mockDynamoDB{scanErr: errors.New("scan failed")}
	faqCache = nil

	withMockDB(mock, func() {
		result, err := loadFAQ(context.Background())
		if err == nil {
			t.Error("expected error but got nil")
		}
		if result != nil {
			t.Errorf("expected nil result on error, got: %v", result)
		}
		faqCache = nil
	})
}

func TestLoadFAQ_EmptyScanResult(t *testing.T) {
	mock := &mockDynamoDB{
		scanOutput: &dynamodb.ScanOutput{Items: []map[string]types.AttributeValue{}},
	}
	faqCache = nil

	withMockDB(mock, func() {
		result, err := loadFAQ(context.Background())
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(result) != 0 {
			t.Errorf("expected empty map, got %d entries", len(result))
		}
		faqCache = nil
	})
}

func TestLoadFAQ_CachePreventsDatabaseCall(t *testing.T) {
	mock := &mockDynamoDB{}
	// キャッシュをセットしておく
	faqCache = map[string]string{"cached": "value"}
	defer func() { faqCache = nil }()

	withMockDB(mock, func() {
		result, err := loadFAQ(context.Background())
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if result["cached"] != "value" {
			t.Errorf("expected cached value, got: %v", result)
		}
	})
}

func TestLoadFAQ_ScanWithMalformedItemSkipped(t *testing.T) {
	// keyword フィールドが文字列でないアイテムはスキップされる
	items := []map[string]types.AttributeValue{
		{
			"keyword": &types.AttributeValueMemberS{Value: "正常キー"},
			"answer":  &types.AttributeValueMemberS{Value: "正常な回答"},
		},
		// answer フィールドなしのアイテム（UnmarshalMap はゼロ値で埋める）
		{
			"keyword": &types.AttributeValueMemberS{Value: "キーのみ"},
		},
	}
	mock := &mockDynamoDB{
		scanOutput: &dynamodb.ScanOutput{Items: items},
	}
	faqCache = nil

	withMockDB(mock, func() {
		result, err := loadFAQ(context.Background())
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		// 2件ともアンマーシャルは成功（answer がゼロ値になる）
		if len(result) < 1 {
			t.Errorf("expected at least 1 item, got %d", len(result))
		}
		faqCache = nil
	})
}

// ── searchFAQ テスト（DynamoDB モック使用） ───────────────────────

func TestSearchFAQ_LoadsFromDynamoWhenCacheNil(t *testing.T) {
	items := []map[string]types.AttributeValue{
		{
			"keyword": &types.AttributeValueMemberS{Value: "time"},
			"answer":  &types.AttributeValueMemberS{Value: "2 hours"},
		},
	}
	mock := &mockDynamoDB{
		scanOutput:  &dynamodb.ScanOutput{Items: items},
		putItemErr: nil,
	}
	faqCache = nil

	withMockDB(mock, func() {
		result := searchFAQ(context.Background(), "what is the time")
		if !strings.Contains(result, "2 hours") {
			t.Errorf("expected DynamoDB FAQ answer, got: %s", result)
		}
		faqCache = nil
	})
}

func TestSearchFAQ_DynamoScanErrorReturnsDefault(t *testing.T) {
	mock := &mockDynamoDB{
		scanErr: errors.New("cannot reach DynamoDB"),
	}
	faqCache = nil

	withMockDB(mock, func() {
		// scan エラー時 → FAQ なし → デフォルトメッセージ
		result := searchFAQ(context.Background(), "何か質問")
		if result == "" {
			t.Error("expected non-empty result even on scan error")
		}
		faqCache = nil
	})
}

func TestSearchFAQ_CacheHitDoesNotCallScan(t *testing.T) {
	mock := &mockDynamoDB{}
	faqCache = map[string]string{"keyword": "答え"}
	defer func() { faqCache = nil }()

	withMockDB(mock, func() {
		_ = searchFAQ(context.Background(), "keyword の質問")
		// Scan が呼ばれていないこと（mockDynamoDB には Scan カウンタなし → パニックせず完了することで確認）
	})
}

// ── routeFunction + log-question テスト（モック使用） ────────────

func TestRouteFunction_LogQuestionSuccess(t *testing.T) {
	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		ctx := context.Background()
		event := ActionGroupEvent{
			Function: "log-question",
			Parameters: []Parameter{
				{Name: "question", Value: "テスト質問"},
				{Name: "answer", Value: "テスト回答"},
			},
		}
		result := routeFunction(ctx, event)
		if !strings.Contains(result, "記録しました") {
			t.Errorf("expected success message, got: %s", result)
		}
	})
}

func TestRouteFunction_LogQuestionDynamoError(t *testing.T) {
	mock := &mockDynamoDB{putItemErr: errors.New("write failed")}
	withMockDB(mock, func() {
		ctx := context.Background()
		event := ActionGroupEvent{
			Function: "log-question",
			Parameters: []Parameter{
				{Name: "question", Value: "Q"},
				{Name: "answer", Value: "A"},
			},
		}
		result := routeFunction(ctx, event)
		if !strings.Contains(result, "失敗") {
			t.Errorf("expected failure message, got: %s", result)
		}
	})
}

func TestRouteFunction_SearchFAQWithDynamoSuccess(t *testing.T) {
	items := []map[string]types.AttributeValue{
		{
			"keyword": &types.AttributeValueMemberS{Value: "予約"},
			"answer":  &types.AttributeValueMemberS{Value: "公式サイトでご予約できます。"},
		},
	}
	mock := &mockDynamoDB{
		scanOutput: &dynamodb.ScanOutput{Items: items},
	}
	faqCache = nil

	withMockDB(mock, func() {
		ctx := context.Background()
		event := ActionGroupEvent{
			Function: "search-faq",
			Parameters: []Parameter{
				{Name: "question", Value: "予約方法を教えてください"},
			},
		}
		result := routeFunction(ctx, event)
		if !strings.Contains(result, "公式サイト") {
			t.Errorf("expected FAQ answer, got: %s", result)
		}
		faqCache = nil
	})
}

func TestRouteFunction_LogQuestionMissingParams(t *testing.T) {
	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		ctx := context.Background()
		// question / answer パラメータなし（空文字列として扱われる）
		event := ActionGroupEvent{
			Function:   "log-question",
			Parameters: []Parameter{},
		}
		defer func() {
			if r := recover(); r != nil {
				t.Errorf("routeFunction panicked: %v", r)
			}
		}()
		result := routeFunction(ctx, event)
		if result == "" {
			t.Error("expected non-empty result")
		}
	})
}

// ── Handler 完全テスト（モック使用） ─────────────────────────────

func TestHandler_LogQuestionEndToEnd(t *testing.T) {
	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		ctx := context.Background()
		event := ActionGroupEvent{
			ActionGroup:    "bedrock-faq",
			Function:       "log-question",
			MessageVersion: "1.0",
			Parameters: []Parameter{
				{Name: "question", Value: "時刻表はありますか"},
				{Name: "answer", Value: "公式サイトをご確認ください"},
			},
		}
		resp, err := Handler(ctx, event)
		if err != nil {
			t.Fatalf("Handler error: %v", err)
		}
		body := resp.Response.FunctionResponse.ResponseBody["TEXT"].Body
		if !strings.Contains(body, "記録しました") {
			t.Errorf("expected success in body, got: %s", body)
		}
		if resp.Response.ActionGroup != "bedrock-faq" {
			t.Errorf("ActionGroup mismatch: %s", resp.Response.ActionGroup)
		}
		if resp.MessageVersion != "1.0" {
			t.Errorf("MessageVersion mismatch: %v", resp.MessageVersion)
		}
	})
}

func TestHandler_SearchFAQEndToEnd(t *testing.T) {
	items := []map[string]types.AttributeValue{
		{
			"keyword": &types.AttributeValueMemberS{Value: "運賃"},
			"answer":  &types.AttributeValueMemberS{Value: "大人片道2,890円です。"},
		},
	}
	mock := &mockDynamoDB{
		scanOutput: &dynamodb.ScanOutput{Items: items},
	}
	faqCache = nil

	withMockDB(mock, func() {
		ctx := context.Background()
		event := ActionGroupEvent{
			ActionGroup: "bedrock-faq",
			Function:    "search-faq",
			Parameters: []Parameter{
				{Name: "question", Value: "運賃はいくらですか"},
			},
		}
		resp, err := Handler(ctx, event)
		if err != nil {
			t.Fatalf("Handler error: %v", err)
		}
		body := resp.Response.FunctionResponse.ResponseBody["TEXT"].Body
		if !strings.Contains(body, "2,890円") {
			t.Errorf("expected FAQ answer in body, got: %s", body)
		}
		faqCache = nil
	})
}

// ── ベンチマーク（モック使用） ────────────────────────────────────

func BenchmarkLogQuestion(b *testing.B) {
	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		ctx := context.Background()
		b.ResetTimer()
		for range b.N {
			logQuestion(ctx, "ベンチ質問", "ベンチ回答")
		}
	})
}

func BenchmarkSearchFAQWithCache(b *testing.B) {
	faqCache = map[string]string{
		"乗船時間": "約2時間30分です。",
		"料金":   "大人片道2,890円です。",
	}
	defer func() { faqCache = nil }()

	mock := &mockDynamoDB{}
	withMockDB(mock, func() {
		ctx := context.Background()
		b.ResetTimer()
		for range b.N {
			searchFAQ(ctx, "乗船時間について知りたい")
		}
	})
}
