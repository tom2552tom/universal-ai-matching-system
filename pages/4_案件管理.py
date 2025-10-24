import streamlit as st
import backend as be
import ui_components as ui
import re

from backend import (
    init_database, 
    load_embedding_model, 
    fetch_and_process_emails,
    load_app_config  # load_app_config をインポートリストに追加
)

config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | 案件管理", layout="wide")
ui.apply_global_styles()

st.title("💼 案件管理")
st.markdown("登録されている案件の一覧表示、検索、並び替えができます。")

ITEMS_PER_PAGE = 20 # 1回に読み込む件数

# --- セッションステートの初期化 ---
if 'all_job_ids' not in st.session_state:
    st.session_state.all_job_ids = None
if 'job_display_count' not in st.session_state:
    st.session_state.job_display_count = ITEMS_PER_PAGE
if 'last_job_search_params' not in st.session_state:
    st.session_state.last_job_search_params = {}

# --- UIセクション: 検索とソート ---
search_keyword = st.text_input(
    "キーワード検索",
    placeholder="プロジェクト名、担当者名、業務内容などで検索 (スペース区切りでAND検索)",
    label_visibility="collapsed"
)

st.divider()
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    sort_column = st.selectbox("並び替え", ["登録日", "プロジェクト名", "担当者名"], 0, key="job_sort_col")
with col2:
    sort_order = st.selectbox("順序", ["降順", "昇順"], 0, key="job_sort_order")
with col3:
    st.write(""); st.write("") # スペーサー
    show_hidden = st.checkbox("非表示の案件も表示する", False, key="job_show_hidden")
st.divider()

# --- 検索ロジック ---
current_search_params = {
    "keyword": search_keyword,
    "sort_col": sort_column,
    "sort_order": sort_order,
    "show_hidden": show_hidden,
}

if current_search_params != st.session_state.last_job_search_params:
    with st.spinner("検索中..."):
        # バックエンドから条件に合う全IDリストを取得
        st.session_state.all_job_ids = be.get_filtered_item_ids(
            item_type='jobs', # 対象を 'jobs' に変更
            keyword=search_keyword,
            sort_column=sort_column,
            sort_order=sort_order,
            show_hidden=show_hidden
        )
    
    st.session_state.job_display_count = ITEMS_PER_PAGE
    st.session_state.last_job_search_params = current_search_params
    st.rerun()

# --- 結果表示ロジック ---
all_ids = st.session_state.all_job_ids
if all_ids is None:
    st.info("キーワードを入力して案件を検索してください。")
elif not all_ids:
    st.warning("条件に一致する案件は見つかりませんでした。")
else:
    display_count = st.session_state.job_display_count
    ids_to_display = all_ids[:display_count]
    
    jobs_to_display = be.get_items_by_ids('jobs', ids_to_display)
    
    header_text = f"検索結果: **{len(all_ids)}** 件中、**{len(jobs_to_display)}** 件を表示中"
    st.header(header_text)

    if not jobs_to_display:
        st.warning("表示するデータがありません。")
    else:
        for job in jobs_to_display:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    # ご提示のコードの表示ロジックを流用
                    project_name = job['project_name'] or f"案件 (ID: {job['id']})"
                    title_display = f"#### {project_name}"
                    if job['is_hidden']:
                        title_display += " <span style='color: #888;'>(非表示)</span>"
                    st.markdown(title_display, unsafe_allow_html=True)
                    doc_parts = job['document'].split('\n---\n', 1)
                    preview_text = (doc_parts[1] if len(doc_parts) > 1 else job['document']).replace('\n',' ')
                    st.caption(preview_text[:250] + "...")
                with col2:
                    if job.get('assigned_username'):
                        st.markdown(f"👤 **担当:** {job['assigned_username']}")
                    st.markdown(f"**ID:** {job['id']}")
                    if st.button("詳細を見る", key=f"detail_job_{job['id']}", use_container_width=True):
                        st.session_state['selected_job_id'] = job['id']
                        st.switch_page("pages/6_案件詳細.py") # ファイル名に合わせて修正

    # --- 「Load More」ボタン ---
    if display_count < len(all_ids):
        st.divider()
        _, col_btn, _ = st.columns([2, 1, 2])
        with col_btn:
            if st.button(f"さらに {min(ITEMS_PER_PAGE, len(all_ids) - display_count)} 件読み込む", use_container_width=True):
                st.session_state.job_display_count += ITEMS_PER_PAGE
                st.rerun()

# --- フッター ---
ui.display_footer()
