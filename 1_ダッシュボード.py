import streamlit as st
from datetime import datetime, timedelta
from backend import (
    init_database, load_embedding_model, get_db_connection,
    hide_match, load_app_config, get_all_users
)
import os

# --- ヘルパー関数 (変更なし) ---
def get_evaluation_html(grade, font_size='2.5em'):
    if not grade: return ""
    color_map = {'S': '#00b894', 'A': '#28a745', 'B': '#17a2b8', 'C': '#ffc107', 'D': '#fd7e14', 'E': '#dc3545'}
    color = color_map.get(grade.upper(), '#6c757d') 
    style = f"color: {color}; font-size: {font_size}; font-weight: bold; text-align: center; line-height: 1; padding-top: 10px;"
    html_code = f"<div style='text-align: center; margin-bottom: 5px;'><span style='{style}'>{grade.upper()}</span></div><div style='text-align: center; font-size: 0.8em; color: #888;'>判定</div>"
    return html_code

def get_status_badge(status):
    if not status: status = "新規"
    status_color_map = {
        "新規": "#6c757d", "提案準備中": "#17a2b8", "提案中": "#007bff",
        "クライアント面談": "#fd7e14", "結果待ち": "#ffc107", "採用": "#28a745",
        "見送り（自社都合）": "#dc3545", "見送り（クライアント都合）": "#dc3545",
        "見送り（技術者都合）": "#dc3545", "クローズ": "#343a40"
    }
    color = status_color_map.get(status, "#6c757d")
    style = f"background-color: {color}; color: white; padding: 0.2em 0.6em; border-radius: 0.8rem; font-size: 0.8em; font-weight: 600; display: inline-block; margin-top: 5px;"
    return f"<span style='{style}'>{status}</span>"

# --- アプリケーションの初期化 ---
init_database()
load_embedding_model()

config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | ダッシュボード", layout="wide")

# --- ページング設定の初期化 ---
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'items_per_page' not in st.session_state:
    st.session_state.items_per_page = 10 

# --- サイドバーフィルター ---
st.sidebar.header("フィルター")
all_users = get_all_users()
user_names = [user['username'] for user in all_users]
assignee_options = ["すべて"] + user_names 
job_assignee_filter = st.sidebar.selectbox("案件担当者", options=assignee_options, key="job_assignee_filter")
engineer_assignee_filter = st.sidebar.selectbox("技術者担当者", options=assignee_options, key="engineer_assignee_filter")

status_options = [
    "新規", "提案準備中", "提案中", "クライアント面談", "結果待ち", 
    "採用", "見送り（自社都合）", "見送り（クライアント都合）", "見送り（技術者都合）", "クローズ"
]
selected_statuses = st.sidebar.multiselect("進捗ステータス", options=status_options, placeholder="ステータスを選択して絞り込み")

grade_options = ['S','A', 'B', 'C', 'D', 'E']
selected_grades = st.sidebar.multiselect("AI評価", options=grade_options, placeholder="評価を選択して絞り込み")

keyword_filter = st.sidebar.text_input("キーワード検索")

filter_nationality = st.sidebar.checkbox("「外国籍不可」の案件を除外する", value=False)
show_hidden_filter = st.sidebar.checkbox("非表示も表示する", value=False)

st.header("最新マッチング結果一覧")

# --- DBからフィルタリングされた結果を取得 ---
conn = get_db_connection()
query = '''
    SELECT 
        r.id as res_id, r.job_id, j.document as job_doc, j.project_name, j.is_hidden as job_is_hidden,
        r.engineer_id, e.document as eng_doc, e.name as engineer_name, e.is_hidden as engineer_is_hidden,
        r.score, r.created_at, r.is_hidden as match_is_hidden, r.grade, r.status,
        job_user.username as job_assignee, eng_user.username as engineer_assignee
    FROM matching_results r
    JOIN jobs j ON r.job_id = j.id
    JOIN engineers e ON r.engineer_id = e.id
    LEFT JOIN users job_user ON j.assigned_user_id = job_user.id
    LEFT JOIN users eng_user ON e.assigned_user_id = eng_user.id
'''
params = []
where_clauses = []

if job_assignee_filter != "すべて":
    where_clauses.append("job_user.username = %s")
    params.append(job_assignee_filter)

if engineer_assignee_filter != "すべて":
    where_clauses.append("eng_user.username = %s")
    params.append(engineer_assignee_filter)

if selected_statuses:
    where_clauses.append("r.status = ANY(%s)")
    params.append(list(selected_statuses))

if selected_grades:
    where_clauses.append("r.grade = ANY(%s)")
    params.append(list(selected_grades))

if keyword_filter: 
    where_clauses.append("(j.document ILIKE %s OR e.document ILIKE %s OR j.project_name ILIKE %s OR e.name ILIKE %s OR job_user.username ILIKE %s OR eng_user.username ILIKE %s OR r.status ILIKE %s)")
    keyword_param = f'%{keyword_filter}%'
    params.extend([keyword_param] * 7)

# ▼▼▼【ここが修正箇所】▼▼▼
# 'r.is_hidden' を正しいエイリアス 'r.match_is_hidden' に修正
if not show_hidden_filter:
    where_clauses.append("((r.match_is_hidden = 0 OR r.match_is_hidden IS NULL) AND j.is_hidden = 0 AND e.is_hidden = 0)")
# ▲▲▲【修正ここまで】▲▲▲

if where_clauses:
    query += " WHERE " + " AND ".join(where_clauses)

query += " ORDER BY r.created_at DESC, r.score DESC"

