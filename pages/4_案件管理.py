# pages/4_案件管理.py (コールバック廃止・最終完成版)

import streamlit as st
import backend as be
import ui_components as ui

# --- ページの基本設定 ---
config = be.load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | 案件管理", layout="wide")
ui.apply_global_styles()

st.title("💼 案件管理")
st.markdown("登録されている案件の一覧表示、検索、並び替えができます。")

ITEMS_PER_PAGE = 20

# --- セッションステートの初期化 ---
if 'job_search_params' not in st.session_state:
    # 検索条件をまとめて辞書で管理
    st.session_state.job_search_params = {
        "keyword": "",
        "user_ids": [],
        "has_matches_only": False,
        "show_hidden": False,
        "sort_column": "登録日",
        "sort_order": "降順"
    }
if 'all_job_ids' not in st.session_state:
    st.session_state.all_job_ids = None
if 'job_display_count' not in st.session_state:
    st.session_state.job_display_count = ITEMS_PER_PAGE


# --- UIセクション: 検索フォーム ---
with st.expander("絞り込み・並び替え", expanded=True):
    with st.form(key="search_form"):
        # 現在の検索条件を読み込み
        params = st.session_state.job_search_params
        
        # --- フォーム内のウィジェット定義 ---
        search_keyword = st.text_input("キーワード", value=params["keyword"], placeholder="プロジェクト名、スキルなどで検索")
        
        all_users = be.get_all_users()
        user_map = {"（未担当）": -1, **{user['username']: user['id'] for user in all_users}}
        id_to_username = {v: k for k, v in user_map.items()}
        default_users = [id_to_username[uid] for uid in params["user_ids"] if uid in id_to_username]
        selected_usernames = st.multiselect("担当者", options=list(user_map.keys()), default=default_users, placeholder="担当者を選択（指定なしは全員対象）")
        
        has_matches_only = st.checkbox("🤝 マッチング結果がある案件のみ表示", value=params["has_matches_only"])
        
        col_sort, col_order, col_hidden = st.columns(3)
        with col_sort:
            sort_options = ["登録日", "プロジェクト名", "担当者名"]
            sort_column = st.selectbox("並び替え", sort_options, index=sort_options.index(params["sort_column"]))
        with col_order:
            order_options = ["降順", "昇順"]
            sort_order = st.selectbox("順序", order_options, index=order_options.index(params["sort_order"]))
        with col_hidden:
            show_hidden = st.checkbox("非表示の案件も表示する", value=params["show_hidden"])

        # --- フォーム送信ボタン ---
        submitted = st.form_submit_button("この条件で検索", type="primary", use_container_width=True)

        if submitted:
            # 「検索」ボタンが押されたら、フォームの現在の値をセッションステートに保存
            st.session_state.job_search_params = {
                "keyword": search_keyword,
                "user_ids": [user_map[name] for name in selected_usernames],
                "has_matches_only": has_matches_only,
                "show_hidden": show_hidden,
                "sort_column": sort_column,
                "sort_order": sort_order
            }
            # 検索実行フラグとページ表示件数をリセット
            st.session_state.execute_search = True
            st.session_state.job_display_count = ITEMS_PER_PAGE
            st.rerun() # 変更を反映し、検索ロジックをキックするために再実行


# --- データ取得ロジック ---
# 初回アクセス時または検索実行時にデータを取得
if st.session_state.all_job_ids is None or st.session_state.get("execute_search"):
    if "execute_search" in st.session_state:
        del st.session_state.execute_search

    params = st.session_state.job_search_params
    with st.spinner("検索中..."):
        all_ids = be.get_filtered_item_ids(
            item_type='jobs',
            keyword=params["keyword"],
            assigned_user_ids=params["user_ids"],
            has_matches_only=params["has_matches_only"],
            sort_column=params["sort_column"],
            sort_order=params["sort_order"],
            show_hidden=params["show_hidden"]
        )
    st.session_state.all_job_ids = all_ids

# --- 結果表示ロジック ---
all_ids = st.session_state.all_job_ids
if not all_ids:
    st.warning("条件に一致する案件は見つかりませんでした。")
else:
    display_count = st.session_state.job_display_count
    ids_to_display = all_ids[:display_count]
    
    if not ids_to_display:
        st.info("これ以上表示する案件がありません。")
    else:
        jobs_to_display = be.get_items_by_ids_sync('jobs', ids_to_display)
        
        st.header(f"検索結果: **{len(all_ids)}** 件中、**{len(jobs_to_display)}** 件を表示中")

        for job in jobs_to_display:
            with st.container(border=True):
                col1, col2, col3 = st.columns([4, 2, 1])
                
                with col1:
                    project_name = job.get('project_name') or f"案件 (ID: {job['id']})"
                    if job.get('is_hidden') == 1:
                        st.markdown(f"##### 🙈 `{project_name}`")
                    else:
                        st.markdown(f"##### {project_name}")
                    
                    doc_parts = job.get('document', '').split('\n---\n', 1)
                    main_doc = doc_parts[1] if len(doc_parts) > 1 else doc_parts[0]
                    st.caption(main_doc.replace('\n', ' ').replace('\r', '')[:100] + "...")

                with col2:
                    match_count = job.get('match_count', 0)
                    if match_count > 0:
                        st.markdown(f"**🤝 `{match_count}`** 件のマッチング")
                    
                    assignee = job.get('assigned_username') or "未担当"
                    st.markdown(f"**担当:** {assignee}")

                with col3:
                    if st.button("詳細を見る", key=f"job_detail_{job['id']}", use_container_width=True):
                        st.session_state['selected_job_id'] = job['id']
                        st.switch_page("pages/6_案件詳細.py")

        # --- 「Load More」ボタン ---
        if display_count < len(all_ids):
            st.divider()
            if st.button(f"さらに {min(ITEMS_PER_PAGE, len(all_ids) - display_count)} 件読み込む", use_container_width=True):
                st.session_state.job_display_count += ITEMS_PER_PAGE
                st.rerun()

# --- フッター ---
ui.display_footer()
