"""
index.py と logger.py / metrics.py の結線を検証するテスト（AWS 接続なし）

logger.py・metrics.py 単体の振る舞いは test_logger.py / test_metrics.py が網羅している。
ここで見るのは「ハンドラーがそれらを実際に通しているか」の 1 点。

このリポジトリでは、共通ユーティリティを配ったものの index.py が標準 logging を
使い続けていて、機密情報のマスキングが効かないまま利用者の質問文が
CloudWatch Logs に出ていた。カバレッジでは気づけないので、
「構造化ログとして出ていること」「生の入力が出ていないこと」を固定する。
"""

import json
from unittest.mock import patch

import index
import pytest
from botocore.exceptions import ClientError
from logger import create_logger
from metrics import create_metrics

# ── ヘルパー ─────────────────────────────────────────────


class Collected:
    """ログ行と EMF 行を集めて、注入用の logger / metrics を返す。"""

    def __init__(self) -> None:
        self.logs: list[dict] = []
        self.emf: list[dict] = []
        self.logger = create_logger(
            level="debug",
            sink=lambda line, level: self.logs.append(json.loads(line)),
        )
        self.metrics = create_metrics(
            index.DEFAULT_METRICS_NAMESPACE,
            sink=lambda line: self.emf.append(json.loads(line)),
            Handler="bedrock-agent-action-group",
        )

    def find_log(self, message: str) -> dict | None:
        for entry in self.logs:
            if entry.get("message") == message:
                return entry
        return None

    def metric_names(self) -> list[str]:
        names: list[str] = []
        for doc in self.emf:
            for cw in doc["_aws"]["CloudWatchMetrics"]:
                names.extend(m["Name"] for m in cw["Metrics"])
        return names

    def metric_value(self, name: str):
        for doc in self.emf:
            if name in doc:
                return doc[name]
        return None

    @property
    def dumped_logs(self) -> str:
        return json.dumps(self.logs, ensure_ascii=False)


def make_event(function: str = "search-faq", **params) -> dict:
    return {
        "actionGroup": "faq-search",
        "function": function,
        "messageVersion": 1,
        "parameters": [{"name": k, "value": v} for k, v in params.items()],
    }


def throttling_error(operation: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException"}}, operation
    )


@pytest.fixture(autouse=True)
def reset_faq_cache():
    index._FAQ_CACHE = None
    yield
    index._FAQ_CACHE = None


@pytest.fixture(autouse=True)
def no_sleep():
    """リトライの実待機をなくしてテストを速く・決定的に保つ。"""
    original = index.RETRY_SLEEP
    index.RETRY_SLEEP = lambda _seconds: None
    yield
    index.RETRY_SLEEP = original


# ── 構造化ログに置き換わっていること ─────────────────────


class TestStructuredLogging:
    @patch("index._load_faq", return_value={"有給": "社内ポータルから申請します"})
    @patch("index.log_question")
    def test_構造化ログとして出力される(self, mock_log, mock_faq):
        c = Collected()

        index.search_faq("有給を申請したい", log=c.logger, mx=c.metrics)

        entry = c.find_log("FAQ ヒット")
        assert entry is not None
        assert entry["level"] == "info"
        # 標準 logging のままなら keyword は構造化されず本文に埋まってしまう
        assert entry["keyword"] == "有給"

    @patch("index.route_function", return_value="回答")
    def test_ハンドラーのログにaction_groupとfunctionが載る(self, mock_route):
        c = Collected()

        index.handler(make_event(), None, logger=c.logger, metrics=c.metrics)

        entry = c.find_log("Action Group 呼び出し")
        assert entry is not None
        assert entry["action_group"] == "faq-search"
        assert entry["function"] == "search-faq"


# ── 利用者の入力をログに残さないこと ─────────────────────


class TestInputIsNotLogged:
    @patch("index.search_faq", return_value="回答")
    def test_質問文はログに出ず長さだけが残る(self, mock_search):
        """
        結線前は `question={question[:50]}` で質問文をそのまま出していた。
        FAQ エージェントの入力は利用者が自由に書く欄なので、
        個人情報や顧客名が混ざりうる。長さだけに留める。
        """
        c = Collected()
        secret = "田中さんの住所を教えてください"

        index.route_function(
            "search-faq",
            [{"name": "question", "value": secret}],
            log=c.logger,
            mx=c.metrics,
        )

        assert secret not in c.dumped_logs
        entry = c.find_log("search-faq 呼び出し")
        assert entry is not None
        assert entry["question_length"] == len(secret)

    @patch("index.log_question", return_value="記録しました")
    def test_log_questionルートでも質問文を残さない(self, mock_log):
        c = Collected()
        secret = "社外秘のプロジェクト名"

        index.route_function(
            "log-question",
            [{"name": "question", "value": secret}, {"name": "answer", "value": "A"}],
            log=c.logger,
            mx=c.metrics,
        )

        assert secret not in c.dumped_logs

    @patch("index.route_function", return_value="社外秘の回答本文です")
    def test_応答本文はログに出ず長さだけが残る(self, mock_route):
        c = Collected()

        index.handler(make_event(), None, logger=c.logger, metrics=c.metrics)

        assert "社外秘の回答本文です" not in c.dumped_logs
        entry = c.find_log("応答完了")
        assert entry is not None
        assert entry["answer_length"] == len("社外秘の回答本文です")


