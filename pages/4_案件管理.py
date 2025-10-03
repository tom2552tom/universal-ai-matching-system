import streamlit as st
from backend import init_database, get_db_connection

st.set_page_config(page_title="案件管理", layout="wide")

init_database()

# --- ポップアップ関数は不要になったため削除 ---

st.title("💼 案件管理")
st.markdown("登録されている案件の一覧表示と検索ができます。")
st.divider()

# --- 検索機能 ---
search_keyword = st.text_input(
    "🔍 キーワードで検索",
    placeholder="プロジェクト名、開発言語（例: Java, Python）、業務内容などで絞り込み"
)

# --- DBから案件データを取得 ---
conn = get_db_connection()
query = "SELECT id, project_name, document, created_at FROM jobs"
params = []
if search_keyword:
    query += " WHERE project_name LIKE ? OR document LIKE ?"
    params.extend([f'%{search_keyword}%', f'%{search_keyword}%'])
query += " ORDER BY created_at DESC"
jobs = conn.execute(query, tuple(params)).fetchall()
conn.close()

# --- 一覧表示 ---
st.header(f"登録済み案件一覧 ({len(jobs)} 件)")

if not jobs:
    st.info("現在、登録されている案件はありません。または検索条件に一致する案件が見つかりませんでした。")
else:
    for job in jobs:
        with st.container(border=True):
            project_name = job['project_name'] if job['project_name'] else f"案件 (ID: {job['id']})"
            st.markdown(f"#### {project_name}")
            
            col1, col2 = st.columns([4, 1])

            with col1:
                doc_parts = job['document'].split('\n---\n', 1)
                display_doc = doc_parts[1] if len(doc_parts) > 1 else job['document']
                preview_text = display_doc.replace('\n', ' ').replace('\r', '')
                st.caption(preview_text[:250] + "..." if len(preview_text) > 250 else preview_text)

            with col2:
                st.markdown(f"**ID: {job['id']}**")
                created_date = job['created_at'].split(' ')[0]
                st.caption(f"登録日: {created_date}")

                # ▼▼▼【ここが修正箇所です】▼▼▼
                # ポップアップの代わりに、session_stateにIDを保存して画面遷移する
                if st.button("詳細を見る", key=f"detail_job_{job['id']}", use_container_width=True):
                    st.session_state['selected_job_id'] = job['id']
                    st.switch_page("pages/6_案件詳細.py")
