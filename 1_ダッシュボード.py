import streamlit as st
from datetime import datetime, timedelta
from backend import (
    init_database, load_embedding_model, get_db_connection,
    hide_match, load_app_config, get_all_users
)
from streamlit_cookies_manager import CookieManager


# ヘルパー関数 (変更なし)
def get_evaluation_html(grade, font_size='2.5em'):
    if not grade: return ""
    color_map = {'A': '#28a745', 'B': '#17a2b8', 'C': '#ffc107', 'D': '#fd7e14', 'E': '#dc3545'}
    color = color_map.get(grade.upper(), '#6c757d') 
    style = f"color: {color}; font-size: {font_size}; font-weight: bold; text-align: center; line-height: 1; padding-top: 10px;"
    html_code = f"<div style='text-align: center; margin-bottom: 5px;'><span style='{style}'>{grade.upper()}</span></div><div style='text-align: center; font-size: 0.8em; color: #888;'>判定</div>"
    return html_code

# --- アプリケーションの初期化 ---
init_database()
load_embedding_model()

config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | ダッシュボード", layout="wide")

if 'cookies_manager' not in st.session_state:
    st.session_state.cookies_manager = CookieManager()
    st.session_state.cookies_manager.ready()

st.image("img/UniversalAI_logo.png", width=240)

sales_notice_message = config.get("messages", {}).get("sales_staff_notice")
if sales_notice_message:
    st.markdown(sales_notice_message, unsafe_allow_html=True)

st.divider()

# ページングの初期設定
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'items_per_page' not in st.session_state:
    st.session_state.items_per_page = 10 

st.sidebar.subheader("ページング設定")
items_per_page_options = [5, 10, 20, 50]
st.session_state.items_per_page = st.sidebar.selectbox(
    "1ページあたりの表示件数",
    options=items_per_page_options,
    index=items_per_page_options.index(st.session_state.items_per_page),
    key="items_per_page_selector"
)

# --- サイドバー (フィルター) ---
st.sidebar.header("フィルター")

all_users = get_all_users()
user_names = [user['username'] for user in all_users]
assignee_options = ["すべて"] + user_names 

job_assignee_filter = st.sidebar.selectbox("案件担当者", options=assignee_options, key="job_assignee_filter")
engineer_assignee_filter = st.sidebar.selectbox("技術者担当者", options=assignee_options, key="engineer_assignee_filter")
st.sidebar.divider()

grade_options = ['S','A', 'B', 'C', 'D', 'E']
cookie_key_grades = "selected_grades_filter"

default_grades_from_cookie = st.session_state.cookies_manager.get(cookie_key_grades)
if default_grades_from_cookie:
    try:
        default_grades_from_cookie = [g.strip() for g in default_grades_from_cookie.split(',') if g.strip() in grade_options]
    except Exception:
        default_grades_from_cookie = []
else:
    default_grades_from_cookie = []

selected_grades = st.sidebar.multiselect(
    "AI評価",
    options=grade_options,
    default=default_grades_from_cookie,
    placeholder="評価を選択して絞り込み",
    key="ai_grade_filter"
)

if selected_grades != default_grades_from_cookie:
    st.session_state.cookies_manager.set(cookie_key_grades, ",".join(selected_grades))
    st.session_state.cookies_manager.save()

min_score_filter = 0 

today = datetime.now().date()
default_start_date = today - timedelta(days=30)
keyword_filter = st.sidebar.text_input("キーワード検索 (担当者名も可)")

st.sidebar.divider()
st.sidebar.header("ルールフィルター")
filter_nationality = st.sidebar.checkbox("「外国籍不可」の案件を除外する", value=False)
show_hidden_filter = st.sidebar.checkbox("非表示も表示する", value=False)

# ▼▼▼ 変更点 1: ソートオプションをサイドバーに追加 ▼▼▼
st.sidebar.divider()
st.sidebar.header("ソート設定")
sort_by_options = {
    "マッチ日": "created_at",
    "AI評価": "grade",
    "マッチ度": "score" # マッチ度は非表示ですが、ソートキーとしては残しておきます
}
selected_sort_by_display = st.sidebar.selectbox("ソート基準", options=list(sort_by_options.keys()), key="sort_by")

