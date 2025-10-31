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




# ▼▼▼【ここからが全面的に修正する箇所】▼▼▼

# --- UIセクション: 検索フォーム ---
with st.form(key="search_form"):
    st.subheader("絞り込み条件")
    
    # --- 1行目: キーワードと担当者 ---
    col1, col2 = st.columns([2, 1])
    with col1:
        search_keyword = st.text_input(
            "キーワード",
            placeholder="プロジェクト名、業務内容などで検索 (スペース区切りでAND検索)"
        )
    with col2:
        all_users = be.get_all_users()
        user_map = {user['username']: user['id'] for user in all_users}
        selected_usernames = st.multiselect(
            "担当者",
            options=list(user_map.keys()),
            placeholder="担当者を選択（複数可）"
        )
        
    # --- 2行目: ソート順と表示オプション ---
    col3, col4, col5 = st.columns([1, 1, 2])
    with col3:
        sort_column = st.selectbox("並び替え", ["登録日", "プロジェクト名", "担当者名"], 0)
    with col4:
        sort_order = st.selectbox("順序", ["降順", "昇順"], 0)
    with col5:
        st.write("") # スペーサー
        show_hidden = st.checkbox("非表示の案件も表示する", False)

    # --- フォームの送信ボタン ---
    st.divider()
    submitted = st.form_submit_button("この条件で検索する", type="primary", use_container_width=True)


# --- 検索ロジック ---
# フォームが送信された場合にのみ検索を実行
if submitted:
    with st.spinner("検索中..."):
        selected_user_ids = [user_map[name] for name in selected_usernames]

        st.session_state.all_job_ids = be.get_filtered_item_ids(
            item_type='jobs',
            keyword=search_keyword,
            assigned_user_ids=selected_user_ids,
            sort_column=sort_column,
            sort_order=sort_order,
            show_hidden=show_hidden
        )
    
    # 検索が実行されたら、表示件数をリセット
    st.session_state.job_display_count = ITEMS_PER_PAGE
    # st.rerun() は不要。フォーム送信で自動的に再実行される。

# ▲▲▲【修正ここまで】▲▲▲



# --- 結果表示ロジック ---
all_ids = st.session_state.all_job_ids
if all_ids is None:
    st.info("検索条件を入力し、「この条件で検索する」ボタンを押してください。")
elif not all_ids:
    st.warning("条件に一致する案件は見つかりませんでした。")
else:
    display_count = st.session_state.job_display_count
    ids_to_display = all_ids[:display_count]
    
    jobs_to_display = be.get_items_by_ids_sync('jobs', ids_to_display)
    
    header_text = f"検索結果: **{len(all_ids)}** 件中、**{len(jobs_to_display)}** 件を表示中"
    st.header(header_text)

    if not jobs_to_display:
        st.warning("表示するデータがありません。")
    else:
        
        for job in jobs_to_display:
            with st.container(border=True):
                col1, col2, col3 = st.columns([4, 2, 1])
                
                with col1:
                    project_name = job.get('project_name') or f"案件 (ID: {job['id']})"
                    if job.get('is_hidden') == 1:
                        st.markdown(f"##### 🙈 `{project_name}`")
                    else:
                        st.markdown(f"##### {project_name}")
                    
                    # documentからメタ情報を除いた本文だけをプレビュー表示
                    doc_parts = job.get('document', '').split('\n---\n', 1)
                    main_doc = doc_parts[1] if len(doc_parts) > 1 else doc_parts[0]
                    st.caption(main_doc.replace('\n', ' ').replace('\r', '')[:100] + "...")

                with col2:
                    # ★★★【ここからが修正の核】★★★
                    match_count = job.get('match_count', 0)
                    if match_count > 0:
                        st.markdown(f"**🤝 `{match_count}`** 件のマッチ")
                    # ★★★【修正ここまで】★★★

                    assignee = job.get('assigned_username') or "未担当"
                    st.markdown(f"**担当:** {assignee}")

                with col3:
                    if st.button("詳細を見る", key=f"job_detail_{job['id']}", use_container_width=True):
                        st.session_state['selected_job_id'] = job['id']
                        st.switch_page("pages/6_案件詳細.py")


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
