// aws-bedrock-agent: Go 実装（Python 版との並置）
//
// Python 版との比較ポイント:
//   - init() でクライアント初期化 → Python のモジュールトップ変数と同等
//   - faqCache でウォームスタート時の DynamoDB スキャンをスキップ（Python の _FAQ_CACHE と同等）
//   - 型安全: Action Group イベント/レスポンスを構造体で厳密に定義
//   - コールドスタートが Python より高速（バイナリ実行・ランタイム起動なし）
//
// ログとメトリクスは同ディレクトリの logger.go / metrics.go に寄せてある。
// 利用者の質問文がそのまま流れてくるため、素の log.Printf ではなく
// logger.go のマスキング（SensitiveKeyPatterns）を必ず通す。
//
// ビルド方法（main.go 単体ではなくパッケージ全体を指定する。
// logger.go / metrics.go / retry.go も同じ package main のため）:
//
//	GOOS=linux GOARCH=arm64 go build -o bootstrap .
//	zip lambda_go.zip bootstrap
package main

import (
	"context"
	"fmt"
	"log"
	"log/slog"
	"os"
	"strings"
	"sync"
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

// DefaultMetricsNamespace は METRICS_NAMESPACE 未設定時に使う名前空間。
const DefaultMetricsNamespace = "AwsBedrockAgent/ActionGroup"

// リトライのフックに渡す操作名。ディメンションではなくプロパティとして載るので、
// 増やしても課金対象のメトリクス数は増えない。
const (
	RetryOperationScan    = "Scan"
	RetryOperationPutItem = "PutItem"
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

// ── 観測可能性（ロガー・メトリクス）の受け渡し ─────────────
//
// loadFAQ / searchFAQ / logQuestion / routeFunction の引数を増やさずに、
// 1 回の呼び出しに閉じたロガーとメトリクスを配るため context に載せて運ぶ。
// パッケージ変数を書き換える方式と違い、呼び出しごとに値が独立するので
// 同時実行で混ざらない。

type loggerCtxKey struct{}

type metricsCtxKey struct{}

// WithObservability は 1 回の呼び出し用のロガーとメトリクスを ctx に載せる。
func WithObservability(ctx context.Context, logger *slog.Logger, metrics *Metrics) context.Context {
	ctx = context.WithValue(ctx, loggerCtxKey{}, logger)
	return context.WithValue(ctx, metricsCtxKey{}, metrics)
}

var (
	fallbackLoggerOnce sync.Once
	fallbackLogger     *slog.Logger
)

// loggerFrom は ctx 上のロガーを返す。
//
// 未設定なら既定ロガーへ落とす。ctx を渡していない呼び出し（テストや将来の
// 内部利用）でもログを落とさないため、nil は返さない。
func loggerFrom(ctx context.Context) *slog.Logger {
	if l, ok := ctx.Value(loggerCtxKey{}).(*slog.Logger); ok && l != nil {
		return l
	}
	fallbackLoggerOnce.Do(func() {
		fallbackLogger = NewLoggerFromEnv(LoggerOptions{})
	})
	return fallbackLogger
}

// metricsFrom は ctx 上のメトリクスを返す。未設定なら nil。
func metricsFrom(ctx context.Context) *Metrics {
	m, _ := ctx.Value(metricsCtxKey{}).(*Metrics)
	return m
}

// countMetric はメトリクス未設定でも安全に呼べるカウンタ。
// メトリクスは副次処理なので、出力に失敗しても本処理は止めない。
func countMetric(ctx context.Context, name string) {
	if m := metricsFrom(ctx); m != nil {
		_ = m.Count(name, 1)
	}
}

// retrierWithHooks は ctx のロガー・メトリクスを OnRetry に結線した
// Retrier の「コピー」を返す。
//
// パッケージ変数の retrier を書き換えないのは、同時実行で他の呼び出しに
// 干渉させないため。
func retrierWithHooks(ctx context.Context, op string) Retrier {
	r := retrier
	logHook := RetryLogHook(loggerFrom(ctx), op)
	metricsHook := func(int, time.Duration, error) {}
	if m := metricsFrom(ctx); m != nil {
		metricsHook = RetryMetricsHook(m, op)
	}
	r.OnRetry = func(attempt int, delay time.Duration, err error) {
		logHook(attempt, delay, err)
		metricsHook(attempt, delay, err)
	}
	return r
}

// テストから差し替えるためのフック。
var (
	newHandlerLogger  = func() *slog.Logger { return NewLoggerFromEnv(LoggerOptions{}) }
	newHandlerMetrics = newMetrics
)

// newMetrics は環境変数 METRICS_NAMESPACE を見てメトリクスを組み立てる。
//
// 名前空間が不正なら警告を残して既定へ落とす。メトリクスが作れないことを
// 理由に本処理を止めない。
func newMetrics(logger *slog.Logger) *Metrics {
	ns := os.Getenv("METRICS_NAMESPACE")
	if ns == "" {
		ns = DefaultMetricsNamespace
	}
	if m, err := NewMetrics(MetricsOptions{Namespace: ns}); err == nil {
		return m
	} else {
		logger.Warn("METRICS_NAMESPACE が不正です。既定の名前空間で初期化します",
			"namespace", ns, "error", err)
	}
	// DefaultMetricsNamespace は定数なので、ここで失敗することはない。
	// その不変条件は TestNewMetrics_DefaultNamespaceAlwaysBuilds で固定している。
	m, _ := NewMetrics(MetricsOptions{Namespace: DefaultMetricsNamespace})
	return m
}

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
	logger := loggerFrom(ctx)

	if faqCache != nil {
		logger.Info("FAQ キャッシュを使用します（DynamoDB スキャンをスキップ）",
			"entries", len(faqCache))
		countMetric(ctx, "FaqCacheHit")
		return faqCache, nil
	}

	out, err := RetryValue(ctx, retrierWithHooks(ctx, RetryOperationScan), RetryOperationScan,
		func(c context.Context) (*dynamodb.ScanOutput, error) {
			return dynamoClient.Scan(c, &dynamodb.ScanInput{
				TableName: aws.String(faqTableName),
			})
		})
	if err != nil {
		countMetric(ctx, "FaqLoadError")
		return nil, fmt.Errorf("FAQ テーブルスキャンエラー: %w", err)
	}

	cache := make(map[string]string, len(out.Items))
	skipped := 0
	for _, item := range out.Items {
		var faq FAQItem
		if err := attributevalue.UnmarshalMap(item, &faq); err != nil {
			// 1 件壊れていても FAQ 全体を落とさない。件数だけ残して続行する。
			skipped++
			continue
		}
		cache[faq.Keyword] = faq.Answer
	}

	faqCache = cache
	logger.Info("FAQ キャッシュを構築しました", "entries", len(faqCache), "skipped", skipped)
	countMetric(ctx, "FaqCacheBuilt")
	return faqCache, nil
}

// ── FAQ 検索 ──────────────────────────────────────────────
const faqNotFoundAnswer = "該当するFAQが見つかりませんでした。担当部署にご確認ください。"

func searchFAQ(ctx context.Context, question string) string {
	logger := loggerFrom(ctx)

	faq, err := loadFAQ(ctx)
	if err != nil {
		logger.Error("FAQ の読み込みに失敗しました。既定の回答で続行します", "error", err)
	}

	answer := faqNotFoundAnswer
	hit := false
	for keyword, faqAnswer := range faq {
		if strings.Contains(question, keyword) {
			logger.Info("FAQ にヒットしました", "keyword", keyword)
			answer = faqAnswer
			hit = true
			break
		}
	}
	// 回答文字列の一致で判定すると、FAQ 側に同じ文言が登録されたときに
	// 取り違える。ヒットしたかどうかはフラグで持つ。
	if hit {
		countMetric(ctx, "FaqHit")
	} else {
		logger.Info("FAQ に該当がありませんでした")
		countMetric(ctx, "FaqMiss")
	}

	// FAQ 検索結果を自動記録
	logQuestion(ctx, question, answer)
	return answer
}

// ── DynamoDB 記録 ──────────────────────────────────────────
func logQuestion(ctx context.Context, question, answer string) string {
	logger := loggerFrom(ctx)

	item := QuestionItem{
		QuestionID: uuid.NewString(),
		Question:   question,
		Answer:     answer,
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
	}

	av, err := attributevalue.MarshalMap(item)
	if err != nil {
		logger.Error("DynamoDB 用のマーシャリングに失敗しました", "error", err)
		countMetric(ctx, "QuestionRecordFailed")
		return "記録に失敗しました。"
	}

	err = retrierWithHooks(ctx, RetryOperationPutItem).Do(ctx, RetryOperationPutItem,
		func(c context.Context) error {
			_, putErr := dynamoClient.PutItem(c, &dynamodb.PutItemInput{
				TableName: aws.String(dynamoTableName),
				Item:      av,
			})
			return putErr
		})
	if err != nil {
		logger.Error("DynamoDB への書き込みに失敗しました",
			"error", err, "questionId", item.QuestionID)
		countMetric(ctx, "QuestionRecordFailed")
		return "記録に失敗しました。"
	}

	logger.Info("質問を記録しました", "questionId", item.QuestionID)
	countMetric(ctx, "QuestionRecorded")
	return fmt.Sprintf("記録しました（ID: %s）", item.QuestionID)
}

// ── Action Group ルーター ──────────────────────────────────
func routeFunction(ctx context.Context, event ActionGroupEvent) string {
	logger := loggerFrom(ctx)

	params := make(map[string]string, len(event.Parameters))
	for _, p := range event.Parameters {
		params[p.Name] = p.Value
	}

	switch event.Function {
	case "search-faq":
		question := params["question"]
		// 質問文そのものは出さない。利用者の入力が CloudWatch Logs へ
		// 平文で残るのを避けるため、長さだけを残す。
		logger.Info("search-faq を実行します", "questionLength", len([]rune(question)))
		return searchFAQ(ctx, question)

	case "log-question":
		question := params["question"]
		answer := params["answer"]
		logger.Info("log-question を実行します", "questionLength", len([]rune(question)))
		return logQuestion(ctx, question, answer)

	default:
		logger.Warn("未対応の function を受信しました", "function", event.Function)
		countMetric(ctx, "UnknownFunction")
		return fmt.Sprintf("未対応の関数です: %s", event.Function)
	}
}

// ── Lambda ハンドラー ──────────────────────────────────────
func Handler(ctx context.Context, event ActionGroupEvent) (ActionGroupResponse, error) {
	logger := newHandlerLogger().With(
		"actionGroup", event.ActionGroup,
		"function", event.Function,
	)
	metrics := newHandlerMetrics(logger)
	defer func() {
		// メトリクスは副次処理。出力に失敗しても応答は返す。
		if err := metrics.Flush(); err != nil {
			logger.Warn("メトリクスの出力に失敗しました", "error", err)
		}
	}()

	ctx = WithObservability(ctx, logger, metrics)

	logger.Info("Action Group の呼び出しを受信しました")
	_ = metrics.Count("Invocation", 1)
	stopTimer := metrics.Timer("HandlerLatency")

	answer := routeFunction(ctx, event)

	_ = stopTimer()
	logger.Info("応答を返します", "answerLength", len([]rune(answer)))
	return buildResponse(event, answer), nil
}

func main() {
	lambda.Start(Handler)
}
