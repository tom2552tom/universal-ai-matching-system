import streamlit as st
import toml
import os

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
    
    # 表示したいテキストとアイコンを準備
    footer_icon = "🤖"
    footer_text = f"Universal AI Agent | Version: {version}"
    
    # st.markdown を使って中央揃えのHTMLを埋め込む
    st.markdown(
        f"""
        <div style="
            display: flex;
            justify-content: center;
            align-items: center;
            width: 100%;
        ">
            <div style="
                display: flex;
                align-items: center;
                color: #888;
                font-size: 0.9em;
            ">
                <span style="font-size: 1.2em; margin-right: 10px;">{footer_icon}</span>
                <span>{footer_text}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def apply_global_styles():
    """
    static/main.css ファイルを読み込み、スタイルを適用する。
    st.set_page_config の直後に呼び出すことを想定。
    """
    # CSSファイルのパスを指定
    # このファイル (ui_components.py) からの相対パスで指定する
    css_file_path = os.path.join(os.path.dirname(__file__), "styles", "main.css")
    
    try:
        with open(css_file_path) as f:
            css_content = f.read()
        
        # 読み込んだCSSを<style>タグで囲み、markdownとして埋め込む
        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
        
    except FileNotFoundError:
        st.error(f"エラー: スタイルシートが見つかりません。パス: {css_file_path}")
