import streamlit as st
import toml

@st.cache_data
def load_app_config():
    """
    config.tomlを読み込む。
    """
    try:
        with open("config.toml", "r", encoding="utf-8") as f:
            return toml.load(f)
    except FileNotFoundError:
        return {
            "app": {"title": "Default App", "version": "N/A"}
        }
    except Exception as e:
        print(f"❌ 設定ファイルの読み込み中にエラーが発生しました: {e}")
        return {
            "app": {"title": "Error", "version": "Error"}
        }

def display_footer():
    """
    すべてのページ共通のフッターを、画面中央に表示する。
    """
    # 設定ファイルからバージョン情報を読み込む
    config = load_app_config()
    version = config.get("app", {}).get("version", "N/A")
    
    st.markdown("---") # 区切り線

    # ▼▼▼【ここからが修正箇所】▼▼▼
    
    # 表示したいテキストを準備
    footer_text = f"Universal AI Agent | Version: {version} | © 2025 Universal Concern"
    
    # st.markdown を使って中央揃えのHTMLを埋め込む
    st.markdown(
        f"""
        <div style="text-align: center; color: #888; font-size: 0.9em;">
            {footer_text}
        </div>
        """,
        unsafe_allow_html=True
    )