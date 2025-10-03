import streamlit as st
from backend import get_db_connection

st.set_page_config(page_title="技術者管理", layout="wide")

st.title("👤 技術者管理")
st.markdown("登録されている技術者の一覧表示と検索ができます。")
st.divider()

# --- 検索機能 ---
keyword = st.text_input(
    "🔵 キーワードで検索",
    placeholder="氏名、スキル (例: Java, COBOL) 、経歴などで絞り込み"
)
st.divider()

# --- DBからデータを取得 ---
conn = get_db_connection()
# ▼▼▼【修正箇所】name列を取得し、検索対象にも追加 ▼▼▼
query = "SELECT id, name, document, created_at FROM engineers"
params = []
if keyword:
    # name列とdocument列の両方を検索対象にする
    query += " WHERE name LIKE ? OR document LIKE ?"
    params.extend([f'%{keyword}%', f'%{keyword}%'])
query += " ORDER BY created_at DESC"
engineers = conn.execute(query, tuple(params)).fetchall()
conn.close()

# --- 一覧表示 ---
st.header(f"登録済み技術者一覧 ({len(engineers)}名)")

if not engineers:
    st.info("表示する技術者情報がありません。")
else:
    for eng in engineers:
        with st.container(border=True):
            # ▼▼▼【修正箇所】レイアウトと表示内容を調整 ▼▼▼
            
            # 技術者名を取得。なければIDで代替表示
            engineer_name = eng['name'] if eng['name'] else f"技術者 (ID: {eng['id']})"
            
            st.markdown(f"#### {engineer_name}") # メインタイトルとして名前を表示
            
            col1, col2 = st.columns([4, 1])
            
            with col1:
                # ドキュメントのプレビュー表示
                doc_parts = eng['document'].split('\n---\n', 1)
                display_doc = doc_parts[1] if len(doc_parts) > 1 else eng['document']
                preview_text = display_doc.replace('\n', ' ').replace('\r', '')
                st.caption(preview_text[:250] + "..." if len(preview_text) > 250 else preview_text)

            with col2:
                st.markdown(f"**ID: {eng['id']}**")
                created_date = eng['created_at'].split(' ')[0]
                st.caption(f"登録日: {created_date}")
                
                # 詳細ページへのボタン
                if st.button("詳細を見る", key=f"detail_btn_{eng['id']}", use_container_width=True):
                    st.session_state['selected_engineer_id'] = eng['id']
                    st.switch_page("pages/5_技術者詳細.py")

