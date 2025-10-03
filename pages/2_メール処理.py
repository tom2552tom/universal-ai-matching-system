undefined# pages/2_メール処理.py
import streamlit as st
# backend.pyから新しい関数をインポート
from backend import init_database, load_embedding_model, fetch_and_process_emails

st.set_page_config(page_title="Universal AIマッチングシステム | メール処理", layout="wide")

init_database()
load_embedding_model()

st.title("📧 メールサーバーからのデータ取込")
st.markdown("""
メールサーバーに接続し、件名に「案件」または「技術者」と記載されている
最新10件（それぞれ）のメールを取得して、自動でマッチング処理を実行します。
""")

st.warning("処理には数分かかる場合があります。処理が完了するまでこのページを閉じないでください。")

if st.button("メールサーバーをチェックして処理を実行", type="primary", use_container_width=True):
    fetch_and_process_emails()