with conn.cursor() as cursor:
    cursor.execute(query, tuple(params))
    results = cursor.fetchall()
conn.close()

# --- 結果のフィルタリング (国籍) ---
if not results:
    st.info("フィルタリング条件に合致するマッチング結果はありませんでした。")
else:
    results_to_display = []
    if filter_nationality:
        for res in results:
            job_doc = res['job_doc'] or ""
            eng_doc = res['eng_doc'] or ""
            if "外国籍不可" in job_doc or "日本人" in job_doc:
                if "国籍: 日本" not in eng_doc:
                    continue
            results_to_display.append(res)
    else:
        results_to_display = results
    
    if not results_to_display:
        st.warning("AIが提案したマッチングはありましたが、ルールフィルターによってすべて除外されました。")
    else:
        total_items = len(results_to_display)

        # --- ヘッダーと表示件数設定 ---
        header_cols = st.columns([3, 1])
        with header_cols[0]:
            st.write(f"**表示中のマッチング結果: {total_items}件**")
        with header_cols[1]:
            items_per_page_options = [5, 10, 20, 50]
            
            new_items_per_page = st.selectbox(
                "表示件数",
                options=items_per_page_options,
                index=items_per_page_options.index(st.session_state.items_per_page),
                key="items_per_page_selector",
                label_visibility="collapsed"
            )
            
            if new_items_per_page != st.session_state.items_per_page:
                st.session_state.items_per_page = new_items_per_page
                st.session_state.current_page = 1
                st.rerun()

        total_pages = (total_items + st.session_state.items_per_page - 1) // st.session_state.items_per_page

        # ページネーションコントロール
        if total_pages > 1:
            st.markdown("---")
            pagination_cols = st.columns([1, 2, 1])
            with pagination_cols[0]:
                if st.button("前のページ", key="prev_page_btn", disabled=(st.session_state.current_page <= 1)):
                    st.session_state.current_page -= 1
                    st.rerun()
            with pagination_cols[1]:
                st.markdown(f"<p style='text-align: center; font-weight: bold;'>ページ {st.session_state.current_page} / {total_pages}</p>", unsafe_allow_html=True)
            with pagination_cols[2]:
                if st.button("次のページ", key="next_page_btn", disabled=(st.session_state.current_page >= total_pages)):
                    st.session_state.current_page += 1
                    st.rerun()
            st.markdown("---")

        start_index = (st.session_state.current_page - 1) * st.session_state.items_per_page
        end_index = start_index + st.session_state.items_per_page
        paginated_results = results_to_display[start_index:end_index]

        # --- マッチング結果の表示ループ ---
        for res in paginated_results:
            is_archived = res['match_is_hidden'] or res['job_is_hidden'] or res['engineer_is_hidden']
            container_style = "opacity: 0.5; background-color: #262730;" if is_archived else ""
            st.markdown(f"<div style='{container_style} border: 1px solid #333; border-radius: 0.5rem; padding: 1rem; margin-bottom: 1rem;'>", unsafe_allow_html=True)
            
            header_col1, header_col2 = st.columns([5, 2])
            with header_col1:
                created_at_dt = res['created_at']
                if created_at_dt:
                    st.caption(f"マッチング日時: {created_at_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            with header_col2:
                status_html = get_status_badge(res['status'])
                if is_archived:
                    status_html += " <span style='background-color: #444; color: #aaa; padding: 0.2em 0.6em; border-radius: 0.8rem; font-size: 0.8em; font-weight: 600;'>非表示</span>"
                st.markdown(f"<div style='text-align: right;'>{status_html}</div>", unsafe_allow_html=True)

            col1, col2, col3 = st.columns([5, 2, 5])
            
            with col1:
                project_name = res['project_name'] or f"案件(ID: {res['job_id']})"
                if res['job_is_hidden']:
                    project_name += " <span style='color: #888; font-size: 0.8em;'>(案件 非表示)</span>"
                st.markdown(f"##### 💼 {project_name}", unsafe_allow_html=True)
                if res['job_assignee']:
                    st.caption(f"**担当:** {res['job_assignee']}")
                job_doc_summary = (res['job_doc'].split('\n---\n', 1)[-1]).replace('\n', ' ').replace('\r', '')[:150]
                st.caption(f"{job_doc_summary}...")
                
            with col2:
                st.markdown(get_evaluation_html(res['grade']), unsafe_allow_html=True)
                button_style = "display: block; padding: 0.5rem; background-color: #ff4b4b; color: white; text-align: center; text-decoration: none; border-radius: 0.5rem; font-weight: 600; margin-top: 10px; border: 1px solid #ff4b4b;"
                link = f'<a href="/マッチング詳細?result_id={res["res_id"]}" target="_blank" style="{button_style}">詳細を見る</a>'
                st.markdown(link, unsafe_allow_html=True)

            with col3:
                engineer_name = res['engineer_name'] or f"技術者(ID: {res['engineer_id']})"
                if res['engineer_is_hidden']:
                    engineer_name += " <span style='color: #888; font-size: 0.8em;'>(技術者 非表示)</span>"
                st.markdown(f"##### 👤 {engineer_name}", unsafe_allow_html=True)
                if res['engineer_assignee']:
                    st.caption(f"**担当:** {res['engineer_assignee']}")
                eng_doc_summary = (res['eng_doc'].split('\n---\n', 1)[-1]).replace('\n', ' ').replace('\r', '')[:150]
                st.caption(f"{eng_doc_summary}...")
            
            st.markdown("</div>", unsafe_allow_html=True)
