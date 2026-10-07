package main

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
)

// ── テスト用ヘルパー ──────────────────────────────────────────
//
// ここでのテストの主眼は「logger.go / metrics.go が main.go から実際に
// 呼ばれているか」。関数単体の挙動は logger_test.go / metrics_test.go 側で
// 検証済みなので、ここでは結線が切れたら落ちることだけを固定する。

// newTestLogger は出力を buf に集めるロガーを返す。
func newTestLogger(buf *bytes.Buffer) *slog.Logger {
	return NewLogger(LoggerOptions{Level: LogLevelDebug, Writer: buf})
}

// newTestMetrics は出力を buf に集めるメトリクスを返す。
func newTestMetrics(t *testing.T, buf *bytes.Buffer) *Metrics {
	t.Helper()
	m, err := NewMetrics(MetricsOptions{Namespace: "Test/Observability", Sink: buf})
	if err != nil {
		t.Fatalf("NewMetrics failed: %v", err)
	}
	return m
}

// withNoSleepRetrier はパッケージ変数の retrier を実待機ゼロに差し替える。
func withNoSleepRetrier(fn func()) {
	orig := retrier
	retrier.Sleep = func(context.Context, time.Duration) error { return nil }
	defer func() { retrier = orig }()
	fn()
}

// withFAQCache は faqCache を差し替えて元に戻す。
func withFAQCache(cache map[string]string, fn func()) {
	orig := faqCache
	faqCache = cache
	defer func() { faqCache = orig }()
	fn()
}

// ── Retrier.OnRetry ───────────────────────────────────────────

func TestRetrier_OnRetryHookIsCalled(t *testing.T) {
	calls := 0
	r := NewRetrier()
	r.Sleep = func(context.Context, time.Duration) error { return nil }
	r.OnRetry = func(attempt int, delay time.Duration, err error) {
		calls++
		if attempt < 1 {
			t.Errorf("attempt should start at 1, got %d", attempt)
		}
		if err == nil {
			t.Error("OnRetry should receive the error that triggered the retry")
		}
	}

	err := r.Do(context.Background(), "Scan", func(context.Context) error {
		return retryTestThrottling
	})
	if err == nil {
		t.Fatal("expected the final error to be returned")
	}
	// MaxAttempts=4 なので、リトライ直前のフックは 3 回呼ばれる。
	if want := r.Config.MaxAttempts - 1; calls != want {
		t.Errorf("OnRetry called %d times, want %d", calls, want)
	}
}

func TestRetrier_OnRetryNilDoesNotPanic(t *testing.T) {
	r := NewRetrier()
	r.Sleep = func(context.Context, time.Duration) error { return nil }
	// OnRetry は nil のまま。従来どおり標準ログへ出力され、落ちないこと。
	if err := r.Do(context.Background(), "Scan", func(context.Context) error {
		return retryTestThrottling
	}); err == nil {
		t.Fatal("expected the final error to be returned")
	}
}

// ── context 経由のロガー / メトリクス ────────────────────────

func TestLoggerFrom_ReturnsContextLogger(t *testing.T) {
	var buf bytes.Buffer
	ctx := WithObservability(context.Background(), newTestLogger(&buf), nil)

	loggerFrom(ctx).Info("結線の確認")

	if !strings.Contains(buf.String(), "結線の確認") {
		t.Errorf("context のロガーが使われていない: %s", buf.String())
	}
}

func TestLoggerFrom_FallsBackWhenAbsent(t *testing.T) {
	// ctx にロガーが無くても nil を返さない（ログを落とさない）。
	if loggerFrom(context.Background()) == nil {
		t.Fatal("loggerFrom should never return nil")
	}
}

func TestMetricsFrom_ReturnsNilWhenAbsent(t *testing.T) {
	if metricsFrom(context.Background()) != nil {
		t.Error("metricsFrom should return nil when unset")
	}
}

func TestCountMetric_NoMetricsIsNoop(t *testing.T) {
	// メトリクス未設定でも panic しないこと。副次処理で本処理を止めないため。
	countMetric(context.Background(), "Anything")
}

func TestNewMetrics_DefaultNamespaceAlwaysBuilds(t *testing.T) {
	// main.go の newMetrics は「既定の名前空間なら必ず作れる」前提で
	// エラーを握りつぶしている。その不変条件をここで固定する。
	if _, err := NewMetrics(MetricsOptions{Namespace: DefaultMetricsNamespace}); err != nil {
		t.Fatalf("DefaultMetricsNamespace must always build, got: %v", err)
	}
}

// ── retrierWithHooks：ロガーとメトリクスの両方へ流れるか ──────

func TestRetrierWithHooks_WiresBothLoggerAndMetrics(t *testing.T) {
	var logBuf, metricBuf bytes.Buffer
	metrics := newTestMetrics(t, &metricBuf)
	ctx := WithObservability(context.Background(), newTestLogger(&logBuf), metrics)

	withNoSleepRetrier(func() {
		r := retrierWithHooks(ctx, RetryOperationScan)
		_ = r.Do(ctx, RetryOperationScan, func(context.Context) error {
			return retryTestThrottling
		})
	})
	if err := metrics.Flush(); err != nil {
		t.Fatalf("Flush failed: %v", err)
	}

	if !strings.Contains(logBuf.String(), RetryOperationScan) {
		t.Errorf("RetryLogHook が結線されていない: %s", logBuf.String())
	}
	if got := metricBuf.String(); !strings.Contains(got, "RetryAttempt") {
		t.Errorf("RetryMetricsHook が結線されていない: %s", got)
	}
}

