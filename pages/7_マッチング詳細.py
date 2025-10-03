import streamlit as st
import backend as be
import json
import html

st.set_page_config(page_title="マッチング詳細", layout="wide")

# ▼▼▼【修正箇所】デザイン調整用のカスタムCSS ▼▼▼
custom_css = """
<style>
    /* メインのスコア表示 */
    .main-score {
        text-align: center;
    }
    .main-score .stMetric {
        background-color: #262730;
        border: 1px solid #333;
        padding: 20px;
        border-radius: 10px;
    }
    /* AI要約と元の情報のテキストボックス */
    .info-box {
        border: 1px solid #333; 
        padding: 15px; 
        border-radius: 5px; 
        background-color: #1a1a1a;
        height: 300px; /* 高さを少し低めに調整 */
        overflow-y: auto; 
        white-space: pre-wrap;
        word-wrap: break-word; 
        font-family: monospace; 
        font-size: 0.85em; /* フォントを少し小さめに */
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

st.title("🤝 マッチング詳細")
st.divider()

# --- ID取得 ---
selected_match_id = st.session_state.get('selected_match_id', None)
if selected_match_id is None:
    st.error("マッチングが選択されていません。ダッシュボードから詳細を見たいマッチングを選択してください。")
    if st.button("ダッシュボードに戻る"): st.switch_page("1_ダッシュボード.py")
    st.stop()

# --- DBから全情報を取得 ---
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
def display_source_block(source_json_str):
    """元のメール情報を整形して返す関数"""
    if not source_json_str:
        return "元のメール情報はありません。"
    try:
        source_data = json.loads(source_json_str)
        email_body = source_data.get("body", "（メール本文がありません）")
        attachments = source_data.get("attachments", [])
        
        full_text = "--- メール本文 ---\n" + email_body
        if attachments:
            full_text += "\n\n--- 添付ファイル ---\n"
            for att in attachments:
                full_text += f"📄 {att.get('filename', '名称不明')}\n"
        return full_text
    except json.JSONDecodeError:
        return "エラー: 元のデータの解析に失敗しました。"

# --- ▼▼▼【ここからが画面レイアウトの全面改修です】▼▼▼ ---

# --- 1. 概要（誰が、誰と、何点で） ---
st.header("概要")
col1, col2, col3 = st.columns([5, 2, 5])

with col1:
    project_name = job_data['project_name'] if job_data['project_name'] else f"案件 (ID: {job_data['id']})"
    st.subheader(f"💼 {project_name}")
    st.caption(f"ID: {job_data['id']}")

with col2:
    st.markdown('<div class="main-score">', unsafe_allow_html=True)
    st.metric("マッチ度", f"{float(match_data['score']):.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)

with col3:
    engineer_name = engineer_data['name'] if engineer_data['name'] else f"技術者 (ID: {engineer_data['id']})"
    st.subheader(f"👤 {engineer_name}")
    st.caption(f"ID: {engineer_data['id']}")

st.divider()

# --- 2. AIによるマッチング根拠 ---
st.header("🤖 AIによるマッチング根拠")
summary_data = be.get_match_summary_with_llm(job_data['document'], engineer_data['document'])
if summary_data:
    with st.container(border=True):
        st.info(f"**総合評価:** {summary_data.get('summary', 'N/A')}")
        summary_col1, summary_col2 = st.columns(2)
        with summary_col1:
            st.markdown("###### ✅ ポジティブな点")
            for point in summary_data.get('positive_points', ["特になし"]):
                st.markdown(f"- {point}")
        with summary_col2:
            st.markdown("###### ⚠️ 懸念点")
            concern_points = summary_data.get('concern_points', [])
            if concern_points:
                for point in concern_points:
                    st.markdown(f"- {point}")
            else:
                st.caption("特に懸念点は見つかりませんでした。")
else:
    st.warning("AIによるマッチング根拠の生成に失敗しました。")

st.divider()

# --- 3. 詳細情報（案件と技術者） ---
st.header("📄 詳細情報")
col_job, col_eng = st.columns(2)

with col_job:
    st.subheader("案件情報")
    with st.container(border=True):
        st.markdown("###### AIによる要約")
        st.markdown(f'<div class="info-box">{html.escape(job_data["document"])}</div>', unsafe_allow_html=True)
        st.markdown("###### 元のメール・添付ファイル")
        source_text_job = display_source_block(job_data['source_data_json'])
        st.markdown(f'<div class="info-box">{html.escape(source_text_job)}</div>', unsafe_allow_html=True)

with col_eng:
    st.subheader("技術者情報")
    with st.container(border=True):
        st.markdown("###### AIによる要約")
        st.markdown(f'<div class="info-box">{html.escape(engineer_data["document"])}</div>', unsafe_allow_html=True)
        st.markdown("###### 元のメール・添付ファイル")
        source_text_eng = display_source_block(engineer_data['source_data_json'])
        st.markdown(f'<div class="info-box">{html.escape(source_text_eng)}</div>', unsafe_allow_html=True)

# --- ▲▲▲【画面レイアウトの改修はここまで】▲▲▲ ---

st.divider()
if st.button("ダッシュボードに戻る"):
    if 'selected_match_id' in st.session_state: del st.session_state['selected_match_id']
    st.switch_page("1_ダッシュボード.py")
