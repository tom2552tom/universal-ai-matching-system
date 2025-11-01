# pages/3_技術者管理.py (最終完成版)

import streamlit as st
import backend as be
import ui_components as ui

# --- ページの基本設定 ---
config = be.load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | 技術者管理", layout="wide")
ui.apply_global_styles()

st.title("👤 技術者管理")
st.markdown("登録されている技術者の一覧表示、検索、並び替えができます。")

ITEMS_PER_PAGE = 20

# --- セッションステートの初期化 ---
# このページ専用のキーを使い、案件管理ページと状態が衝突しないようにする
if 'engineer_search_params' not in st.session_state:
    st.session_state.engineer_search_params = {
        "keyword": "",
        "user_ids": [],
        "has_matches_only": False,
        "show_hidden": False,
        "sort_column": "登録日",
        "sort_order": "降順"
    }
if 'all_engineer_ids' not in st.session_state:
    st.session_state.all_engineer_ids = None
if 'engineer_display_count' not in st.session_state:
    st.session_state.engineer_display_count = ITEMS_PER_PAGE


# --- UIセクション: 検索フォーム ---
with st.expander("絞り込み・並び替え", expanded=True):
    with st.form(key="engineer_search_form"):
        params = st.session_state.engineer_search_params
        
        # --- フォーム内のウィジェット定義 ---
        search_keyword = st.text_input("キーワード", value=params["keyword"], placeholder="氏名、スキル、経歴などで検索")
        
        all_users = be.get_all_users()
        user_map = {"（未担当）": -1, **{user['username']: user['id'] for user in all_users}}
        id_to_username = {v: k for k, v in user_map.items()}
        default_users = [id_to_username[uid] for uid in params["user_ids"] if uid in id_to_username]
        selected_usernames = st.multiselect("担当者", options=list(user_map.keys()), default=default_users, placeholder="担当者を選択（指定なしは全員対象）")
        
        has_matches_only = st.checkbox("🤝 マッチング結果がある技術者のみ表示", value=params["has_matches_only"])
        
        col_sort, col_order, col_hidden = st.columns(3)
        with col_sort:
            # 技術者管理用のソートオプション
            sort_options = ["登録日", "氏名", "担当者名"]
            sort_column = st.selectbox("並び替え", sort_options, index=sort_options.index(params["sort_column"]))
        with col_order:
            order_options = ["降順", "昇順"]
            sort_order = st.selectbox("順序", order_options, index=order_options.index(params["sort_order"]))
        with col_hidden:
            show_hidden = st.checkbox("非表示の技術者も表示する", value=params["show_hidden"])

        # --- フォーム送信ボタン ---
        submitted = st.form_submit_button("この条件で検索", type="primary", use_container_width=True)

        if submitted:
            st.session_state.engineer_search_params = {
                "keyword": search_keyword,
                "user_ids": [user_map[name] for name in selected_usernames],
                "has_matches_only": has_matches_only,
                "show_hidden": show_hidden,
                "sort_column": sort_column,
                "sort_order": sort_order
            }
            st.session_state.execute_engineer_search = True
            st.session_state.engineer_display_count = ITEMS_PER_PAGE
            st.rerun()


# --- データ取得ロジック ---
if st.session_state.all_engineer_ids is None or st.session_state.get("execute_engineer_search"):
    if "execute_engineer_search" in st.session_state:
        del st.session_state.execute_engineer_search

    params = st.session_state.engineer_search_params
    with st.spinner("検索中..."):
        all_ids = be.get_filtered_item_ids(
            item_type='engineers', # ★★★ item_type を 'engineers' に変更 ★★★
            keyword=params["keyword"],
            assigned_user_ids=params["user_ids"],
            has_matches_only=params["has_matches_only"],
            sort_column=params["sort_column"],
            sort_order=params["sort_order"],
            show_hidden=params["show_hidden"]
        )
    st.session_state.all_engineer_ids = all_ids

# --- 結果表示ロジック ---
all_ids = st.session_state.all_engineer_ids
if not all_ids:
    st.warning("条件に一致する技術者は見つかりませんでした。")
else:
    display_count = st.session_state.engineer_display_count
    ids_to_display = all_ids[:display_count]
    
    if not ids_to_display:
        st.info("これ以上表示する技術者がいません。")
    else:
        engineers_to_display = be.get_items_by_ids_sync('engineers', ids_to_display)
        
        st.header(f"検索結果: **{len(all_ids)}** 件中、**{len(engineers_to_display)}** 件を表示中")

        for engineer in engineers_to_display:
            with st.container(border=True):
                col1, col2, col3 = st.columns([4, 2, 1])
                
                with col1:
                    engineer_name = engineer.get('name') or f"技術者 (ID: {engineer['id']})"
                    if engineer.get('is_hidden') == 1:
                        st.markdown(f"##### 🙈 `{engineer_name}`")
                    else:
                        st.markdown(f"##### {engineer_name}")
                    
                    doc_parts = engineer.get('document', '').split('\n---\n', 1)
                    main_doc = doc_parts[1] if len(doc_parts) > 1 else doc_parts[0]
                    st.caption(main_doc.replace('\n', ' ').replace('\r', '')[:100] + "...")

                with col2:
                    match_count = engineer.get('match_count', 0)
                    if match_count > 0:
                        st.markdown(f"**🤝 `{match_count}`** 件のマッチング")
                    
                    assignee = engineer.get('assigned_username') or "未担当"
                    st.markdown(f"**担当:** {assignee}")

                with col3:
                    if st.button("詳細を見る", key=f"eng_detail_{engineer['id']}", use_container_width=True):
                        st.session_state['selected_engineer_id'] = engineer['id']
                        st.switch_page("pages/5_技術者詳細.py")

        # --- 「Load More」ボタン ---
        if display_count < len(all_ids):
            st.divider()
            if st.button(f"さらに {min(ITEMS_PER_PAGE, len(all_ids) - display_count)} 件読み込む", use_container_width=True):
                st.session_state.engineer_display_count += ITEMS_PER_PAGE
                st.rerun()

# --- フッター ---
ui.display_footer()