// ── Handler：メトリクスが実際に出るか ─────────────────────────

func TestHandler_EmitsInvocationMetric(t *testing.T) {
	var logBuf, metricBuf bytes.Buffer
	metrics := newTestMetrics(t, &metricBuf)

	origLogger, origMetrics := newHandlerLogger, newHandlerMetrics
	newHandlerLogger = func() *slog.Logger { return newTestLogger(&logBuf) }
	newHandlerMetrics = func(*slog.Logger) *Metrics { return metrics }
	defer func() { newHandlerLogger, newHandlerMetrics = origLogger, origMetrics }()

	// DynamoDB に触れない経路（未対応 function）で結線だけを見る。
	if _, err := Handler(context.Background(), ActionGroupEvent{
		ActionGroup: "test-group",
		Function:    "no-such-function",
	}); err != nil {
		t.Fatalf("Handler returned an error: %v", err)
	}

	got := metricBuf.String()
	for _, name := range []string{"Invocation", "HandlerLatency", "UnknownFunction"} {
		if !strings.Contains(got, name) {
			t.Errorf("メトリクス %s が出力されていない: %s", name, got)
		}
	}
	if !strings.Contains(logBuf.String(), "test-group") {
		t.Errorf("ハンドラーのロガーに actionGroup が乗っていない: %s", logBuf.String())
	}
}

// ── ★ 利用者の質問文をログへ平文で残さない ────────────────────

func TestRouteFunction_DoesNotLogQuestionText(t *testing.T) {
	const secret = "社外秘ZZZ-この文字列はログに出てはいけない"

	var logBuf, metricBuf bytes.Buffer
	metrics := newTestMetrics(t, &metricBuf)
	ctx := WithObservability(context.Background(), newTestLogger(&logBuf), metrics)

	mock := &mockDynamoDB{scanOutput: &dynamodb.ScanOutput{}}
	withFAQCache(nil, func() {
		withNoSleepRetrier(func() {
			withMockDB(mock, func() {
				routeFunction(ctx, ActionGroupEvent{
					ActionGroup: "test-group",
					Function:    "search-faq",
					Parameters:  []Parameter{{Name: "question", Value: secret}},
				})
			})
		})
	})

	if strings.Contains(logBuf.String(), secret) {
		t.Errorf("質問文がログへ平文で出ている: %s", logBuf.String())
	}
	// 長さは残しているので、追跡はできること。
	if !strings.Contains(logBuf.String(), "questionLength") {
		t.Errorf("questionLength が記録されていない: %s", logBuf.String())
	}
}

// ── ビジネスメトリクス ────────────────────────────────────────

func TestSearchFAQ_CountsHitAndMiss(t *testing.T) {
	tests := []struct {
		name     string
		cache    map[string]string
		question string
		want     string
	}{
		{"hit", map[string]string{"有給": "就業規則をご確認ください。"}, "有給は何日ですか", "FaqHit"},
		{"miss", map[string]string{"有給": "就業規則をご確認ください。"}, "該当しない質問", "FaqMiss"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var logBuf, metricBuf bytes.Buffer
			metrics := newTestMetrics(t, &metricBuf)
			ctx := WithObservability(context.Background(), newTestLogger(&logBuf), metrics)

			mock := &mockDynamoDB{}
			withFAQCache(tt.cache, func() {
				withNoSleepRetrier(func() {
					withMockDB(mock, func() {
						searchFAQ(ctx, tt.question)
					})
				})
			})
			if err := metrics.Flush(); err != nil {
				t.Fatalf("Flush failed: %v", err)
			}

			if got := metricBuf.String(); !strings.Contains(got, tt.want) {
				t.Errorf("メトリクス %s が出力されていない: %s", tt.want, got)
			}
		})
	}
}

func TestLogQuestion_CountsFailureOnPutItemError(t *testing.T) {
	var logBuf, metricBuf bytes.Buffer
	metrics := newTestMetrics(t, &metricBuf)
	ctx := WithObservability(context.Background(), newTestLogger(&logBuf), metrics)

	mock := &mockDynamoDB{putItemErr: retryTestThrottling}
	withNoSleepRetrier(func() {
		withMockDB(mock, func() {
			if got := logQuestion(ctx, "質問", "回答"); !strings.Contains(got, "失敗") {
				t.Errorf("失敗時のメッセージが返っていない: %s", got)
			}
		})
	})
	if err := metrics.Flush(); err != nil {
		t.Fatalf("Flush failed: %v", err)
	}

	if got := metricBuf.String(); !strings.Contains(got, "QuestionRecordFailed") {
		t.Errorf("QuestionRecordFailed が出力されていない: %s", got)
	}
}
