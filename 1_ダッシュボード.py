import streamlit as st
from datetime import datetime, timedelta
from backend import (
    init_database, load_embedding_model, get_db_connection,
    hide_match, load_app_config, get_all_users
)

# ▼▼▼【ここからが修正箇所です】▼▼▼

# --- アプリケーションの初期化 ---
# データベースとテーブルが確実に存在するように、全ての処理の最初に呼び出す
init_database()
load_embedding_model() # 埋め込みモデルもここで読み込む

# --- ヘルパー関数と設定の読み込み ---
def get_evaluation_html(grade, font_size='2.5em'):
    # ... (この関数は変更なし) ...
    if not grade: return ""
    color_map = {'A': '#28a745', 'B': '#17a2b8', 'C': '#ffc107', 'D': '#fd7e14', 'E': '#dc3545'}
    color = color_map.get(grade.upper(), '#6c757d') 
    style = f"color: {color}; font-size: {font_size}; font-weight: bold; text-align: center; line-height: 1; padding-top: 10px;"
    html_code = f"<div style='{style}'>{grade.upper()}</div><div style='text-align: center; font-size: 0.8em; color: #888;'>判定</div>"
    return html_code

config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | ダッシュボード", layout="wide")


st.image("img/UniversalAI_logo.png", width=240)
st.divider()


# --- サイドバー ---
st.sidebar.header("フィルター")

# 担当者フィルター
# init_database() が実行された後なので、安全に get_all_users() を呼び出せる
all_users = get_all_users()
user_names = [user['username'] for user in all_users]
assignee_options = ["すべて"] + user_names 
# ▲▲▲【ここまでが修正箇所です】▲▲▲



job_assignee_filter = st.sidebar.selectbox(
    "案件担当者", options=assignee_options, key="job_assignee_filter"
)
engineer_assignee_filter = st.sidebar.selectbox(
    "技術者担当者", options=assignee_options, key="engineer_assignee_filter"
)
st.sidebar.divider()

# ▼▼▼ 変更点 2: AI評価フィルターをサイドバーに追加 ▼▼▼
grade_options = ['S','A', 'B', 'C', 'D', 'E']
selected_grades = st.sidebar.multiselect(
    "AI評価",
    options=grade_options,
    placeholder="評価を選択して絞り込み"
)
st.sidebar.divider()
# ▲▲▲ 変更点 2 ここまで ▲▲▲

# その他のフィルター
min_score_filter = st.sidebar.slider("最小マッチ度 (%)", 0, 100, 0)
today = datetime.now().date()
default_start_date = today - timedelta(days=30)
#start_date_filter = st.sidebar.date_input("開始日", value=default_start_date)
#end_date_filter = st.sidebar.date_input("終了日", value=today)
keyword_filter = st.sidebar.text_input("キーワード検索 (担当者名も可)")

st.sidebar.divider()
st.sidebar.header("ルールフィルター")
filter_nationality = st.sidebar.checkbox("「外国籍不可」の案件を除外する", value=False)
show_hidden_filter = st.sidebar.checkbox("非表示も表示する", value=False)

st.header("最新マッチング結果一覧")

# --- DBからフィルタリングされた結果を取得 ---
conn = get_db_connection()
# ▼▼▼ 変更点 3: クエリに 'r.grade' を追加 ▼▼▼
query = '''
    SELECT 
        r.id as res_id, 
        r.job_id, j.document as job_doc, j.project_name, j.is_hidden as job_is_hidden,
        r.engineer_id, e.document as eng_doc, e.name as engineer_name, e.is_hidden as engineer_is_hidden,
        r.score, r.created_at, r.is_hidden, r.grade,
        job_user.username as job_assignee,
        eng_user.username as engineer_assignee
    FROM matching_results r
    JOIN jobs j ON r.job_id = j.id
    JOIN engineers e ON r.engineer_id = e.id
    LEFT JOIN users job_user ON j.assigned_user_id = job_user.id
    LEFT JOIN users eng_user ON e.assigned_user_id = eng_user.id
    
'''
# ▲▲▲ 変更点 3 ここまで ▲▲▲
params = []
where_clauses = ["r.score >= ?"]; params.append(min_score_filter)

# 担当者フィルター
if job_assignee_filter != "すべて":
    where_clauses.append("job_user.username = ?"); params.append(job_assignee_filter)
if engineer_assignee_filter != "すべて":
    where_clauses.append("eng_user.username = ?"); params.append(engineer_assignee_filter)

# ▼▼▼ 変更点 4: AI評価フィルターの条件を追加 ▼▼▼
if selected_grades:
    # プレースホルダを動的に生成
    placeholders = ','.join('?' for _ in selected_grades)
    where_clauses.append(f"r.grade IN ({placeholders})")
    params.extend(selected_grades)
# ▲▲▲ 変更点 4 ここまで ▲▲▲

# その他のフィルター
#if start_date_filter: where_clauses.append("date(r.created_at) >= ?"); params.append(start_date_filter)
#if end_date_filter: where_clauses.append("date(r.created_at) <= ?"); params.append(end_date_filter)
if keyword_filter: 
    where_clauses.append("(j.document LIKE ? OR e.document LIKE ? OR j.project_name LIKE ? OR e.name LIKE ? OR job_user.username LIKE ? OR eng_user.username LIKE ?)")
    params.extend([f'%{keyword_filter}%']*6)

if not show_hidden_filter:
    where_clauses.append("((r.is_hidden = 0 OR r.is_hidden IS NULL) AND j.is_hidden = 0 AND e.is_hidden = 0)")

if where_clauses: query += " WHERE " + " AND ".join(where_clauses)

query += " ORDER BY r.created_at DESC, r.score DESC LIMIT 100"

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
        st.write(f"表示中のマッチング結果: {len(results_to_display)}件")

    for res in results_to_display:
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

            # ▼▼▼ 変更点 5: レイアウトと表示内容の変更 ▼▼▼
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
                # AI評価をヘルパー関数で表示
                st.markdown(get_evaluation_html(res['grade']), unsafe_allow_html=True)
                # マッチ度はラベルを非表示にして評価の下に配置
                #st.metric(label="マッチ度", value=f"{score:.1f}%", label_visibility="collapsed")
                
                # 詳細ボタンをこの列に移動
                if st.button("詳細を見る", key=f"detail_btn_{res['res_id']}", type="primary", use_container_width=True):
                    st.session_state['selected_match_id'] = res['res_id']
                    st.switch_page("pages/7_マッチング詳細.py")

            with col3: # 技術者情報
                engineer_name = res['engineer_name'] if res['engineer_name'] else f"技術者(ID: {res['engineer_id']})"
                if is_engineer_hidden:
                    engineer_name += " <span style='color: #888; font-size: 0.8em; vertical-align: middle;'>(非表示)</span>"
                st.markdown(f"##### 👤 {engineer_name}", unsafe_allow_html=True)

                if res['engineer_assignee']: st.caption(f"**担当:** {res['engineer_assignee']}")
                eng_doc = res['eng_doc'] if res['eng_doc'] else ""
                display_doc = eng_doc.split('\n---\n', 1)[-1]
                st.caption(display_doc.replace('\n', ' ').replace('\r', '')[:150] + "...")
            # ▲▲▲ 変更点 5 ここまで ▲▲▲
        st.empty()
