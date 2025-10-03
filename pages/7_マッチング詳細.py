import streamlit as st
import backend as be
import json
import html

st.set_page_config(page_title="マッチング詳細", layout="wide")

# ▼▼▼【ここからが最後の修正箇所です】▼▼▼
# --- テーマに応じて色が変わる、新しいカスタムCSS ---
custom_css = """
<style>
    /* メインのスコア表示 */
    .main-score { text-align: center; }
    .main-score .stMetric {
        background-color: var(--secondary-background-color); /* テーマの第二背景色 */
        border: 1px solid var(--gray-80); /* テーマの灰色 */
        padding: 20px;
        border-radius: 10px;
    }
    /* AI要約のテキストボックス */
    .summary-box {
        background-color: var(--secondary-background-color); /* テーマの第二背景色 */
        border: 1px solid var(--gray-80); /* テーマの灰色 */
        color: var(--text-color); /* テーマの文字色 */
        padding: 15px; border-radius: 5px;
        height: 250px; overflow-y: auto;
        white-space: pre-wrap; word-wrap: break-word;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 0.9em;
    }
    /* メタ情報タグ */
    .meta-tag {
        display: inline-block;
        background-color: var(--secondary-background-color);
        color: var(--primary-color); /* テーマの主要色（青など） */
        border: 1px solid var(--primary-color);
        padding: 2px 8px; border-radius: 15px; margin-right: 10px;
        font-size: 0.85em; margin-bottom: 10px;
    }
    /* 元のメール情報のテキストエリア */
    textarea[aria-label="source_text_area"] {
        font-family: monospace; font-size: 0.85em;
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)
# ▲▲▲【CSSの修正はここまで】▲▲▲

st.title("🤝 マッチング詳細")
st.divider()

# --- ID取得 & データ取得 ---
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
job_data = conn.execute("SELECT * FROM jobs WHERE id = ?", (match_data['job_id'],)).fetchone()
engineer_data = conn.execute("SELECT * FROM engineers WHERE id = ?", (match_data['engineer_id'],)).fetchone()
conn.close()
if not job_data or not engineer_data:
    st.error("案件または技術者の情報が見つかりませんでした。")
    st.stop()

# --- 表示用のヘルパー関数 ---
def get_source_text(source_json_str):
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

# --- 画面表示 ---
header_col1, header_col2 = st.columns([8, 2])
with header_col1: st.header("🤖 AIによる要約")
with header_col2: st.metric("マッチ度", f"{float(match_data['score']):.1f}%")

col_job_summary, col_eng_summary = st.columns(2)
with col_job_summary:
    project_name = job_data['project_name'] if job_data['project_name'] else f"案件 (ID: {job_data['id']})"
    st.markdown(f"###### 💼 {project_name}")
    doc_parts = job_data['document'].split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", job_data['document'])
    tags_html = "".join([f'<span class="meta-tag">{html.escape(tag.strip("[]"))}</span>' for tag in meta_info.strip().replace("][", "] [").split(" ") if tag])
    st.markdown(tags_html, unsafe_allow_html=True)
    st.markdown(f'<div class="summary-box">{html.escape(main_doc)}</div>', unsafe_allow_html=True)

with col_eng_summary:
    engineer_name = engineer_data['name'] if engineer_data['name'] else f"技術者 (ID: {engineer_data['id']})"
    st.markdown(f"###### 👤 {engineer_name}")
    doc_parts = engineer_data['document'].split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", engineer_data['document'])
    tags_html = "".join([f'<span class="meta-tag">{html.escape(tag.strip("[]"))}</span>' for tag in meta_info.strip().replace("][", "] [").split(" ") if tag])
    st.markdown(tags_html, unsafe_allow_html=True)
    st.markdown(f'<div class="summary-box">{html.escape(main_doc)}</div>', unsafe_allow_html=True)
st.divider()

st.header("🔍 AIによるマッチング根拠")
summary_data = be.get_match_summary_with_llm(job_data['document'], engineer_data['document'])
if summary_data:
    with st.container(border=True):
        st.info(f"**総合評価:** {summary_data.get('summary', 'N/A')}")
        summary_col1, summary_col2 = st.columns(2)
        with summary_col1:
            st.markdown("###### ✅ ポジティブな点")
            for point in summary_data.get('positive_points', ["特になし"]): st.markdown(f"- {point}")
        with summary_col2:
            st.markdown("###### ⚠️ 懸念点")
            concern_points = summary_data.get('concern_points', [])
            if concern_points:
                for point in concern_points: st.markdown(f"- {point}")
            else: st.caption("特に懸念点は見つかりませんでした。")
else: st.warning("AIによるマッチング根拠の生成に失敗しました。")
st.divider()

st.header("📄 元のメール情報詳細")
col_job_source, col_eng_source = st.columns(2)
with col_job_source:
    st.subheader(f"案件: {job_data['project_name']}")
    source_text_job = get_source_text(job_data['source_data_json'])
    st.text_area("source_text_area", value=source_text_job, height=400, disabled=True, key="job_source")
with col_eng_source:
    st.subheader(f"技術者: {engineer_data['name']}")
    source_text_eng = get_source_text(engineer_data['source_data_json'])
    st.text_area("source_text_area", value=source_text_eng, height=400, disabled=True, key="eng_source")

st.divider()
if st.button("ダッシュボードに戻る"):
    if 'selected_match_id' in st.session_state: del st.session_state['selected_match_id']
    st.switch_page("1_ダッシュボード.py")
