import streamlit as st
import toml
import os
import hmac 

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


def check_password():
    """
    ログインフォームを表示し、認証状態を返す。
    認証成功ならTrue、失敗ならFalseを返す。
    """
    
    # --- 認証状態の確認 ---
    # st.session_state に authentication_status がなく、False でもない場合（つまり未ログイン）
    if st.session_state.get("authentication_status", False) != True:
        
        # --- ログインフォーム ---
        # フォームを中央に配置するためのカラム
        _, col2, _ = st.columns([1, 2, 1])
        with col2:
            st.title("🔒 ログイン")
            
            # secrets.toml からユーザー情報を読み込む
            try:
                users = st.secrets["credentials"]["usernames"]
                user_list = list(users.keys())
            except (KeyError, AttributeError):
                st.error("認証情報が `secrets.toml` に正しく設定されていません。")
                return False

            # ログインフォームを作成
            with st.form("login_form"):
                username = st.selectbox("ユーザー名", user_list)
                password = st.text_input("パスワード", type="password")
                submitted = st.form_submit_button("ログイン", use_container_width=True, type="primary")

                if submitted:
                    # 入力されたパスワードと、secrets.toml のパスワードを比較
                    # hmac.compare_digest を使うことで、タイミング攻撃に対して安全になる
                    if hmac.compare_digest(password, users[username]):
                        # 認証成功
                        st.session_state["authentication_status"] = True
                        st.rerun() # ページを再実行してメインコンテンツを表示
                    else:
                        st.error("パスワードが間違っています。")
        
        # フォームが表示されている間は、これ以降の処理を停止
        return False

    # --- 認証成功後の処理 ---
    else:
        # 認証済みであれば True を返す
        return True

