"""
aws-bedrock-agent: Streamlit Web UI
Bedrock Agent Runtime を通じて Agent を呼び出すアプリ
"""

import json
import os
import uuid

import boto3
import streamlit as st

# ── ページ設定 ────────────────────────────────────────────────
st.set_page_config(
    page_title="社内FAQ チャットボット",
    page_icon="🤖",
    layout="centered",
)

# ── サイドバー設定 ────────────────────────────────────────────
with st.sidebar:
    st.header("設定")
    agent_id = st.text_input(
        "Bedrock Agent ID",
        value=os.environ.get("BEDROCK_AGENT_ID", "VBIJQIUBUT"),
    )
    agent_alias_id = st.text_input(
        "Agent Alias ID",
        value=os.environ.get("BEDROCK_AGENT_ALIAS_ID", "TSTALIASID"),
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
"""
    )
    st.divider()
    st.caption("aws-bedrock-agent PoC | Powered by Amazon Bedrock Agent")

# ── メイン画面 ────────────────────────────────────────────────
st.title("🤖 社内FAQ チャットボット")
st.caption("社内の質問を入力してください。Bedrock Agent が回答します。")

# ── セッション初期化 ──────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

# ── チャット履歴の表示 ────────────────────────────────────────
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# ── Bedrock Agent 呼び出し ────────────────────────────────────
def invoke_bedrock_agent(question: str, session_id: str) -> str:
    """Bedrock Agent Runtime を通じて Agent を呼び出す"""
    client = boto3.client("bedrock-agent-runtime", region_name=aws_region)

    response = client.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=question,
    )

    # ストリーミングレスポンスを結合
    answer = ""
    for event in response["completion"]:
        if "chunk" in event:
            chunk = event["chunk"]
            answer += chunk["bytes"].decode("utf-8")

    return answer if answer else "回答を取得できませんでした。"


# ── 質問入力 ──────────────────────────────────────────────────
if prompt := st.chat_input("質問を入力してください（例：有給の申請方法は？）"):

    # ユーザーメッセージを表示・保存
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Bedrock Agent を呼び出し
    with st.chat_message("assistant"):
        with st.spinner("Bedrock Agent が回答を生成中..."):
            try:
                answer = invoke_bedrock_agent(prompt, st.session_state.session_id)
            except Exception as e:
                answer = f"⚠️ エラーが発生しました: {str(e)}"

        st.markdown(answer)

    # アシスタントの回答を保存
    st.session_state.messages.append({"role": "assistant", "content": answer})

# ── 会話クリアボタン ──────────────────────────────────────────
if st.session_state.messages:
    if st.button("会話をクリア", type="secondary"):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()
