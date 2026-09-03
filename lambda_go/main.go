// aws-bedrock-agent: Go 実装（Python 版との並置）
//
// Python 版との比較ポイント:
//   - init() でクライアント初期化 → Python のモジュールトップ変数と同等
//   - faqCache でウォームスタート時の DynamoDB スキャンをスキップ（Python の _FAQ_CACHE と同等）
//   - 型安全: Action Group イベント/レスポンスを構造体で厳密に定義
//   - コールドスタートが Python より高速（バイナリ実行・ランタイム起動なし）
//
// ビルド方法:
//   GOOS=linux GOARCH=arm64 go build -o bootstrap main.go
//   zip lambda_go.zip bootstrap
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/google/uuid"
)

// ── 環境変数 ──────────────────────────────────────────────
var (
	dynamoTableName = getEnv("DYNAMODB_TABLE", "bedrock-agent-dev-questions")
	faqTableName    = getEnv("FAQ_TABLE", "bedrock-agent-dev-faq")
)

// ── DynamoDB クライアントインターフェース（テスト時にモックに差し替え可能） ──
type DynamoDBClient interface {
	Scan(ctx context.Context, params *dynamodb.ScanInput, optFns ...func(*dynamodb.Options)) (*dynamodb.ScanOutput, error)
	PutItem(ctx context.Context, params *dynamodb.PutItemInput, optFns ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error)
}

// ── DynamoDB クライアント（init で初期化・コンテナ再利用時に再生成しない） ──
var dynamoClient DynamoDBClient

// リトライ実行器。DynamoDB のスロットリングと一時的なサーバエラーに備える。
// テストからは Sleep / Rand を差し替えて実待機ゼロで検証する。
var retrier = NewRetrier()

func init() {
	cfg, err := config.LoadDefaultConfig(context.Background())
	if err != nil {
		log.Fatalf("AWS 設定の読み込みに失敗: %v", err)
	}
	dynamoClient = dynamodb.NewFromConfig(cfg)
}

// ── FAQ キャッシュ（ウォームスタート時は DynamoDB スキャンをスキップ） ──
var faqCache map[string]string

// ── Action Group イベント / レスポンス型 ─────────────────
type ActionGroupEvent struct {
	ActionGroup    string      `json:"actionGroup"`
	Function       string      `json:"function"`
	MessageVersion interface{} `json:"messageVersion"`
	Parameters     []Parameter `json:"parameters"`
}

type Parameter struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

type ActionGroupResponse struct {
	Response       ActionGroupResult `json:"response"`
	MessageVersion interface{}       `json:"messageVersion"`
}

type ActionGroupResult struct {
	ActionGroup      string           `json:"actionGroup"`
	Function         string           `json:"function"`
	FunctionResponse FunctionResponse `json:"functionResponse"`
}

type FunctionResponse struct {
	ResponseBody map[string]TextBody `json:"responseBody"`
}

type TextBody struct {
	Body string `json:"body"`
}

// ── DynamoDB アイテム型 ───────────────────────────────────
type FAQItem struct {
	Keyword string `dynamodbav:"keyword"`
	Answer  string `dynamodbav:"answer"`
}

type QuestionItem struct {
	QuestionID string `dynamodbav:"question_id"`
	Question   string `dynamodbav:"question"`
	Answer     string `dynamodbav:"answer"`
	Timestamp  string `dynamodbav:"timestamp"`
}

// ── ヘルパー ─────────────────────────────────────────────
func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func buildResponse(event ActionGroupEvent, body string) ActionGroupResponse {
	return ActionGroupResponse{
		Response: ActionGroupResult{
			ActionGroup: event.ActionGroup,
			Function:    event.Function,
			FunctionResponse: FunctionResponse{
				ResponseBody: map[string]TextBody{
					"TEXT": {Body: body},
				},
			},
		},
		MessageVersion: event.MessageVersion,
	}
}

