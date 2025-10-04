import streamlit as st
import backend as be
import json
import html

st.set_page_config(page_title="マッチング詳細", layout="wide")

st.image("img/UniversalAI_logo.png", width=240)
st.divider()

# --- データ取得 ---
selected_match_id = st.session_state.get('selected_match_id', None)
if selected_match_id is None:
    st.error("マッチングが選択されていません。ダッシュボードから詳細を見たいマッチングを選択してください。")
    if st.button("ダッシュボードに戻る"): st.switch_page("1_ダッシュボード.py")
    st.stop()

conn = be.get_db_connection()
match_data = conn.execute("SELECT job_id, engineer_id, score FROM matching_results WHERE id = ?", (selected_match_id,)).fetchone()
if not match_data:
    st.error("指定されたマッチング情報が見つかりませんでした。")
    conn.close(); st.stop()

# 【変更点 1】担当者名を取得するために、JOINを使ったクエリに変更
job_query = """
SELECT j.*, u.username as assignee_name
FROM jobs j
LEFT JOIN users u ON j.assigned_user_id = u.id
WHERE j.id = ?
"""
job_data = conn.execute(job_query, (match_data['job_id'],)).fetchone()

engineer_query = """
SELECT e.*, u.username as assignee_name
FROM engineers e
LEFT JOIN users u ON e.assigned_user_id = u.id
WHERE e.id = ?
"""
engineer_data = conn.execute(engineer_query, (match_data['engineer_id'],)).fetchone()
conn.close()

if not job_data or not engineer_data:
    st.error("案件または技術者の情報が見つかりませんでした。")
    st.stop()

# --- ヘルパー関数 ---
def get_source_text(source_json_str):
    # ... (この関数は変更なし)
    if not source_json_str: return "元のメール情報はありません。"
    try:
        source_data = json.loads(source_json_str)
        email_body = source_data.get("body", "（メール本文がありません）")
        attachments = source_data.get("attachments", [])
        full_text = "--- メール本文 ---\n" + email_body
        if attachments:
            full_text += "\n\n--- 添付ファイル ---\n"
            for att in attachments: full_text += f"📄 {att.get('filename', '名称不明')}\n"
        return full_text
    except json.JSONDecodeError: return "エラー: 元のデータの解析に失敗しました。"

# ==================================================================
# ▼▼▼【ここからが新しい画面レイアウトです】▼▼▼
# ==================================================================

# --- 2. AI要約比較セクション ---
st.header("🤖 AIによる案件、技術者の要約")
col_job, col_eng = st.columns(2)

# 【変更点 2】display_summary関数に担当者名(assignee)を表示する機能を追加
def display_summary(title, document_text, assignee=None):
    """AI要約情報を表示するための共通関数"""
    doc_parts = document_text.split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", document_text)
    
    with st.container(border=True, height=350):
        st.subheader(title)
        # 担当者がいれば表示
        if assignee:
            st.caption(f"**担当:** {assignee}")
        # メタ情報はキャプションとして表示
        if meta_info:
            st.caption(meta_info.replace("][", " | ").strip("[]"))
        st.markdown(main_doc)

with col_job:
    project_name = job_data['project_name'] or f"案件 (ID: {job_data['id']})"
    # 【変更点 3】取得した案件担当者名を関数に渡す
    display_summary(f"💼 {project_name}", job_data['document'], job_data['assignee_name'])

with col_eng:
    engineer_name = engineer_data['name'] or f"技術者 (ID: {engineer_data['id']})"
    # 【変更点 4】取得した技術者担当者名を関数に渡す
    display_summary(f"👤 {engineer_name}", engineer_data['document'], engineer_data['assignee_name'])

st.divider()

# --- 1. 最重要サマリーセクション ---
st.header("📊 AIマッチング評価")
# ... (このセクションは変更なし) ...
summary_data = be.get_match_summary_with_llm(job_data['document'], engineer_data['document'])
with st.container(border=True):
    col1, col2, col3 = st.columns([1.5, 3, 3])
    with col1:
        st.metric("マッチ度", f"{float(match_data['score']):.1f}%")
    with col2:
        st.markdown("###### ✅ ポジティブな点")
        if summary_data and summary_data.get('positive_points'):
            for point in summary_data['positive_points']:
                st.markdown(f"- {point}")
        else:
            st.caption("特筆すべき点はありません。")
    with col3:
        st.markdown("###### ⚠️ 懸念点・確認事項")
        if summary_data and summary_data.get('concern_points'):
            for point in summary_data['concern_points']:
                st.markdown(f"- {point}")
        else:
            st.caption("特に懸念はありません。")

# --- 3. 元情報（タブ）セクション ---
st.header("📄 元の情報ソース")
# ... (このセクションは変更なし) ...
tab1, tab2 = st.tabs(["案件の元情報", "技術者の元情報"])
with tab1:
    source_text_job = get_source_text(job_data['source_data_json'])
    st.text_area("案件ソース", value=source_text_job, height=400, disabled=True, label_visibility="collapsed")
with tab2:
    source_text_eng = get_source_text(engineer_data['source_data_json'])
    st.text_area("技術者ソース", value=source_text_eng, height=400, disabled=True, label_visibility="collapsed")

st.divider()
if st.button("ダッシュボードに戻る"):
    if 'selected_match_id' in st.session_state: del st.session_state['selected_match_id']
    st.switch_page("1_ダッシュボード.py")