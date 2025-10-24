import streamlit as st
# backend.pyから必要な関数をインポート
from backend import (
    init_database, 
    load_embedding_model, 
    fetch_and_process_emails,
    load_app_config  # load_app_config をインポートリストに追加
)
import ui_components as ui

# --- アプリケーションの初期化 ---
init_database()
load_embedding_model()

# --- 設定ファイルの読み込み ---
config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")


# メール処理の設定値を取得（取得できない場合はデフォルトで10）
FETCH_LIMIT = config.get("email_processing", {}).get("fetch_limit", 10)


# セッションステートの初期化
if 'debug_log' not in st.session_state:
    st.session_state.debug_log = "" # Noneではなく空文字列で初期化する方が安全

# ページ設定
st.set_page_config(page_title=f"{APP_TITLE} | メール処理", layout="wide")
ui.apply_global_styles() 


# タイトル
st.title("📧 メールサーバーからのデータ取込")
st.divider()

# ▼▼▼【説明文の修正】▼▼▼

# st.markdown の f-string を使って、設定値を埋め込む
st.markdown(f"""
メールサーバーに接続し、**最新の未読メールを最大{FETCH_LIMIT}件**取得します。

取得したメールの本文や添付ファイル（PDF, Word, Excelなど）の内容をAIが解析し、「案件情報」または「技術者情報」が含まれていると判断した場合、そのメールを処理対象としてシステムに登録します。
""")

# ▲▲▲【修正ここまで】▲▲▲

st.warning("処理には数分かかる場合があります。処理が完了するまでこのページを閉じないでください。")

if st.button("メールサーバーをチェックして処理を実行", type="primary", use_container_width=True):
    # 実行前にログエリアをクリア
    st.session_state.debug_log = ""
    
    # backendの関数を呼び出し、ストリームで表示
    # fetch_and_process_emails がジェネレータであることを想定
    with st.expander("📬 処理ログ", expanded=True):
        st.write_stream(fetch_and_process_emails())
    
    # 処理完了後にメッセージを表示
    st.success("メール処理が完了しました。")
    st.balloons()


# ログ表示エリアはボタン処理の中に統合したため、不要になります。
# if st.session_state.debug_log: ...

ui.display_footer() # フッターは最初に描画しても良い