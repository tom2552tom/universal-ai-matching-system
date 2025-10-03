import streamlit as st
import backend as be
import json
import html

st.set_page_config(page_title="技術者詳細", layout="wide")

# --- 表示用のカスタムCSS ---
custom_css = """
<style>
    .text-container {
        border: 1px solid #333; padding: 15px; border-radius: 5px; background-color: #1a1a1a;
        max-height: 400px; overflow-y: auto; white-space: pre-wrap;
        word-wrap: break-word; font-family: monospace; font-size: 0.9em;
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# --- ID取得 ---
selected_id = st.session_state.get('selected_engineer_id', None)
if selected_id is None:
    st.error("技術者が選択されていません。ダッシュボードまたは技術者管理ページから技術者を選択してください。")
    if st.button("ダッシュボードに戻る"): st.switch_page("1_ダッシュボード.py")
    st.stop()

# --- DBからデータを取得 ---
conn = be.get_db_connection()
engineer_data = conn.execute("SELECT id, name, document, source_data_json FROM engineers WHERE id = ?", (selected_id,)).fetchone()

if engineer_data:
    # --- タイトル表示 ---
    engineer_name = engineer_data['name'] if engineer_data['name'] else f"技術者 (ID: {selected_id})"
    st.title(f"👤 {engineer_name}")
    st.caption(f"ID: {selected_id}")
    st.divider()

    # --- AIによる要約情報の表示 ---
    st.header("🤖 AIによる要約情報")
    doc_parts = engineer_data['document'].split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", engineer_data['document'])
    if meta_info: st.markdown(f"**抽出されたメタ情報:** `{meta_info}`")
    sanitized_main_doc = html.escape(main_doc)
    st.markdown(f'<div class="text-container">{sanitized_main_doc}</div>', unsafe_allow_html=True)
    st.divider()

    # --- 元の情報の表示 ---
    st.header("📄 元のメール・添付ファイル内容")
    source_json_str = engineer_data['source_data_json']
    
    if source_json_str:
        try:
            source_data = json.loads(source_json_str)
            st.subheader("メール本文")
            email_body = source_data.get("body", "（メール本文がありません）")
            sanitized_body = html.escape(email_body)
            st.markdown(f'<div class="text-container" style="max-height: 500px;">{sanitized_body}</div>', unsafe_allow_html=True)
            attachments = source_data.get("attachments", [])
            if attachments:
                st.subheader("添付ファイル（クリックで関連案件を検索）")
                search_results_placeholder = st.container()
                for i, att in enumerate(attachments):
                    filename = att.get("filename", "名称不明のファイル")
                    content = att.get("content", "")
                    if st.button(f"📄 {filename}", key=f"att_btn_{selected_id}_{i}"):
                        search_results_placeholder.empty()
                        if content and not content.startswith("["):
                            with search_results_placeholder, st.spinner(f"「{filename}」の内容で最適な案件を検索中..."):
                                similarities, ids = be.search(content, be.JOB_INDEX_FILE, top_k=5)
                                if ids:
                                    st.success(f"関連性の高い案件が {len(ids)}件 見つかりました。")
                                    matching_jobs = be.get_records_by_ids("jobs", ids)
                                    for i, job in enumerate(matching_jobs):
                                        score = similarities[i] * 100
                                        with st.container(border=True):
                                            project_name = job['project_name'] if job['project_name'] else f"案件(ID: {job['id']})"
                                            st.markdown(f"**{project_name}** (マッチ度: **{score:.1f}%**)")
                                            job_doc_parts = job['document'].split('\n---\n', 1)
                                            job_main_doc = job_doc_parts[1] if len(job_doc_parts) > 1 else job['document']
                                            st.caption(job_main_doc.replace('\n', ' ').replace('\r', '')[:150] + "...")
                                else: st.info("関連する案件は見つかりませんでした。")
                        else:
                            with search_results_placeholder: st.warning(f"「{filename}」から検索可能なテキストを抽出できませんでした。")
        except json.JSONDecodeError:
            st.error("元のデータの解析に失敗しました。"); st.text(source_json_str)
    else: st.warning("このデータには元のテキストが保存されていません。")

    st.divider()

    # --- マッチング済みの案件一覧 ---
    st.header("🤝 マッチング済みの案件一覧")
    matched_jobs = conn.execute("""
        SELECT j.id, j.project_name, j.document, r.score 
        FROM matching_results r
        JOIN jobs j ON r.job_id = j.id
        WHERE r.engineer_id = ?
        ORDER BY r.score DESC
    """, (selected_id,)).fetchall()

    if not matched_jobs:
        st.info("この技術者にマッチング済みの案件はありません。")
    else:
        st.write(f"計 {len(matched_jobs)} 件の案件がマッチングしています。")
        for job in matched_jobs:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    project_name = job['project_name'] if job['project_name'] else f"案件 (ID: {job['id']})"
                    st.markdown(f"##### {project_name}")
                    job_doc_parts = job['document'].split('\n---\n', 1)
                    job_main_doc = job_doc_parts[1] if len(job_doc_parts) > 1 else job['document']
                    st.caption(job_main_doc.replace('\n', ' ').replace('\r', '')[:200] + "...")
                with col2:
                    st.metric("マッチ度", f"{job['score']:.1f}%")
                    if st.button("詳細を見る", key=f"matched_job_detail_{job['id']}", use_container_width=True):
                        # DBコネクションを再取得
                        temp_conn = be.get_db_connection()
                        match_res = temp_conn.execute(
                            "SELECT id FROM matching_results WHERE engineer_id = ? AND job_id = ?",
                            (selected_id, job['id'])
                        ).fetchone()
                        temp_conn.close()
                        
                        if match_res:
                            st.session_state['selected_match_id'] = match_res['id']
                            st.switch_page("pages/7_マッチング詳細.py")
                        else:
                            st.error("対応するマッチング結果が見つかりませんでした。")
else:
    st.error("指定されたIDの技術者情報が見つかりませんでした。")

conn.close()
st.divider()
if st.button("一覧に戻る"):
    if 'selected_engineer_id' in st.session_state: del st.session_state['selected_engineer_id']
    st.switch_page("pages/3_技術者管理.py")
