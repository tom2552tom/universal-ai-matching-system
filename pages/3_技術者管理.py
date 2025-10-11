import streamlit as st
from backend import init_database, get_db_connection

# --- ページ設定と初期化 ---
st.set_page_config(page_title="技術者管理", layout="wide")
init_database()

st.title("👨‍💻 技術者管理")
st.markdown("登録されている技術者の一覧表示、検索、並び替えができます。")

# --- 検索とソート、表示オプション ---
col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
with col1:
    search_keyword = st.text_input(
        "🔍 キーワードで検索",
        placeholder="氏名、担当者名、スキル、経歴などで絞り込み"
    )

with col2:
    sort_column = st.selectbox(
        "並び替え",
        options=["登録日", "氏名", "担当者名"],
        index=0,
        key="sort_column"
    )

with col3:
    sort_order = st.selectbox(
        "順序",
        options=["降順", "昇順"],
        index=0,
        key="sort_order"
    )

with col4:
    st.write("") 
    st.write("") 
    show_hidden = st.checkbox("非表示の技術者も表示する", value=False)

st.divider()

# --- DBから技術者データを取得 ---
conn = get_db_connection()

query = """
SELECT 
    e.id, e.name, e.document, e.created_at, e.is_hidden,
    u.username as assigned_username
FROM engineers e
LEFT JOIN users u ON e.assigned_user_id = u.id
"""
params = []
where_clauses = []

if not show_hidden:
    where_clauses.append("e.is_hidden = 0")

# ▼▼▼【ここが修正箇所】▼▼▼
# プレースホルダを %s に、LIKE を ILIKE に変更
if search_keyword:
    where_clauses.append("(e.name ILIKE %s OR e.document ILIKE %s OR u.username ILIKE %s)")
    keyword_param = f'%{search_keyword}%'
    params.extend([keyword_param, keyword_param, keyword_param])
# ▲▲▲【修正ここまで】▲▲▲

if where_clauses:
    query += " WHERE " + " AND ".join(where_clauses)

# --- ソート順の決定 (変更なし) ---
sort_column_map = {
    "登録日": "e.created_at",
    "氏名": "e.name",
    "担当者名": "assigned_username"
}
order_map = {
    "降順": "DESC",
    "昇順": "ASC"
}
order_by_column = sort_column_map.get(sort_column, "e.created_at")
order_by_direction = order_map.get(sort_order, "DESC")

query += f" ORDER BY {order_by_column} {order_by_direction}"

# ▼▼▼【ここも修正箇所】▼▼▼
# executeとfetchallを分離
with conn.cursor() as cursor:
    cursor.execute(query, tuple(params))
    engineers = cursor.fetchall()
conn.close()
# ▲▲▲【修正ここまで】▲▲▲

# --- 一覧表示 ---
st.header(f"登録済み技術者一覧 ({len(engineers)}名)")

if not engineers:
    st.info("表示対象の技術者はいません。検索条件を変更するか、「非表示の技術者も表示する」を試してください。")
else:
    for eng in engineers:
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            
            with col1:
                engineer_name = eng['name'] or f"技術者 (ID: {eng['id']})"
                title_display = f"#### {engineer_name}"
                if eng['is_hidden']:
                    title_display += " <span style='color: #888; font-size: 0.8em; vertical-align: middle;'>(非表示)</span>"
                st.markdown(title_display, unsafe_allow_html=True)
                
                doc_parts = eng['document'].split('\n---\n', 1)
                display_doc = doc_parts[1] if len(doc_parts) > 1 else eng['document']
                preview_text = display_doc.replace('\n', ' ').replace('\r', '')
                st.caption(preview_text[:250] + "..." if len(preview_text) > 250 else preview_text)

            with col2:
                if eng['assigned_username']:
                    st.markdown(f"👤 **担当:** {eng['assigned_username']}")
                
                st.markdown(f"**ID:** {eng['id']}")
                
                # created_atがdatetimeオブジェクトの場合を考慮
                created_at_str = eng['created_at']
                if isinstance(created_at_str, str):
                    created_date = created_at_str.split(' ')[0]
                else:
                    # もしdatetimeオブジェクトならフォーマットする
                    try:
                        created_date = created_at_str.strftime('%Y-%m-%d')
                    except:
                        created_date = "N/A"
                st.caption(f"登録日: {created_date}")
                
                # st.switch_page は新しいStreamlitバージョンで推奨
                if st.button("詳細を見る", key=f"detail_btn_{eng['id']}", use_container_width=True):
                    st.session_state['selected_engineer_id'] = eng['id']
                    st.switch_page("pages/5_技術者詳細.py")