sort_order_options = {
    "マッチ日": {"新しい順": "DESC", "古い順": "ASC"},
    "AI評価": {"良い順 (S→E)": "ASC", "悪い順 (E→S)": "DESC"},
    "マッチ度": {"高い順": "DESC", "低い順": "ASC"}
}
selected_sort_order_display = st.sidebar.selectbox(
    "ソート順", 
    options=list(sort_order_options[selected_sort_by_display].keys()), 
    key="sort_order"
)

# 選択された表示名から、実際のDBカラム名とソート順を取得
sort_column = sort_by_options[selected_sort_by_display]
sort_direction = sort_order_options[selected_sort_by_display][selected_sort_order_display]
# ▲▲▲ 変更点 1 ここまで ▲▲▲


st.header("最新マッチング結果一覧")

# --- DBからフィルタリングされた結果を取得 ---
conn = get_db_connection()
query = '''
    SELECT 
        r.id as res_id, 
        r.job_id, j.document as job_doc, j.project_name, j.is_hidden as job_is_hidden,
        r.engineer_id, e.document as eng_doc, e.name as engineer_name, e.is_hidden as engineer_is_hidden,
        r.score, r.created_at, r.is_hidden, r.grade, r.positive_points, r.concern_points,
        job_user.username as job_assignee,
        eng_user.username as engineer_assignee
    FROM matching_results r
    JOIN jobs j ON r.job_id = j.id
    JOIN engineers e ON r.engineer_id = e.id
    LEFT JOIN users job_user ON j.assigned_user_id = job_user.id
    LEFT JOIN users eng_user ON e.assigned_user_id = eng_user.id
'''
params = []
where_clauses = [] 
if min_score_filter > 0:
    where_clauses.append("r.score >= ?")
    params.append(min_score_filter)

if job_assignee_filter != "すべて":
    where_clauses.append("job_user.username = ?"); params.append(job_assignee_filter)
if engineer_assignee_filter != "すべて":
    where_clauses.append("eng_user.username = ?"); params.append(engineer_assignee_filter)

if selected_grades:
    placeholders = ','.join('?' for _ in selected_grades)
    where_clauses.append(f"r.grade IN ({placeholders})")
    params.extend(selected_grades)

if keyword_filter: 
    where_clauses.append("(j.document LIKE ? OR e.document LIKE ? OR j.project_name LIKE ? OR e.name LIKE ? OR job_user.username LIKE ? OR eng_user.username LIKE ?)")
    params.extend([f'%{keyword_filter}%']*6)

if not show_hidden_filter:
    where_clauses.append("((r.is_hidden = 0 OR r.is_hidden IS NULL) AND j.is_hidden = 0 AND e.is_hidden = 0)")

if where_clauses: query += " WHERE " + " AND ".join(where_clauses)

# ▼▼▼ 変更点 2: ORDER BY 句を動的に生成 ▼▼▼
order_by_clause = ""
if sort_column == "grade":
    # AI評価 (S, A, B, C, D, E) のカスタムソート順
    order_by_clause = f"""
        ORDER BY
            CASE r.grade
                WHEN 'S' THEN 1
                WHEN 'A' THEN 2
                WHEN 'B' THEN 3
                WHEN 'C' THEN 4
                WHEN 'D' THEN 5
                WHEN 'E' THEN 6
                ELSE 7 -- NULLやその他の評価は最後に
            END {sort_direction},
            r.created_at DESC -- 評価が同じ場合はマッチ日でソート
    """
elif sort_column == "score":
    order_by_clause = f"ORDER BY r.score {sort_direction}, r.created_at DESC"
else: # created_at (マッチ日) の場合
    order_by_clause = f"ORDER BY r.created_at {sort_direction}, r.score DESC" # マッチ日が同じ場合はスコアでソート

query += order_by_clause
# ▲▲▲ 変更点 2 ここまで ▲▲▲

results = conn.execute(query, tuple(params)).fetchall()
conn.close()

# --- 結果の表示 ---
if not results:
    st.info("フィルタリング条件に合致するマッチング結果はありませんでした。")
