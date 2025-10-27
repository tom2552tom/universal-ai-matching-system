import streamlit as st
import backend as be
import ui_components as ui
import re

# --- ページ設定など ---
config = be.load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | 技術者管理", layout="wide")
ui.apply_global_styles()

st.title("👨‍💻 技術者管理")
st.markdown("登録されている技術者の一覧表示、検索、並び替えができます。")

ITEMS_PER_PAGE = 20

# --- セッションステート初期化 ---
if 'all_engineer_ids' not in st.session_state:
    st.session_state.all_engineer_ids = None
if 'eng_display_count' not in st.session_state: # キー名を案件管理と区別
    st.session_state.eng_display_count = ITEMS_PER_PAGE

# ▼▼▼【ここからが全面的に修正する箇所】▼▼▼

# --- UIセクション: 検索フォーム ---
with st.form(key="engineer_search_form"):
    st.subheader("絞り込み条件")
    
    # --- 1行目: キーワードと担当者 ---
    col1, col2 = st.columns([2, 1])
    with col1:
        search_keyword = st.text_input(
            "キーワード",
            placeholder="氏名、スキル、経歴などで検索 (スペース区切りでAND検索)"
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
        sort_column = st.selectbox("並び替え", ["登録日", "氏名", "担当者名"], 0)
    with col4:
        sort_order = st.selectbox("順序", ["降順", "昇順"], 0)
    with col5:
        st.write("") # スペーサー
        show_hidden = st.checkbox("非表示の技術者も表示する", False)

    # --- フォームの送信ボタン ---
    st.divider()
    submitted = st.form_submit_button("この条件で検索する", type="primary", use_container_width=True)


# --- 検索ロジック ---
# フォームが送信された場合にのみ検索を実行
if submitted:
    with st.spinner("検索中..."):
        selected_user_ids = [user_map[name] for name in selected_usernames]

        st.session_state.all_engineer_ids = be.get_filtered_item_ids(
            item_type='engineers',
            keyword=search_keyword,
            assigned_user_ids=selected_user_ids,
            sort_column=sort_column,
            sort_order=sort_order,
            show_hidden=show_hidden
        )
    
    # 検索が実行されたら、表示件数をリセット
    st.session_state.eng_display_count = ITEMS_PER_PAGE

# ▲▲▲【修正ここまで】▲▲▲


# --- 結果表示ロジック ---
all_ids = st.session_state.all_engineer_ids
if all_ids is None:
    st.info("検索条件を入力し、「この条件で検索する」ボタンを押してください。")
elif not all_ids:
    st.warning("条件に一致する技術者は見つかりませんでした。")
else:
    display_count = st.session_state.eng_display_count
    ids_to_display = all_ids[:display_count]
    
    engineers_to_display = be.get_items_by_ids('engineers', ids_to_display)
    
    header_text = f"検索結果: **{len(all_ids)}** 名中、**{len(engineers_to_display)}** 名を表示中"
    st.header(header_text)

    if not engineers_to_display:
        st.warning("表示するデータがありません。")
    else:
        for eng in engineers_to_display:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    title_display = f"#### {eng['name'] or 'N/A'}"
                    if eng['is_hidden']:
                        title_display += " <span style='color: #888;'>(非表示)</span>"
                    st.markdown(title_display, unsafe_allow_html=True)
                    doc_parts = eng['document'].split('\n---\n', 1)
                    preview_text = (doc_parts[1] if len(doc_parts) > 1 else eng['document']).replace('\n',' ')
                    st.caption(preview_text[:250] + "...")
                with col2:
                    if eng.get('assigned_username'):
                        st.markdown(f"👤 **担当:** {eng['assigned_username']}")
                    st.markdown(f"**ID:** {eng['id']}")
                    if st.button("詳細を見る", key=f"detail_{eng['id']}", use_container_width=True):
                        st.session_state['selected_engineer_id'] = eng['id']
                        st.switch_page("pages/5_技術者詳細.py") # .py を削除

    # --- 「Load More」ボタン ---
    if all_ids and display_count < len(all_ids): # all_idsが存在することを確認
        st.divider()
        _, col_btn, _ = st.columns([2, 1, 2])
        with col_btn:
            if st.button(f"さらに {min(ITEMS_PER_PAGE, len(all_ids) - display_count)} 件読み込む", use_container_width=True):
                st.session_state.eng_display_count += ITEMS_PER_PAGE
                st.rerun()

# --- フッター ---
ui.display_footer()
