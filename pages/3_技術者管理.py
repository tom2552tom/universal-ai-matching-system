import streamlit as st
# backendからinit_database, get_db_connectionのみをインポート
from backend import init_database, get_db_connection

import sys
import os
import json
import html
import time
from datetime import datetime
import re 

# プロジェクトルートをパスに追加 (既存のコード)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)

# backendをbeとしてインポート (既存のコード)
import backend as be

st.set_page_config(page_title="技術者管理", layout="wide")
init_database()

st.title("👨‍💻 技術者管理")
st.markdown("登録されている技術者の一覧表示、検索、並び替えができます。")

# ▼▼▼【レイアウト修正ここから】▼▼▼
# 検索フィールドを独立したコンテナに配置し、幅を広げる
with st.container():
    st.markdown("##### 🔍 キーワードAND検索")
    search_keyword = st.text_input(
        "技術者情報に必ず含まれるべきキーワードをスペース、カンマ、読点などで区切って入力 (例: Python リーダー経験 AWS)",
        placeholder="技術者情報に必ず含まれるべきキーワード",
        label_visibility="collapsed" # ラベルを非表示にしてスッキリさせる
    )
    st.caption("氏名、担当者名、スキル、経歴などに、入力された**すべてのキーワード**が含まれる技術者を抽出します。")

st.divider() # 検索フィールドとソートオプションの間に区切りを入れる

col1, col2, col3 = st.columns([1, 1, 2]) # ソートと表示オプションのカラム比率を調整
with col1:
    sort_column = st.selectbox(
        "並び替え",
        options=["登録日", "氏名", "担当者名"],
        index=0,
        key="sort_column"
    )

with col2:
    sort_order = st.selectbox(
        "順序",
        options=["降順", "昇順"],
        index=0,
        key="sort_order"
    )

with col3: # チェックボックスを右寄せにするために空のカラムを削除し、チェックボックスを直接配置
    st.write("") # スペースを確保
    st.write("") # スペースを確保
    show_hidden = st.checkbox("非表示の技術者も表示する", value=False)

st.divider() # ソートオプションと一覧表示の間に区切りを入れる
# ▲▲▲【レイアウト修正ここまで】▲▲▲



# --- DBから技術者データを取得 ---
conn = get_db_connection()
engineers = []
total_engineer_count = 0 

try:
    with conn.cursor() as cursor:
        # --- SQLクエリの構築 ---
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

        # ▼▼▼【厳密なキーワードAND検索ロジックのみを適用】▼▼▼
        if search_keyword:
            # スペースでキーワードを分割し、各キーワードに対して ILIKE 条件を追加
            keywords_list = [k.strip() for k in re.split(r'[,\s　、]+', search_keyword) if k.strip()]


            if keywords_list:
                for kw in keywords_list:
                    # document, name, assigned_username のいずれかにキーワードが含まれる
                    where_clauses.append(f"(e.document ILIKE %s OR e.name ILIKE %s OR u.username ILIKE %s)")
                    keyword_param = f'%{kw}%'
                    params.extend([keyword_param, keyword_param, keyword_param])
        # ▲▲▲【変更点ここまで】▲▲▲

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # --- ソート順の決定 ---
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

        # 技術者データの取得
        cursor.execute(query, tuple(params))
        engineers = cursor.fetchall()
        
        # 全技術者数を取得（検索条件に合致する件数）
        total_engineer_count = len(engineers)

finally:
    if conn:
        conn.close()

# --- 一覧表示 ---


# --- 一覧表示 ---
# ▼▼▼【ここを修正します】▼▼▼
display_header = f"登録済み技術者一覧 ({total_engineer_count}名)"
if search_keyword:
    keywords_list_for_display = [k.strip() for k in re.split(r'[,\s　、]+', search_keyword) if k.strip()]
    if keywords_list_for_display:
        display_header += f" (キーワード: **{'** + **'.join(keywords_list_for_display)}**)"
    else:
        display_header += f" (キーワード: **{search_keyword}**)"
st.header(display_header)
# ▲▲▲【修正ここまで】▲▲▲


if not engineers:
     # ▼▼▼【メッセージ表示ロジックも修正】▼▼▼
    info_message = "表示対象の技術者はいません。"
    if search_keyword:
        # 正しく分割されたキーワードを表示するように変更
        keywords_list_for_display = [k.strip() for k in re.split(r'[,\s　、]+', search_keyword) if k.strip()]
        if keywords_list_for_display:
            info_message += f" 検索キーワード「**{'**」と「**'.join(keywords_list_for_display)}**」では見つかりませんでした。"
        else:
            info_message += f" 検索キーワード「**{search_keyword}**」では見つかりませんでした。"
    info_message += " 検索条件を変更するか、「非表示の技術者も表示する」を試してください。"
    st.info(info_message)
    # ▲▲▲【修正ここまで】▲▲▲
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
                
                created_at_str = eng['created_at']
                if isinstance(created_at_str, str):
                    created_date = created_at_str.split(' ')[0]
                else:
                    try:
                        created_date = created_at_str.strftime('%Y-%m-%d')
                    except:
                        created_date = "N/A"
                st.caption(f"登録日: {created_date}")
                
                if st.button("詳細を見る", key=f"detail_btn_{eng['id']}", use_container_width=True):
                    st.session_state['selected_engineer_id'] = eng['id']
                    st.switch_page("pages/5_技術者詳細.py")