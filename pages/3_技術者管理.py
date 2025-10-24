import streamlit as st
import backend as be
import ui_components as ui
import re

# --- ページ設定と初期化 ---
st.set_page_config(page_title="技術者管理", layout="wide")
st.title("👨‍💻 技術者管理")
st.markdown("登録されている技術者の一覧表示、検索、並び替えができます。")

ITEMS_PER_PAGE = 20 # 1回に読み込む件数

# --- セッションステートの初期化 ---
# Load More方式で管理する状態
if 'all_engineer_ids' not in st.session_state:
    st.session_state.all_engineer_ids = None
if 'display_count' not in st.session_state:
    st.session_state.display_count = ITEMS_PER_PAGE
# 検索条件の変更を検知するための状態
if 'last_eng_search_params' not in st.session_state:
    st.session_state.last_eng_search_params = {}

# --- UIセクション: 検索とソート ---
with st.container():
    search_keyword = st.text_input(
        "キーワード検索",
        placeholder="氏名、スキル、経歴などで検索 (スペース区切りでAND検索)",
        label_visibility="collapsed"
    )

st.divider()
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    sort_column = st.selectbox("並び替え", ["登録日", "氏名", "担当者名"], 0, key="eng_sort_col")
with col2:
    sort_order = st.selectbox("順序", ["降順", "昇順"], 0, key="eng_sort_order")
with col3:
    st.write(""); st.write("") # スペーサー
    show_hidden = st.checkbox("非表示の技術者も表示する", False, key="eng_show_hidden")
st.divider()

# --- 検索ロジック ---
# 現在の検索条件を辞書としてまとめる
current_search_params = {
    "keyword": search_keyword,
    "sort_col": sort_column,
    "sort_order": sort_order,
    "show_hidden": show_hidden,
}

# 検索条件が変更されたか、または初回表示かチェック
if current_search_params != st.session_state.last_eng_search_params:
    with st.spinner("検索中..."):
        # バックエンドから条件に合う全IDリストを取得
        st.session_state.all_engineer_ids = be.get_filtered_item_ids(
            item_type='engineers',
            keyword=search_keyword,
            sort_column=sort_column,
            sort_order=sort_order,
            show_hidden=show_hidden
        )
    
    # 状態をリセットして再実行
    st.session_state.display_count = ITEMS_PER_PAGE
    st.session_state.last_eng_search_params = current_search_params
    st.rerun()

# --- 結果表示ロジック ---
all_ids = st.session_state.all_engineer_ids
if all_ids is None:
    # アプリケーション初回起動時など
    st.info("検索条件を指定してください。")
elif not all_ids:
    st.warning("条件に一致する技術者は見つかりませんでした。")
else:
    display_count = st.session_state.display_count
    ids_to_display = all_ids[:display_count]
    
    # 表示するデータだけをDBから取得
    engineers_to_display = be.get_items_by_ids('engineers', ids_to_display)
    
    # ヘッダー表示
    header_text = f"検索結果: **{len(all_ids)}** 名中、**{len(engineers_to_display)}** 名を表示中"
    st.header(header_text)

    # --- 一覧表示ループ ---
    if not engineers_to_display:
        st.warning("表示するデータがありません。")
    else:
        for eng in engineers_to_display:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    # (ご提示のコードの表示ロジックを流用)
                    title_display = f"#### {eng['name'] or 'N/A'}"
                    if eng['is_hidden']:
                        title_display += " <span style='color: #888;'>(非表示)</span>"
                    st.markdown(title_display, unsafe_allow_html=True)
                    doc_parts = eng['document'].split('\n---\n', 1)
                    preview_text = (doc_parts[1] if len(doc_parts) > 1 else eng['document']).replace('\n',' ')
                    st.caption(preview_text[:250] + "...")
                with col2:
                    st.markdown(f"**ID:** {eng['id']}")
                    if st.button("詳細を見る", key=f"detail_{eng['id']}", use_container_width=True):
                        st.session_state['selected_engineer_id'] = eng['id']
                        st.switch_page("pages/5_技術者詳細.py")

    # --- 「Load More」ボタン ---
    if display_count < len(all_ids):
        st.divider()
        _, col_btn, _ = st.columns([2, 1, 2])
        with col_btn:
            if st.button(f"さらに {min(ITEMS_PER_PAGE, len(all_ids) - display_count)} 件読み込む", use_container_width=True):
                st.session_state.display_count += ITEMS_PER_PAGE
                st.rerun()

# --- フッター ---
ui.display_footer()
