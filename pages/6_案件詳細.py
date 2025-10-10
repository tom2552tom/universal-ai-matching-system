import streamlit as st
import backend as be
import json
import html
import base64
import time

# backend から get_evaluation_html をインポート
try:
    from backend import get_evaluation_html
except ImportError:
    def get_evaluation_html(grade, font_size='2em'): # 簡易版を定義
        if not grade: return ""
        return f"<p style='font-size:{font_size}; text-align:center;'>{grade}</p>"

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

# --- DBから全データを取得 ---
conn = be.get_db_connection()
query = """
SELECT 
    j.id, j.project_name, j.document, j.source_data_json, j.assigned_user_id, j.is_hidden,
    u.username as assigned_username
FROM jobs j
LEFT JOIN users u ON j.assigned_user_id = u.id
WHERE j.id = ?
"""
job_data = conn.execute(query, (selected_id,)).fetchone()

if job_data:
    # --- タイトル表示 ---
    is_currently_hidden = job_data['is_hidden'] == 1
    project_name = job_data['project_name'] if job_data['project_name'] else f"案件 (ID: {selected_id})"
    title_display = f"💼 {project_name}"
    if is_currently_hidden:
        title_display += " `非表示`"
    st.title(title_display)
    st.caption(f"ID: {selected_id}")

    # --- 担当者情報セクション ---
    st.subheader("👤 担当者情報")
    all_users = be.get_all_users()
    user_options = {"未割り当て": None, **{user['username']: user['id'] for user in all_users}}
    current_user_id = job_data['assigned_user_id']
    id_to_username = {v: k for k, v in user_options.items()}
    current_username = id_to_username.get(current_user_id, "未割り当て")

    col1, col2 = st.columns([1, 2])
    with col1: st.metric("現在の担当者", current_username)
    with col2:
        option_names = list(user_options.keys())
        default_index = option_names.index(current_username)
        selected_username = st.selectbox("担当者を変更/割り当て", options=option_names, index=default_index, key=f"job_user_assign_{selected_id}")
        if st.button("担当者を更新", use_container_width=True):
            selected_user_id = user_options[selected_username]
            if be.assign_user_to_job(selected_id, selected_user_id):
                st.success(f"担当者を更新しました。"); st.rerun()
            else: st.error("担当者の更新に失敗しました。")
    st.divider()

    # --- 案件の操作（表示/非表示）セクション ---
    with st.expander("案件の操作", expanded=False):
        if is_currently_hidden:
            if st.button("✅ この案件を再表示する", use_container_width=True, type="primary"):
                if be.set_job_visibility(selected_id, 0): st.success("案件を再表示しました。"); st.rerun()
                else: st.error("更新に失敗しました。")
        else:
            if st.button("🙈 この案件を非表示にする (アーカイブ)", type="secondary", use_container_width=True):
                if be.set_job_visibility(selected_id, 1): st.success("案件を非表示にしました。"); st.rerun()
                else: st.error("更新に失敗しました。")
    st.divider()

    # --- AIによる要約情報 ---
    st.header("🤖 AIによる要約情報")
    if job_data['document']:
        with st.container(border=True):
            doc_parts = job_data['document'].split('\n---\n', 1)
            meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", job_data['document'])
            
            if meta_info:
                st.caption(meta_info.replace("][", " | ").strip("[]"))
            st.markdown(main_doc)
    else:
        st.info("この案件にはAIによる要約情報がありません。")
    st.divider()

    # --- 元の情報の表示 ---
    st.header("📄 元の情報ソース（編集可能）")
    source_json_str = job_data['source_data_json']
    
    if source_json_str:
        try:
            source_data = json.loads(source_json_str)

            # --- テキストの統合 ---
            initial_text_parts = [source_data.get("body", "")]
            attachments = source_data.get("attachments", [])
            if attachments:
                for att in attachments:
                    filename = att.get("filename", "名称不明")
                    content = att.get("content", "")
                    if content:
                        initial_text_parts.append(f"\n\n--- 添付ファイル: {filename} ---\n{content}")
            full_source_text = "".join(initial_text_parts)

            # --- 統合されたテキストエリア ---
            st.markdown("メール本文と添付ファイルの内容が統合されています。案件内容の追加や修正はこちらで行ってください。")
            edited_source_text = st.text_area(
                "情報ソースを編集",
                value=full_source_text,
                height=600,
                label_visibility="collapsed",
                key=f"job_source_editor_{selected_id}"
            )
            st.warning("案件内容を変更した場合、AI再評価＋再マッチングを行うことで、新たな技術者がヒットすることがあります。")

            if st.button("情報ソースを更新する", type="primary"):
                source_data['body'] = edited_source_text
                if 'attachments' in source_data:
                    for att in source_data['attachments']:
                        if 'content' in att:
                            att['content'] = ''
                
                new_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
                if be.update_job_source_json(selected_id, new_json_str):
                    success_message = st.success("情報ソースを更新しました。下の「AI再評価」ボタンを押して、変更をマッチングに反映させてください。")
                    time.sleep(3)
                    success_message.empty()
                    st.rerun()
                else:
                    st.error("データベースの更新に失敗しました。")

            st.divider()

            # --- 添付ファイルのダウンロードセクション ---
            if attachments:
                st.subheader("原本ファイルのダウンロード")
                for i, att in enumerate(attachments):
                    filename = att.get("filename", "名称不明のファイル")
                    content_b64 = att.get("content_b64", "")
                    if content_b64:
                        try:
                            file_bytes = base64.b64decode(content_b64)
                            st.download_button(
                                label=f"📄 {filename}",
                                data=file_bytes,
                                file_name=filename,
                                key=f"att_dl_btn_{selected_id}_{i}"
                            )
                        except Exception as e:
                            st.warning(f"ファイル「{filename}」のダウンロード準備に失敗しました: {e}")
                st.divider()

        except json.JSONDecodeError: st.error("元のデータの解析に失敗しました。")
    else: st.warning("このデータには元のテキストが保存されていません。")
    st.divider()

    # --- マッチング済みの技術者一覧 ---
    st.header("🤝 マッチング済みの技術者一覧")
    matched_engineers_query = """
        SELECT 
            e.id as engineer_id, e.name, e.document, r.score, r.id as match_id, r.grade
        FROM matching_results r
        JOIN engineers e ON r.engineer_id = e.id
        WHERE r.job_id = ? AND e.is_hidden = 0 AND r.is_hidden = 0
        ORDER BY r.score DESC
    """
    matched_engineers = conn.execute(matched_engineers_query, (selected_id,)).fetchall()

    if not matched_engineers:
        st.info("この案件にマッチング済みの技術者はいません。")
    else:
        st.write(f"計 {len(matched_engineers)} 名の技術者がマッチングしています。")
        for eng in matched_engineers:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    engineer_name = eng['name'] if eng['name'] else f"技術者 (ID: {eng['engineer_id']})"
                    st.markdown(f"##### {engineer_name}")
                    eng_doc_parts = eng['document'].split('\n---\n', 1)
                    eng_main_doc = eng_doc_parts[1] if len(eng_doc_parts) > 1 else eng['document']
                    st.caption(eng_main_doc.replace('\n', ' ').replace('\r', '')[:200] + "...")
                with col2:
                    st.markdown(get_evaluation_html(eng['grade'], font_size='2em'), unsafe_allow_html=True)
                    
                    if st.button("マッチング詳細へ", key=f"matched_eng_detail_{eng['match_id']}", use_container_width=True):
                        st.session_state['selected_match_id'] = eng['match_id']
                        st.switch_page("pages/7_マッチング詳細.py")
