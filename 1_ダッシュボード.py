import streamlit as st
from datetime import datetime, timedelta
from backend import (
    init_database, load_embedding_model, get_db_connection,
    hide_match, load_app_config
)

config = load_app_config()
APP_TITLE = config.get("app", {}).get("title", "AI Matching System")
st.set_page_config(page_title=f"{APP_TITLE} | ダッシュボード", layout="wide")

init_database(); load_embedding_model()

# --- タイトル部分を画像に差し替え ---
# st.title(APP_TITLE) # 元のテキストタイトルをコメントアウト
st.image("img/UniversalAI_logo.png",width=240) # ロゴ画像を表示
st.divider()

# --- サイドバー ---
st.sidebar.header("フィルター")
min_score_filter = st.sidebar.slider("最小マッチ度 (%)", 0, 100, 0)
today = datetime.now().date()
default_start_date = today - timedelta(days=30)
start_date_filter = st.sidebar.date_input("開始日", value=default_start_date)
end_date_filter = st.sidebar.date_input("終了日", value=today)
keyword_filter = st.sidebar.text_input("キーワード検索")

st.sidebar.divider()
st.sidebar.header("ルールフィルター")
filter_nationality = st.sidebar.checkbox("「外国籍不可」の案件を除外する", value=True)
show_hidden_filter = st.sidebar.checkbox("非表示も表示する", value=False)

st.header("最新マッチング結果一覧")

# --- DBからフィルタリングされた結果を取得 ---
conn = get_db_connection()
query = '''
    SELECT 
        r.id as res_id, r.job_id, j.document as job_doc, j.project_name, 
        r.engineer_id, e.document as eng_doc, e.name as engineer_name,
        r.score, r.created_at, r.is_hidden
    FROM matching_results r
    JOIN jobs j ON r.job_id = j.id
    JOIN engineers e ON r.engineer_id = e.id
    WHERE r.score >= ?
'''
params = [min_score_filter]
if start_date_filter: query += " AND date(r.created_at) >= ?"; params.append(start_date_filter)
if end_date_filter: query += " AND date(r.created_at) <= ?"; params.append(end_date_filter)
if keyword_filter: query += " AND (j.document LIKE ? OR e.document LIKE ? OR j.project_name LIKE ? OR e.name LIKE ?)"; params.extend([f'%{keyword_filter}%']*4)
if not show_hidden_filter: query += " AND (r.is_hidden = 0 OR r.is_hidden IS NULL)"
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
        is_hidden = res['is_hidden'] == 1

        with st.container(border=True):
            header_col1, header_col2, header_col3 = st.columns([8, 3, 1])
            with header_col1: st.caption(f"マッチング日時: {res['created_at']}")
            with header_col2:
                if is_hidden: st.markdown('<p style="text-align: right; opacity: 0.7;">非表示</p>', unsafe_allow_html=True)
                elif score > 75: st.markdown('<p style="text-align: right; color: #28a745; font-weight: bold;">高マッチ</p>', unsafe_allow_html=True)
            with header_col3:
                if not is_hidden and st.button("❌", key=f"hide_btn_{res['res_id']}", help="このマッチングを非表示にします"):
                    hide_match(res['res_id']); st.rerun()

            col1, col2, col3 = st.columns([5, 2, 5])
            
            with col1:
                project_name = res['project_name'] if res['project_name'] else f"案件(ID: {res['job_id']})"
                st.markdown(f"##### 💼 {project_name}")
                job_doc = res['job_doc'] if res['job_doc'] else ""
                display_doc = job_doc.split('\n---\n', 1)[-1]
                st.caption(display_doc.replace('\n', ' ').replace('\r', '')[:150] + "...")
                # ▼▼▼【ここが修正箇所です】▼▼▼
                # ボタンのラベルを変更し、クリック時の動作を画面遷移に変更
                if st.button("詳細を見る", key=f"detail_btn_{res['res_id']}", type="primary"):
                    st.session_state['selected_match_id'] = res['res_id']
                    st.switch_page("pages/7_マッチング詳細.py")

            with col2:
                st.metric(label="マッチ度", value=f"{score:.1f}%")
            
            with col3:
                engineer_name = res['engineer_name'] if res['engineer_name'] else f"技術者(ID: {res['engineer_id']})"
                st.markdown(f"##### 👤 {engineer_name}")
                eng_doc = res['eng_doc'] if res['eng_doc'] else ""
                display_doc = eng_doc.split('\n---\n', 1)[-1]
                st.caption(display_doc.replace('\n', ' ').replace('\r', '')[:150] + "...")
                #if st.button("技術者詳細へ", key=f"detail_link_{res['res_id']}"):
                #    st.session_state['selected_engineer_id'] = res['engineer_id']
                #    st.switch_page("pages/5_技術者詳細.py")

            # ▼▼▼【ここが修正箇所です】▼▼▼
            # ダッシュボード上でのAI評価表示ロジックは不要になったため削除
            # if show_ai_eval: ... のブロック全体を削除
        st.empty()
