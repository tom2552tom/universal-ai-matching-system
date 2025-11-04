import streamlit as st
import ui_components as ui
import os
from backend import (
    init_database, 
    load_embedding_model, 
    fetch_and_process_emails,
    load_app_config  # load_app_config をインポートリストに追加
)

config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")



# --- ページ設定 ---
st.set_page_config(page_title=f"{APP_TITLE} | リリースノート", layout="wide")

# --- 認証と共通スタイル ---
#if not ui.check_password():
#    st.stop()
ui.apply_global_styles()

if not ui.check_password():
    st.stop() # 認証が通らない場合、ここで処理を停止

# --- メインコンテンツ ---
st.markdown("このアプリケーションのバージョンごとの変更履歴です。")
st.divider()

# --- CHANGELOG.md ファイルの読み込みと表示 ---
try:
    # このファイルの場所を基準にCHANGELOG.mdへの相対パスを構築
    changelog_path = os.path.join(os.path.dirname(__file__), '..', 'CHANGELOG.md')
    
    with open(changelog_path, "r", encoding="utf-8") as f:
        changelog_content = f.read()
    
    # st.markdownでファイルの内容を表示
    st.markdown(changelog_content, unsafe_allow_html=True)

except FileNotFoundError:
    st.error("エラー: `CHANGELOG.md` ファイルが見つかりません。プロジェクトのルートディレクトリに配置してください。")
except Exception as e:
    st.error(f"ファイルの読み込み中にエラーが発生しました: {e}")

# --- フッター ---
ui.display_footer()