# ── メトリクスが出ていること ──────────────────────────────


class TestMetrics:
    @patch("index._load_faq", return_value={"有給": "回答"})
    @patch("index.log_question")
    def test_FAQヒット時にFaqHitが出る(self, mock_log, mock_faq):
        c = Collected()

        index.search_faq("有給を申請したい", log=c.logger, mx=c.metrics)
        c.metrics.flush()

        assert "FaqHit" in c.metric_names()
        assert "FaqMiss" not in c.metric_names()

    @patch("index._load_faq", return_value={"有給": "回答"})
    @patch("index.log_question")
    def test_FAQミス時にFaqMissが出る(self, mock_log, mock_faq):
        c = Collected()

        index.search_faq("全く関係ない質問", log=c.logger, mx=c.metrics)
        c.metrics.flush()

        assert "FaqMiss" in c.metric_names()

    @patch("index.route_function", return_value="回答")
    def test_ハンドラーは1実行につき1回だけEMFを出す(self, mock_route):
        c = Collected()

        index.handler(make_event(), None, logger=c.logger, metrics=c.metrics)

        assert len(c.emf) == 1, f"EMF ドキュメントは 1 件のはず: {len(c.emf)}"
        assert "Invocations" in c.metric_names()
        assert "Success" in c.metric_names()

    def test_未知のfunctionでUnknownFunctionが出る(self):
        c = Collected()

        index.handler(
            make_event("no-such-function"), None, logger=c.logger, metrics=c.metrics
        )

        assert "UnknownFunction" in c.metric_names()

    def test_例外時もEMFが出てHandlerErrorが立つ(self):
        """flush を finally に置いていないと、失敗した実行だけ計測が消える。"""
        c = Collected()

        # actionGroup が無いイベント → handler 内で KeyError
        result = index.handler({}, None, logger=c.logger, metrics=c.metrics)

        assert (
            "エラーが発生しました"
            in result["response"]["functionResponse"]["responseBody"]["TEXT"]["body"]
        )
        assert len(c.emf) == 1
        assert "HandlerError" in c.metric_names()

    @patch("index._table")
    def test_DynamoDB書き込み成功でQuestionLoggedが出る(self, mock_table):
        c = Collected()
        mock_table.put_item.return_value = {}

        index.log_question("質問", "回答", log=c.logger, mx=c.metrics)
        c.metrics.flush()

        assert "QuestionLogged" in c.metric_names()
        assert "PutItemLatency" in c.metric_names()

    @patch("index._table")
    def test_DynamoDB書き込み失敗でQuestionLogErrorが出る(self, mock_table):
        c = Collected()
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ValidationException"}}, "PutItem"
        )

        result = index.log_question("質問", "回答", log=c.logger, mx=c.metrics)
        c.metrics.flush()

        assert result == "記録に失敗しました。"
        assert "QuestionLogError" in c.metric_names()


# ── リトライがログ・メトリクスに乗ること ──────────────────


class TestRetryIsObserved:
    @patch("index._table")
    def test_リトライ時にwarnログとRetryAttemptsが出る(self, mock_table):
        """
        retry_call には on_retry フックがあるのに未接続だった。
        スロットリングが起きていても外からは見えない状態だったので、
        ログとメトリクスの両方に乗ることを固定する。
        """
        c = Collected()
        mock_table.put_item.side_effect = [throttling_error("PutItem"), {}]

        result = index.log_question("質問", "回答", log=c.logger, mx=c.metrics)
        c.metrics.flush()

        assert "記録しました" in result

        entry = c.find_log("AWS API 呼び出しをリトライします")
        assert entry is not None
        assert entry["level"] == "warn"
        assert entry["operation"] == "put_item"
        assert entry["attempt"] == 1

        assert "RetryAttempts" in c.metric_names()
        assert "RetryDelay" in c.metric_names()

    @patch("index._faq_table")
    def test_FAQスキャンのリトライもoperation名で区別できる(self, mock_faq_table):
        c = Collected()
        mock_faq_table.scan.side_effect = [
            throttling_error("Scan"),
            {"Items": [{"keyword": "有給", "answer": "回答"}]},
        ]

        faq = index._load_faq(log=c.logger, mx=c.metrics)
        c.metrics.flush()

        assert faq == {"有給": "回答"}
        entry = c.find_log("AWS API 呼び出しをリトライします")
        assert entry is not None
        assert entry["operation"] == "faq_scan"


# ── 標準 logging へ戻っていないこと ──────────────────────


class TestNoStdlibLogging:
    def test_indexはloggingモジュールを使っていない(self):
        """
        `import logging` に戻すと、機密情報のマスキングを通らないログが
        再び混ざる。構造化ロガーへの一本化を固定する。
        """
        import pathlib
        import re

        source = (pathlib.Path(index.__file__)).read_text(encoding="utf-8")
        assert not re.search(r"^import logging$", source, re.MULTILINE)
        assert not re.search(r"^from logging import", source, re.MULTILINE)
        assert "create_logger_from_env" in source
        assert "create_metrics_from_env" in source
