import streamlit as st
from backend import init_database, get_db_connection

st.set_page_config(page_title="案件管理", layout="wide")

# アプリケーション起動時にDBをチェック・初期化
init_database()

st.title("💼 案件管理")
st.markdown("登録されている案件の一覧表示と検索ができます。")

# --- 検索と表示オプション ---
col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
with col1:
    search_keyword = st.text_input(
        "🔍 キーワードで検索",
        placeholder="プロジェクト名、担当者名、業務内容などで絞り込み"
    )
# ▼▼▼【ここからが追加箇所】▼▼▼
with col2:
    sort_column = st.selectbox(
        "並び替え",
        options=["登録日", "プロジェクト名", "担当者名"],
        index=0,
        key="sort_column"
    )

with col3:
    sort_order = st.selectbox(
        "順序",
        options=["昇順", "降順"],
        index=0,
        key="sort_order"
    )
# ▲▲▲【追加箇所はここまで】▲▲▲

with col4:
    st.write("") 
    st.write("") 
    show_hidden = st.checkbox("非表示の案件も表示する", value=False)


st.divider()

# --- DBから案件データを取得 ---
conn = get_db_connection()
query = """
SELECT 
    j.id, j.project_name, j.document, j.created_at, j.is_hidden,
    u.username as assigned_username
FROM jobs j
LEFT JOIN users u ON j.assigned_user_id = u.id
"""
params = []
where_clauses = []

if not show_hidden:
    where_clauses.append("j.is_hidden = 0")

if search_keyword:
    where_clauses.append("(j.project_name LIKE ? OR j.document LIKE ? OR u.username LIKE ?)")
    params.extend([f'%{search_keyword}%', f'%{search_keyword}%', f'%{search_keyword}%'])

if where_clauses:
    query += " WHERE " + " AND ".join(where_clauses)



# ▼▼▼【ここからが修正箇所】▼▼▼
# --- ソート順の決定 ---
sort_column_map = {
    "登録日": "j.created_at",
    "プロジェクト名": "j.project_name",
    "担当者名": "assigned_username" # LEFT JOIN後のエイリアス名を使用
}
order_map = {
    "降順": "DESC",
    "昇順": "ASC"
}

# 選択されたオプションに基づいてORDER BY句を組み立てる
# SQLインジェクションを防ぐため、ユーザー入力を直接クエリに埋め込まず、マップから安全な値を選択する
order_by_column = sort_column_map.get(sort_column, "j.created_at")
order_by_direction = order_map.get(sort_order, "DESC")

query += f" ORDER BY {order_by_column} {order_by_direction}"
# ▲▲▲【修正箇所はここまで】▲▲▲





jobs = conn.execute(query, tuple(params)).fetchall()
conn.close()

# --- 一覧表示 ---
st.header(f"案件一覧 ({len(jobs)} 件)")

if not jobs:
    st.info("表示対象の案件はありません。検索条件を変更するか、「非表示の案件も表示する」を試してください。")
else:
    for job in jobs:
        with st.container(border=True):
            project_name = job['project_name'] if job['project_name'] else f"案件 (ID: {job['id']})"
            
            title_display = f"#### {project_name}"
            if job['is_hidden']:
                title_display += " <span style='color: #888; font-size: 0.8em; vertical-align: middle;'>(非表示)</span>"
            st.markdown(title_display, unsafe_allow_html=True)
            
            col1, col2 = st.columns([4, 1])

            with col1:
                doc_parts = job['document'].split('\n---\n', 1)
                display_doc = doc_parts[1] if len(doc_parts) > 1 else job['document']
                preview_text = display_doc.replace('\n', ' ').replace('\r', '')
                st.caption(preview_text[:250] + "..." if len(preview_text) > 250 else preview_text)

            with col2:
                if job['assigned_username']:
                    st.markdown(f"👤 **担当:** {job['assigned_username']}")
                
                st.markdown(f"**ID:** {job['id']}")
                created_date = job['created_at'].split(' ')[0]
                st.caption(f"登録: {created_date}")

                if st.button("詳細を見る", key=f"detail_job_{job['id']}", use_container_width=True):
                    st.session_state['selected_job_id'] = job['id']
                    st.switch_page("pages/6_案件詳細.py")