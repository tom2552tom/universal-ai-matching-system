import streamlit as st
# backend.pyから必要な関数をインポート
from backend import (
    init_database, 
    load_embedding_model, 
    fetch_and_process_emails,
    load_app_config  # 設定読み込み関数をインポート
)

# 設定ファイルからアプリ名を取得
config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")

if 'debug_log' not in st.session_state:
    st.session_state.debug_log = None

# 新しいアプリ名でページ設定
st.set_page_config(page_title=f"{APP_TITLE} | メール処理", layout="wide")

# アプリケーションの初期化
init_database()
load_embedding_model()

# --- タイトル部分を画像に差し替え ---
# st.title(APP_TITLE) # 元のテキストタイトルをコメントアウト
st.image("img/UniversalAI_logo.png",width=240) # ロゴ画像を表示
st.divider()



st.title("📧 メールサーバーからのデータ取込")

st.markdown("""
メールサーバーに接続し、**最新の未読メールを最大10件**取得します。
取得したメールの**本文に「案件情報」または「技術者情報」などが含まれている場合**、そのメールを処理対象として自動でマッチングを実行します。
""")

st.warning("処理には数分かかる場合があります。処理が完了するまでこのページを閉じないでください。")

if st.button("メールサーバーをチェックして処理を実行", type="primary", use_container_width=True):
    success, log_output = fetch_and_process_emails()
    st.session_state.debug_log = log_output

# デバッグウィンドウを画面下部に追加
if st.session_state.debug_log:
    with st.expander("📬 メールサーバー通信ログ (デバッグ用)", expanded=False):
        st.code(st.session_state.debug_log, language='text')

