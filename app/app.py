"""
aws-bedrock-agent: Streamlit Web UI
boto3 で Lambda を直接 Invoke してデモ動作するアプリ
"""

import streamlit as st
import boto3
import json
import os

# ── ページ設定 ────────────────────────────────────────────────
st.set_page_config(
    page_title="社内FAQ チャットボット",
    page_icon="🤖",
    layout="centered",
)

# ── サイドバー設定 ────────────────────────────────────────────
with st.sidebar:
    st.header("設定")
    function_name = st.text_input(
        "Lambda 関数名",
        value=os.environ.get("LAMBDA_FUNCTION_NAME", "bedrock-agent-dev"),
    )
    aws_region = st.text_input(
        "AWS リージョン",
        value=os.environ.get("AWS_REGION", "ap-northeast-1"),
    )
    st.divider()
    st.markdown("### FAQ キーワード一覧")
    st.markdown(
        """
以下のキーワードを含む質問は FAQ から即時回答します：
- 有給
- 経費
- リモート
- パスワード
- 福利厚生

上記以外は **Amazon Bedrock（Claude）** が回答します。
"""
    )
    st.divider()
    st.caption("aws-bedrock-agent PoC | Powered by Amazon Bedrock")

# ── メイン画面 ────────────────────────────────────────────────
st.title("🤖 社内FAQ チャットボット")
st.caption("社内の質問を入力してください。FAQまたはAIが回答します。")

# ── チャット履歴の初期化 ──────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── チャット履歴の表示 ────────────────────────────────────────
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ── 質問入力 ──────────────────────────────────────────────────
if prompt := st.chat_input("質問を入力してください（例：有給の申請方法は？）"):

    # ユーザーメッセージを表示・保存
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Lambda を boto3 で直接 Invoke
    with st.chat_message("assistant"):
        with st.spinner("回答を生成中..."):
            try:
                lambda_client = boto3.client("lambda", region_name=aws_region)
                payload = {"body": json.dumps({"question": prompt})}
                response = lambda_client.invoke(
                    FunctionName=function_name,
                    InvocationType="RequestResponse",
                    Payload=json.dumps(payload),
                )
                result = json.loads(response["Payload"].read())
                body = json.loads(result.get("body", "{}"))
                answer = body.get("answer", "回答を取得できませんでした。")

            except Exception as e:
                answer = f"⚠️ エラーが発生しました: {str(e)}"

        st.markdown(answer)

    # アシスタントの回答を保存
    st.session_state.messages.append({"role": "assistant", "content": answer})

# ── チャット履歴クリアボタン ──────────────────────────────────
if st.session_state.messages:
    if st.button("会話をクリア", type="secondary"):
        st.session_state.messages = []
        st.rerun()