// ── FAQ ロード（キャッシュ付き） ──────────────────────────
func loadFAQ(ctx context.Context) (map[string]string, error) {
	if faqCache != nil {
		log.Println("FAQ キャッシュ使用（DynamoDB スキャンをスキップ）")
		return faqCache, nil
	}

	out, err := RetryValue(ctx, retrier, "Scan", func(c context.Context) (*dynamodb.ScanOutput, error) {
		return dynamoClient.Scan(c, &dynamodb.ScanInput{
			TableName: aws.String(faqTableName),
		})
	})
	if err != nil {
		return nil, fmt.Errorf("FAQ テーブルスキャンエラー: %w", err)
	}

	cache := make(map[string]string, len(out.Items))
	for _, item := range out.Items {
		var faq FAQItem
		if err := attributevalue.UnmarshalMap(item, &faq); err != nil {
			continue
		}
		cache[faq.Keyword] = faq.Answer
	}

	faqCache = cache
	log.Printf("FAQ キャッシュ構築完了: %d 件", len(faqCache))
	return faqCache, nil
}

// ── FAQ 検索 ──────────────────────────────────────────────
func searchFAQ(ctx context.Context, question string) string {
	faq, err := loadFAQ(ctx)
	if err != nil {
		log.Printf("FAQ 読み込みエラー: %v", err)
	}

	answer := "該当するFAQが見つかりませんでした。担当部署にご確認ください。"
	for keyword, faqAnswer := range faq {
		if strings.Contains(question, keyword) {
			log.Printf("FAQ ヒット: keyword=%s", keyword)
			answer = faqAnswer
			break
		}
	}

	// FAQ 検索結果を自動記録
	logQuestion(ctx, question, answer)
	return answer
}

// ── DynamoDB 記録 ──────────────────────────────────────────
func logQuestion(ctx context.Context, question, answer string) string {
	item := QuestionItem{
		QuestionID: uuid.NewString(),
		Question:   question,
		Answer:     answer,
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
	}

	av, err := attributevalue.MarshalMap(item)
	if err != nil {
		log.Printf("DynamoDB マーシャリングエラー: %v", err)
		return "記録に失敗しました。"
	}

	err = retrier.Do(ctx, "PutItem", func(c context.Context) error {
		_, putErr := dynamoClient.PutItem(c, &dynamodb.PutItemInput{
			TableName: aws.String(dynamoTableName),
			Item:      av,
		})
		return putErr
	})
	if err != nil {
		log.Printf("DynamoDB 書き込みエラー: %v", err)
		return "記録に失敗しました。"
	}

	log.Printf("DynamoDB 記録完了: question_id=%s", item.QuestionID)
	return fmt.Sprintf("記録しました（ID: %s）", item.QuestionID)
}

// ── Action Group ルーター ──────────────────────────────────
func routeFunction(ctx context.Context, event ActionGroupEvent) string {
	params := make(map[string]string, len(event.Parameters))
	for _, p := range event.Parameters {
		params[p.Name] = p.Value
	}

	switch event.Function {
	case "search-faq":
		question := params["question"]
		log.Printf("search-faq 呼び出し: question=%.50s", question)
		return searchFAQ(ctx, question)

	case "log-question":
		question := params["question"]
		answer := params["answer"]
		log.Printf("log-question 呼び出し: question=%.50s", question)
		return logQuestion(ctx, question, answer)

	default:
		log.Printf("未知の function: %s", event.Function)
		return fmt.Sprintf("未対応の関数です: %s", event.Function)
	}
}

// ── Lambda ハンドラー ──────────────────────────────────────
func Handler(ctx context.Context, event ActionGroupEvent) (ActionGroupResponse, error) {
	log.Printf("Action Group 呼び出し: %s / %s", event.ActionGroup, event.Function)

	answer := routeFunction(ctx, event)
	log.Printf("応答完了: %.50s", answer)
	return buildResponse(event, answer), nil
}

func main() {
	lambda.Start(Handler)
}
