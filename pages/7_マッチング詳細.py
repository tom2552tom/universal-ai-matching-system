import streamlit as st
import backend as be
import json
import html

st.set_page_config(page_title="マッチング詳細", layout="wide")



# --- データ取得 ---
selected_match_id = st.session_state.get('selected_match_id', None)
if selected_match_id is None:
    st.error("マッチングが選択されていません。ダッシュボードから詳細を見たいマッチングを選択してください。")
    if st.button("ダッシュボードに戻る"): st.switch_page("1_ダッシュボード.py")
    st.stop()

conn = be.get_db_connection()
match_data = conn.execute("SELECT * FROM matching_results WHERE id = ?", (selected_match_id,)).fetchone()
if not match_data:
    st.error("指定されたマッチング情報が見つかりませんでした。"); conn.close(); st.stop()

job_query = "SELECT j.*, u.username as assignee_name FROM jobs j LEFT JOIN users u ON j.assigned_user_id = u.id WHERE j.id = ?"
job_data = conn.execute(job_query, (match_data['job_id'],)).fetchone()
engineer_query = "SELECT e.*, u.username as assignee_name FROM engineers e LEFT JOIN users u ON e.assigned_user_id = u.id WHERE e.id = ?"
engineer_data = conn.execute(engineer_query, (match_data['engineer_id'],)).fetchone()
conn.close()

if not job_data or not engineer_data:
    st.error("案件または技術者の情報が見つかりませんでした。"); st.stop()

# --- ヘルパー関数 ---
def get_source_text(source_json_str):
    if not source_json_str: return "元のメール情報はありません。"
    try:
        data = json.loads(source_json_str)
        text = "--- メール本文 ---\n" + data.get("body", "（本文なし）")
        for att in data.get("attachments", []):
            text += f"\n\n--- 添付ファイル: {att.get('filename', '名称不明')} ---\n{att.get('content', '（内容なし）')}"
        return text
    except: return "エラー: 元のデータの解析に失敗しました。"

# ==================================================================
# ▼▼▼【ここからが新しい画面レイアウトです】▼▼▼
# ==================================================================



# 【変更点 3】AI要約比較セクション
st.header("🤖 AIによる案件・技術者の要約")
col_job, col_eng = st.columns(2)

def display_summary(title, document_text, assignee, item_id, page_link, session_key):
    doc_parts = document_text.split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", document_text)
    
    with st.container(border=True):
        st.subheader(title)
        if assignee: st.caption(f"**担当:** {assignee}")
        if meta_info: st.caption(meta_info.replace("][", " | ").strip("[]"))
        st.markdown(main_doc)
        
        # 【変更点 4】詳細ページへのボタンを追加
        if st.button("詳細を見る", key=f"nav_{item_id}", use_container_width=True):
            st.session_state[session_key] = item_id
            st.switch_page(page_link)

with col_job:
    project_name = job_data['project_name'] or f"案件 (ID: {job_data['id']})"
    display_summary(
        title=f"💼 {project_name}",
        document_text=job_data['document'],
        assignee=job_data['assignee_name'],
        item_id=job_data['id'],
        page_link="pages/6_案件詳細.py",
        session_key='selected_job_id'
    )

with col_eng:
    engineer_name = engineer_data['name'] or f"技術者 (ID: {engineer_data['id']})"
    display_summary(
        title=f"👤 {engineer_name}",
        document_text=engineer_data['document'],
        assignee=engineer_data['assignee_name'],
        item_id=engineer_data['id'],
        page_link="pages/5_技術者詳細.py",
        session_key='selected_engineer_id'
    )
st.divider()


# 【変更点 1】AIマッチング評価セクションを一番上に移動
st.header("📊 AIマッチング評価")
summary_data = be.get_match_summary_with_llm(job_data['document'], engineer_data['document'])
with st.container(border=True):
    col1, col2, col3 = st.columns([1.5, 3, 3])
    with col1:
        st.metric("マッチ度", f"{float(match_data['score']):.1f}%")
        # AIによる総合評価も表示
        if summary_data and summary_data.get('summary'):
            st.markdown(f"**総合評価: {summary_data.get('summary')}**")
    with col2:
        st.markdown("###### ✅ ポジティブな点")
        if summary_data and summary_data.get('positive_points'):
            for point in summary_data['positive_points']: st.markdown(f"- {point}")
        else: st.caption("分析中または特筆すべき点はありません。")
    with col3:
        st.markdown("###### ⚠️ 懸念点・確認事項")
        if summary_data and summary_data.get('concern_points'):
            for point in summary_data['concern_points']: st.markdown(f"- {point}")
        else: st.caption("分析中または特に懸念はありません。")
st.divider()


# --- 元情報（タブ）セクション ---
st.header("📄 元の情報ソース")
tab1, tab2 = st.tabs(["案件の元情報", "技術者の元情報"])
with tab1:
    st.text_area("案件ソース", value=get_source_text(job_data['source_data_json']), height=400, disabled=True, label_visibility="collapsed")
with tab2:
    st.text_area("技術者ソース", value=get_source_text(engineer_data['source_data_json']), height=400, disabled=True, label_visibility="collapsed")

st.divider()

# 【変更点 2】操作メニューを追加
with st.expander("マッチングの操作"):
    is_hidden = match_data['is_hidden'] == 1
    if not is_hidden:
        if st.button("🙈 このマッチング結果を非表示にする", use_container_width=True, type="secondary"):
            if be.hide_match(selected_match_id):
                st.success("このマッチングを非表示にしました。"); st.rerun()
            else:
                st.error("更新に失敗しました。")
    else:
        st.info("このマッチングは非表示に設定されています。")
st.divider()


if st.button("ダッシュボードに戻る"):
    if 'selected_match_id' in st.session_state: del st.session_state['selected_match_id']
    st.switch_page("1_ダッシュボード.py")
