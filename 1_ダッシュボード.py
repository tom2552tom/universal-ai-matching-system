import streamlit as st
from datetime import datetime, timedelta
from backend import (
    init_database, load_embedding_model, get_db_connection,
    hide_match, load_app_config, get_all_users
)
import os
import ui_components as ui  # ← 1. 新しいファイルをインポート


# --- CSSとJSを初回のみ読み込むためのヘルパー関数 ---
@st.cache_data
def load_file_content(file_path):
    """外部ファイルを読み込んでその内容を返す（キャッシュ付き）"""
    try:
        # プロジェクトルートからの相対パスでファイルを検索
        project_root = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(project_root, file_path)
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        st.warning(f"Warning: ファイルが見つかりません - {file_path}")
        return ""

def apply_global_styles():
    """アプリケーション全体に適用するスタイルとスクリプトを注入する"""
    # JSでテーマを検知し、CSS変数を設定
    js_code = load_file_content('js/theme_detector.js')
    
    # CSSを外部ファイルから読み込み
    css_code = load_file_content('styles/main.css')

    if css_code:
        st.markdown(f"<style>{css_code}</style>", unsafe_allow_html=True)
    
    if js_code:
        st.components.v1.html(f"<script>{js_code}</script>", height=0)

# --- アプリケーションの初期化とスタイル適用 ---
config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | ダッシュボード", layout="wide")
ui.apply_global_styles()

if not ui.check_password():
    st.stop() # 認証が通らない場合、ここで処理を停止

    
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
#init_database()
#load_embedding_model()

config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | ダッシュボード", layout="wide")

# --- ページング設定の初期化 ---
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'items_per_page' not in st.session_state:
    st.session_state.items_per_page = 20 

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

#st.info("バージョン1.0.5がリリースされました。リリースノートをご確認ください。")

st.header("最新マッチング結果一覧")

# --- DBからフィルタリングされた結果を取得 ---
conn = get_db_connection()

# ▼▼▼【SQLクエリの確認・修正】▼▼▼
# COALESCE を使って、担当者がNULLの場合に「未担当」を返すようにする
query = '''
    SELECT 
        r.id as res_id, r.job_id, j.document as job_doc, j.project_name, j.is_hidden as job_is_hidden,
        r.engineer_id, e.document as eng_doc, e.name as engineer_name, e.is_hidden as engineer_is_hidden,
        r.score, r.created_at, r.is_hidden as match_is_hidden, r.grade, r.status,
        COALESCE(job_user.username, '未担当') as job_assignee,
        COALESCE(eng_user.username, '未担当') as engineer_assignee,
        CASE 
            WHEN r.feedback_status IS NOT NULL AND r.feedback_status != '' THEN true
            ELSE false
        END AS has_feedback
    FROM matching_results r
    JOIN jobs j ON r.job_id = j.id
    JOIN engineers e ON r.engineer_id = e.id
    LEFT JOIN users job_user ON j.assigned_user_id = job_user.id
    LEFT JOIN users eng_user ON e.assigned_user_id = eng_user.id
'''
# ▲▲▲【SQLクエリここまで】▲▲▲


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

if not show_hidden_filter:
    where_clauses.append("((r.is_hidden = 0 OR r.is_hidden IS NULL) AND j.is_hidden = 0 AND e.is_hidden = 0)")

if where_clauses:
    query += " WHERE " + " AND ".join(where_clauses)

