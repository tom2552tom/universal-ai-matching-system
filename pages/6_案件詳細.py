import streamlit as st
import backend as be
import json
import html

st.set_page_config(page_title="案件詳細", layout="wide")

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
selected_id = st.session_state.get('selected_job_id', None)
if selected_id is None:
    st.error("案件が選択されていません。案件管理ページから案件を選択してください。")
    if st.button("案件管理に戻る"): st.switch_page("pages/4_案件管理.py")
    st.stop()

# --- DBからデータを取得 ---
conn = be.get_db_connection()
job_data = conn.execute("SELECT id, project_name, document, source_data_json FROM jobs WHERE id = ?", (selected_id,)).fetchone()

if job_data:
    # --- タイトル表示 ---
    project_name = job_data['project_name'] if job_data['project_name'] else f"案件 (ID: {selected_id})"
    st.title(f"💼 {project_name}")
    st.caption(f"ID: {selected_id}")
    st.divider()

    # --- AIによる要約情報の表示 ---
    st.header("🤖 AIによる要約情報")
    doc_parts = job_data['document'].split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", job_data['document'])
    if meta_info: st.markdown(f"**抽出されたメタ情報:** `{meta_info}`")
    sanitized_main_doc = html.escape(main_doc)
    st.markdown(f'<div class="text-container">{sanitized_main_doc}</div>', unsafe_allow_html=True)
    st.divider()

    # --- 元の情報の表示 ---
    st.header("📄 元のメール・添付ファイル内容")
    source_json_str = job_data['source_data_json']
    
    if source_json_str:
        try:
            source_data = json.loads(source_json_str)
            st.subheader("メール本文")
            email_body = source_data.get("body", "（メール本文がありません）")
            sanitized_body = html.escape(email_body)
            st.markdown(f'<div class="text-container" style="max-height: 500px;">{sanitized_body}</div>', unsafe_allow_html=True)
            attachments = source_data.get("attachments", [])
            if attachments:
                st.subheader("添付ファイル（クリックで関連技術者を検索）")
                search_results_placeholder = st.container()
                for i, att in enumerate(attachments):
                    filename = att.get("filename", "名称不明のファイル")
                    content = att.get("content", "")
                    if st.button(f"📄 {filename}", key=f"att_btn_{selected_id}_{i}"):
                        search_results_placeholder.empty()
                        if content and not content.startswith("["):
                            with search_results_placeholder, st.spinner(f"「{filename}」の内容で最適な技術者を検索中..."):
                                similarities, ids = be.search(content, be.ENGINEER_INDEX_FILE, top_k=5)
                                if ids:
                                    st.success(f"関連性の高い技術者が {len(ids)}名 見つかりました。")
                                    matching_engineers = be.get_records_by_ids("engineers", ids)
                                    for i, eng in enumerate(matching_engineers):
                                        score = similarities[i] * 100
                                        with st.container(border=True):
                                            engineer_name = eng['name'] if eng['name'] else f"技術者(ID: {eng['id']})"
                                            st.markdown(f"**{engineer_name}** (マッチ度: **{score:.1f}%**)")
                                            eng_doc_parts = eng['document'].split('\n---\n', 1)
                                            eng_main_doc = eng_doc_parts[1] if len(eng_doc_parts) > 1 else eng['document']
                                            st.caption(eng_main_doc.replace('\n', ' ').replace('\r', '')[:150] + "...")
                                else: st.info("関連する技術者は見つかりませんでした。")
                        else:
                            with search_results_placeholder: st.warning(f"「{filename}」から検索可能なテキストを抽出できませんでした。")
        except json.JSONDecodeError:
            st.error("元のデータの解析に失敗しました。"); st.text(source_json_str)
    else: st.warning("このデータには元のテキストが保存されていません。")

    st.divider()

    # --- マッチング済みの技術者一覧 ---
    st.header("🤝 マッチング済みの技術者一覧")
    matched_engineers = conn.execute("""
        SELECT e.id, e.name, e.document, r.score 
        FROM matching_results r
        JOIN engineers e ON r.engineer_id = e.id
        WHERE r.job_id = ?
        ORDER BY r.score DESC
    """, (selected_id,)).fetchall()

    if not matched_engineers:
        st.info("この案件にマッチング済みの技術者はいません。")
    else:
        st.write(f"計 {len(matched_engineers)} 名の技術者がマッチングしています。")
        for eng in matched_engineers:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    engineer_name = eng['name'] if eng['name'] else f"技術者 (ID: {eng['id']})"
                    st.markdown(f"##### {engineer_name}")
                    eng_doc_parts = eng['document'].split('\n---\n', 1)
                    eng_main_doc = eng_doc_parts[1] if len(eng_doc_parts) > 1 else eng['document']
                    st.caption(eng_main_doc.replace('\n', ' ').replace('\r', '')[:200] + "...")
                with col2:
                    st.metric("マッチ度", f"{eng['score']:.1f}%")
                    if st.button("詳細を見る", key=f"matched_eng_detail_{eng['id']}", use_container_width=True):
                        # DBコネクションを再取得
                        temp_conn = be.get_db_connection()
                        match_res = temp_conn.execute(
                            "SELECT id FROM matching_results WHERE job_id = ? AND engineer_id = ?",
                            (selected_id, eng['id'])
                        ).fetchone()
                        temp_conn.close()
                        
                        if match_res:
                            st.session_state['selected_match_id'] = match_res['id']
                            st.switch_page("pages/7_マッチング詳細.py")
                        else:
                            st.error("対応するマッチング結果が見つかりませんでした。")
else:
    st.error("指定されたIDの案件情報が見つかりませんでした。")

conn.close()
st.divider()
if st.button("一覧に戻る"):
    if 'selected_job_id' in st.session_state: del st.session_state['selected_job_id']
    st.switch_page("pages/4_案件管理.py")