else:
    st.error("指定されたIDの案件情報が見つかりませんでした。")

conn.close()
st.divider()

# --- AI再評価ボタン ---
st.header("⚙️ AI再評価＋マッチング")
if st.button("🤖 AI再評価と再マッチングを実行する", type="primary", use_container_width=True):
    with st.status("再評価と再マッチングを実行中...", expanded=True) as status:
        log_container = st.container(height=300)
        log_container.write(f"案件ID: {selected_id} の情報を最新化し、再マッチングを開始します。")
        
        import io
        import contextlib
        
        log_stream = io.StringIO()
        with contextlib.redirect_stdout(log_stream):
            # 案件用の再評価関数を呼び出す
            success = be.re_evaluate_and_match_single_job(selected_id)
        
        log_container.text(log_stream.getvalue())

        if success:
            status.update(label="処理が完了しました！", state="complete")
            st.success("AIによる再評価と再マッチングが完了しました。ページをリロードして最新のマッチング結果を確認してください。")
            st.balloons()
        else:
            status.update(label="処理に失敗しました", state="error")
            st.error("処理中にエラーが発生しました。詳細はログを確認してください。")
st.divider()


if st.button("一覧に戻る"):
    if 'selected_job_id' in st.session_state: del st.session_state['selected_job_id']
    st.switch_page("pages/4_案件管理.py")
