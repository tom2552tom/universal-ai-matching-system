import streamlit as st
from backend import init_database, get_db_connection

st.set_page_config(page_title="技術者管理", layout="wide")

# アプリケーション起動時にDBをチェック・初期化
init_database()

st.title("👨‍💻 技術者管理")
st.markdown("登録されている技術者の一覧表示と検索ができます。")

# 【変更点 1】検索と表示オプションを横並びに配置
col1, col2 = st.columns([3, 1])
with col1:
    search_keyword = st.text_input(
        "🔍 キーワードで検索",
        placeholder="氏名、担当者名、スキル (例: Java, Python)、経歴などで絞り込み"
    )
with col2:
    st.write("") 
    st.write("") 
    show_hidden = st.checkbox("非表示の技術者も表示する", value=False)

st.divider()

# --- DBから技術者データを取得 ---
conn = get_db_connection()

# 【変更点 2】クエリを拡張し、担当者情報と表示状態を取得
query = """
SELECT 
    e.id, e.name, e.document, e.created_at, e.is_hidden,
    u.username as assigned_username
FROM engineers e
LEFT JOIN users u ON e.assigned_user_id = u.id
"""
params = []
where_clauses = []

# 【変更点 3】表示/非表示の状態に応じて動的にWHERE句を構築
if not show_hidden:
    where_clauses.append("e.is_hidden = 0")

# キーワード検索の条件
if search_keyword:
    where_clauses.append("(e.name LIKE ? OR e.document LIKE ? OR u.username LIKE ?)")
    params.extend([f'%{search_keyword}%', f'%{search_keyword}%', f'%{search_keyword}%'])

# WHERE句を結合
if where_clauses:
    query += " WHERE " + " AND ".join(where_clauses)

query += " ORDER BY e.created_at DESC"
engineers = conn.execute(query, tuple(params)).fetchall()
conn.close()

# --- 一覧表示 ---
st.header(f"登録済み技術者一覧 ({len(engineers)}名)")

if not engineers:
    st.info("表示対象の技術者はいません。検索条件を変更するか、「非表示の技術者も表示する」を試してください。")
else:
    for eng in engineers:
        with st.container(border=True):
            engineer_name = eng['name'] if eng['name'] else f"技術者 (ID: {eng['id']})"
            
            # 【変更点 4】非表示の場合、タイトルに目印をつける
            title_display = f"#### {engineer_name}"
            if eng['is_hidden']:
                title_display += " <span style='color: #888; font-size: 0.8em; vertical-align: middle;'>(非表示)</span>"
            st.markdown(title_display, unsafe_allow_html=True)
            
            col1, col2 = st.columns([4, 1])
            
            with col1:
                doc_parts = eng['document'].split('\n---\n', 1)
                display_doc = doc_parts[1] if len(doc_parts) > 1 else eng['document']
                preview_text = display_doc.replace('\n', ' ').replace('\r', '')
                st.caption(preview_text[:250] + "..." if len(preview_text) > 250 else preview_text)

            with col2:
                # 【変更点 5】担当者がいる場合に表示
                if eng['assigned_username']:
                    st.markdown(f"👤 **担当:** {eng['assigned_username']}")
                
                st.markdown(f"**ID: {eng['id']}**")
                created_date = eng['created_at'].split(' ')[0]
                st.caption(f"登録日: {created_date}")
                
                if st.button("詳細を見る", key=f"detail_btn_{eng['id']}", use_container_width=True):
                    st.session_state['selected_engineer_id'] = eng['id']
                    # 元のコードに合わせてファイル名を指定
                    st.switch_page("pages/5_技術者詳細.py")