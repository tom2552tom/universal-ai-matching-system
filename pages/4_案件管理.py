# pages/4_案件管理.py (最終完成版)

import streamlit as st
import backend as be
import ui_components as ui
from datetime import datetime


# --- ページの基本設定 ---
config = be.load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | 案件管理", layout="wide")
ui.apply_global_styles()
if not ui.check_password():
    st.stop() # 認証が通らない場合、ここで処理を停止

    
st.title("💼 案件管理")


st.markdown("登録されている案件の一覧表示、検索、並び替えができます。")

ITEMS_PER_PAGE = 20

# --- セッションステートの初期化 ---
# このページ専用のキーを使い、他のページと状態が衝突しないようにする
if 'job_search_params' not in st.session_state:
    st.session_state.job_search_params = {
        "keyword": "",
        "user_ids": [],
        "has_matches_only": False,
        "auto_match_only": False, # 自動マッチングフィルターの初期値
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
    with st.form(key="job_search_form"):
        params = st.session_state.job_search_params
        
        # --- フォーム内のウィジェット定義 ---
        search_keyword = st.text_input("キーワード", value=params["keyword"], placeholder="プロジェクト名、スキルなどで検索")
        
        all_users = be.get_all_users()
        user_map = {"（未割当）": -1, **{user['username']: user['id'] for user in all_users}}
        id_to_username = {v: k for k, v in user_map.items()}
        default_users = [id_to_username[uid] for uid in params["user_ids"] if uid in id_to_username]
        selected_usernames = st.multiselect("担当者", options=list(user_map.keys()), default=default_users, placeholder="担当者を選択（指定なしは全員対象）")
        
        # --- オプションのチェックボックス ---
        col1, col2 = st.columns(2)
        with col1:
            has_matches_only = st.checkbox("🤝 マッチング結果がある案件のみ表示", value=params["has_matches_only"])
        with col2:
            auto_match_only = st.checkbox("🤖 自動マッチング依頼中のみ表示", value=params["auto_match_only"])
        
        # --- ソートと非表示設定 ---
        col3, col4, col5 = st.columns(3)
        with col3:
            sort_options = ["登録日", "プロジェクト名", "担当者名"]
            sort_column = st.selectbox("並び替え", sort_options, index=sort_options.index(params["sort_column"]))
        with col4:
            order_options = ["降順", "昇順"]
            sort_order = st.selectbox("順序", order_options, index=order_options.index(params["sort_order"]))
        with col5:
            show_hidden = st.checkbox("非表示の案件も表示する", value=params["show_hidden"])

        # --- フォーム送信ボタン ---
        submitted = st.form_submit_button("この条件で検索", type="primary", use_container_width=True)

        if submitted:
            # 「検索」ボタンが押されたら、フォームの現在の値をセッションステートに保存
            st.session_state.job_search_params = {
                "keyword": search_keyword,
                "user_ids": [user_map[name] for name in selected_usernames],
                "has_matches_only": has_matches_only,
                "auto_match_only": auto_match_only,
                "show_hidden": show_hidden,
                "sort_column": sort_column,
                "sort_order": sort_order
            }
            # 検索実行フラグと表示件数をリセット
            st.session_state.execute_search = True
            st.session_state.job_display_count = ITEMS_PER_PAGE
            st.rerun()


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
            auto_match_only=params["auto_match_only"],
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
    
    if ids_to_display:
        jobs_to_display = be.get_items_by_ids_sync('jobs', ids_to_display) # ★ item_type を 'jobs' に変更
        
        st.header(f"検索結果: **{len(all_ids)}** 件中、**{len(jobs_to_display)}** 件を表示中")



        # ▼▼▼【ここからが移植・修正の核】▼▼▼
        for job in jobs_to_display:
            with st.container(border=True):
                st.markdown('<div class="card-container">', unsafe_allow_html=True)

                # --- 左側のコンテンツエリア ---
                st.markdown('<div class="card-content">', unsafe_allow_html=True)

                project_name = job.get('project_name') or f"案件 (ID: {job['id']})"
                if job.get('is_hidden') == 1:
                    st.markdown(f"##### 🙈 `{project_name}`")
                else:
                    st.markdown(f"##### {project_name}")

                assignee = job.get('assigned_username') or "未担当"
                created_at_obj = job.get('created_at')
                created_at_str = be.convert_to_jst_str(created_at_obj) if isinstance(created_at_obj, datetime) else "不明"
                st.caption(f"ID: {job['id']} | 担当: {assignee} | 登録日: {created_at_str}")

                doc_parts = job.get('document', '').split('\n---\n', 1)
                main_doc = doc_parts[1] if len(doc_parts) > 1 else doc_parts[0]
                st.caption(main_doc.replace('\n', ' ').replace('\r', '')[:200] + "...")

                def create_chip_html(icon, label):
                    style = """
                        display: inline-flex; align-items: center; background-color: #31333F;
                        color: #FAFAFA; padding: 4px 10px; border-radius: 16px;
                        font-size: 0.8rem; margin-right: 6px; margin-bottom: 6px; border: 1px solid #4A4A4A;
                    """
                    return f'<span style="{style}">{icon} {label}</span>'

                chips_html = ""
                if job.get('auto_match_active'): chips_html += create_chip_html("🤖", "自動マッチ")
                if (match_count := job.get('match_count', 0)) > 0: chips_html += create_chip_html("🤝", f"{match_count} 件")
                if chips_html: st.markdown(f"<div style='margin-top: auto;'>{chips_html}</div>", unsafe_allow_html=True)

                st.markdown('</div>', unsafe_allow_html=True)

                # --- 右側のアクションエリア ---
                st.markdown('<div class="card-actions">', unsafe_allow_html=True)

                if st.button("詳細を見る", key=f"job_detail_{job['id']}", use_container_width=True):
                    st.session_state['selected_job_id'] = job['id']
                    st.switch_page("pages/6_案件詳細.py")

                st.markdown('</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
        # ▲▲▲【移植・修正ここまで】▲▲▲




    if display_count < len(all_ids):
        st.divider()
        if st.button(f"さらに {min(ITEMS_PER_PAGE, len(all_ids) - display_count)} 件読み込む", use_container_width=True):
            st.session_state.job_display_count += ITEMS_PER_PAGE # ★キーを変更
            st.rerun()

ui.display_footer()
