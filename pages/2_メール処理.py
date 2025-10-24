import streamlit as st
# backend.pyから必要な関数をインポート
from backend import (
    init_database, 
    load_embedding_model, 
    fetch_and_process_emails,
    load_app_config
)

import ui_components as ui

# --- アプリケーションの初期化 ---
# ページがロードされたときに一度だけ実行
init_database()
load_embedding_model()

# 設定ファイルからアプリ名を取得
config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")

# セッションステートの初期化
if 'debug_log' not in st.session_state:
    st.session_state.debug_log = None

# ページ設定
st.set_page_config(page_title=f"{APP_TITLE} | メール処理", layout="wide")

# タイトル
st.title("📧 メールサーバーからのデータ取込")
st.divider()

st.markdown("""
メールサーバーに接続し、**最新の未読メールを最大10件**取得します。
取得したメールの本文や添付ファイルに「案件情報」または「技術者情報」などが含まれているとAIが判断した場合、そのメールを処理対象としてシステムに登録し、自動でマッチングを実行します。
""")

st.warning("処理には数分かかる場合があります。処理が完了するまでこのページを閉じないでください。")

if st.button("メールサーバーをチェックして処理を実行", type="primary", use_container_width=True):
    # backendの関数を呼び出す
    success, log_output = fetch_and_process_emails()
    # 実行結果のログをセッションに保存
    st.session_state.debug_log = log_output

# ログ表示エリア
if st.session_state.debug_log:
    st.markdown("---")
    with st.expander("📬 処理ログ", expanded=True):
        # ログをst.codeではなく、より見やすいst.textやst.info/warningで表示することも検討可能
        st.code(st.session_state.debug_log, language='text')




ui.display_footer()