else:
    results_to_display = []
    for res in results:
        job_doc = res['job_doc'] if res['job_doc'] else ""
        eng_doc = res['eng_doc'] if res['eng_doc'] else ""
        if filter_nationality and ("外国籍不可" in job_doc or "日本人" in job_doc):
            if "国籍: 日本" not in eng_doc:
                continue
        results_to_display.append(res)
    
    if not results_to_display:
        st.warning("AIが提案したマッチングはありましたが、ルールフィルターによってすべて除外されました。")
    else:
        total_items = len(results_to_display)
        total_pages = (total_items + st.session_state.items_per_page - 1) // st.session_state.items_per_page

        st.write(f"表示中のマッチング結果: {total_items}件")

        # ページネーションコントロール
        if total_items > 0:
            st.markdown("---")
            pagination_cols = st.columns([1, 2, 1])
            with pagination_cols[0]:
                if st.button("前のページ", key="prev_page_btn"):
                    if st.session_state.current_page > 1:
                        st.session_state.current_page -= 1
                        st.rerun()
            with pagination_cols[1]:
                st.markdown(f"<p style='text-align: center; font-weight: bold;'>ページ {st.session_state.current_page} / {total_pages}</p>", unsafe_allow_html=True)
            with pagination_cols[2]:
                if st.button("次のページ", key="next_page_btn"):
                    if st.session_state.current_page < total_pages:
                        st.session_state.current_page += 1
                        st.rerun()
            st.markdown("---")

        start_index = (st.session_state.current_page - 1) * st.session_state.items_per_page
        end_index = start_index + st.session_state.items_per_page
        paginated_results = results_to_display[start_index:end_index]

        for res in paginated_results:
            score = float(res['score'])
            is_match_hidden = res['is_hidden'] == 1
            is_job_hidden = res['job_is_hidden'] == 1
            is_engineer_hidden = res['engineer_is_hidden'] == 1
            is_any_part_hidden = is_match_hidden or is_job_hidden or is_engineer_hidden

            with st.container(border=True):
                header_col1, header_col2, header_col3 = st.columns([8, 3, 1])
                with header_col1: st.caption(f"マッチング日時: {res['created_at']}")
                with header_col2:
                    if is_any_part_hidden:
                        st.markdown('<p style="text-align: right; opacity: 0.7;">(非表示を含む)</p>', unsafe_allow_html=True)

                col1, col2, col3 = st.columns([5, 2, 5])
                
                with col1: # 案件情報
                    project_name = res['project_name'] if res['project_name'] else f"案件(ID: {res['job_id']})"
                    if is_job_hidden:
                        project_name += " <span style='color: #888; font-size: 0.8em; vertical-align: middle;'>(非表示)</span>"
                    st.markdown(f"##### 💼 {project_name}", unsafe_allow_html=True)
                    
                    if res['job_assignee']: st.caption(f"**担当:** {res['job_assignee']}")
                    job_doc = res['job_doc'] if res['job_doc'] else ""
                    display_doc = job_doc.split('\n---\n', 1)[-1]
                    st.caption(display_doc.replace('\n', ' ').replace('\r', '')[:150] + "...")
                    
                with col2: # マッチ度とAI評価
                    st.markdown(get_evaluation_html(res['grade']), unsafe_allow_html=True)
                    
                    if st.button("詳細を見る", key=f"detail_btn_{res['res_id']}", type="primary", use_container_width=True):
                        st.session_state['selected_match_id'] = res['res_id']
                        st.switch_page("pages/7_マッチング詳細.py")

                with col3: # 技術者情報
                    engineer_name = res['engineer_name'] if res['engineer_name'] else f"技術者(ID: {res['engineer_id']})"
                    if is_engineer_hidden:
                        engineer_name += " <span style='color: #888; font-size: 0.8em; vertical-align: middle;'>(非表示)</span>"
                    st.markdown(f"##### 👤 {engineer_name}", unsafe_allow_html=True)

                    if res['engineer_assignee']: st.caption(f"**担当:** {res['engineer_assignee']}")
                    eng_doc = res['eng_doc'] if eng['eng_doc'] else ""
                    display_doc = eng_doc.split('\n---\n', 1)[-1]
                    st.caption(display_doc.replace('\n', ' ').replace('\r', '')[:150] + "...")
            st.empty()