query += """ ORDER BY
            CASE r.grade
                WHEN 'S' THEN 1
                WHEN 'A' THEN 2
                WHEN 'B' THEN 3
                WHEN 'C' THEN 4
                WHEN 'D' THEN 5
                ELSE 6
            END ASC,
            r.created_at DESC
"""

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

        # ▼▼▼【ここからが修正箇所です】▼▼▼

        # --- "Load More"方式のためのセッションステート初期化 ---
        ITEMS_PER_LOAD = 10 # 一回に読み込む件数
        if 'items_to_show' not in st.session_state:
            st.session_state.items_to_show = ITEMS_PER_LOAD

        total_items = len(results_to_display)

        # --- ヘッダー表示 ---
        # 表示件数セレクターは不要になるため削除（またはコメントアウト）
        st.write(f"**マッチング結果: {total_items}件**")

        # --- 表示するデータのスライス ---
        # 現在表示すべき件数までのデータを取得
        items_to_display_now = results_to_display[:st.session_state.items_to_show]

        # --- マッチング結果の表示ループ ---
        for res in items_to_display_now:
            with st.container(border=True):
                is_archived = res['match_is_hidden'] or res['job_is_hidden'] or res['engineer_is_hidden']
                
                if is_archived:
                    st.warning("このマッチングは、関連する案件・技術者、またはマッチング自体が非表示（アーカイブ済み）です。")
                
                header_col1, header_col2 = st.columns([5, 2])
                with header_col1:
                    created_at_dt = res['created_at']
                    if created_at_dt:
                        st.caption(f"マッチング日時: {created_at_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                with header_col2:
                    status_html = get_status_badge(res['status'])
                    st.markdown(f"<div style='text-align: right;'>{status_html}</div>", unsafe_allow_html=True)

                col1, col2, col3 = st.columns([5, 2, 5])
                
                with col1:
                    project_name = res['project_name'] or f"案件(ID: {res['job_id']})"
                    project_button_label = f"💼 {project_name}{' (非表示)' if res['job_is_hidden'] else ''}"
                    
                    # st.button を使い、クリックされたら session_state にIDを保存してページを切り替える
                    if st.button(project_button_label, key=f"job_link_{res['res_id']}", use_container_width=True, type="secondary"):
                        st.session_state['selected_job_id'] = res['job_id']
                        st.switch_page("pages/6_案件詳細.py")
                        
                    st.caption(f"ID: {res['job_id']} | 担当: {res['job_assignee']}")
                    job_doc_summary = (res['job_doc'].split('\n---\n', 1)[-1]).replace('\n', ' ').replace('\r', '')[:150]
                    st.caption(f"{job_doc_summary}...")
                    

                    
                with col2:

                     # ▼▼▼【この部分を修正】▼▼▼

                    # フィードバックアイコンを準備
                    feedback_icon = "💬" if res.get('has_feedback') else ""
                    
                    # 評価(Grade)のHTMLを取得
                    grade_html = get_evaluation_html(res['grade'])
                    
                    # HTMLを結合して表示
                    st.markdown(f"{grade_html}<div style='text-align:center; font-size:1.2em;'>{feedback_icon}</div>", unsafe_allow_html=True)
                    
                    # ▲▲▲【修正ここまで】▲▲▲

                    #st.markdown(get_evaluation_html(res['grade']), unsafe_allow_html=True)

                    
                    if st.button("詳細を見る", key=f"dashboard_detail_btn_{res['res_id']}", use_container_width=True):
                        st.session_state['selected_match_id'] = res['res_id']
                        st.switch_page("pages/7_マッチング詳細.py")

                with col3:
                    engineer_name = res['engineer_name'] or f"技術者(ID: {res['engineer_id']})"
                    engineer_button_label = f"👤 {engineer_name}{' (非表示)' if res['engineer_is_hidden'] else ''}"

                    # こちらも同様に st.button に変更
                    if st.button(engineer_button_label, key=f"eng_link_{res['res_id']}", use_container_width=True, type="secondary"):
                        st.session_state['selected_engineer_id'] = res['engineer_id']
                        st.switch_page("pages/5_技術者詳細.py")

                    st.caption(f"ID: {res['engineer_id']} | 担当: {res['engineer_assignee']}")
                    eng_doc_summary = (res['eng_doc'].split('\n---\n', 1)[-1]).replace('\n', ' ').replace('\r', '')[:150]
                    st.caption(f"{eng_doc_summary}...")




        
        # まだ表示していないアイテムが残っている場合のみボタンを表示
        if st.session_state.items_to_show < total_items:
            # 画面中央にボタンを配置するためのカラム
            _, col_btn, _ = st.columns([2, 1, 2])
            with col_btn:
                if st.button("もっと見る", use_container_width=True, type="primary"):
                    # 表示件数を増やす
                    st.session_state.items_to_show += ITEMS_PER_LOAD
                    st.rerun()
        else:
            st.success("すべてのマッチング結果を表示しました。")

        # ▲▲▲【修正ここまで】▲▲▲

        
ui.display_footer()
