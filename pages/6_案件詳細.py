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
    # ▼▼▼【ここからが修正箇所です】▼▼▼
    if job_data['document']:
        with st.container(border=True):
            doc_parts = job_data['document'].split('\n---\n', 1)
            meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", job_data['document'])
            
            if meta_info:
                st.caption(meta_info.replace("][", " | ").strip("[]"))
            st.markdown(main_doc)
    else:
        st.info("この案件にはAIによる要約情報がありません。")
    # ▲▲▲【ここまでが修正箇所です】▲▲▲
    st.divider()

    # --- 元のメール・添付ファイル内容 ---
    st.header("📄 元のメール・添付ファイル内容")
    source_json_str = job_data['source_data_json']
    if source_json_str:
        try:
            source_data = json.loads(source_json_str)
            st.subheader("メール本文（編集可能）")
            edited_body = st.text_area("メール本文", value=source_data.get("body", ""), height=400, label_visibility="collapsed", key=f"job_mail_editor_{selected_id}")
            if st.button("メール本文を更新する", type="primary"):
                source_data['body'] = edited_body
                new_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
                if be.update_job_source_json(selected_id, new_json_str): st.success("メール本文を更新しました。"); st.rerun()
                else: st.error("データベースの更新に失敗しました。")
            
            # 添付ファイル関連のロジックは、必要であればここに追加します。
            # 現状のコードにはないため、一旦省略しています。

        except json.JSONDecodeError: st.error("元のデータの解析に失敗しました。")
    else: st.warning("このデータには元のテキストが保存されていません。")
    st.divider()

    # --- マッチング済みの技術者一覧 ---
    st.header("🤝 マッチング済みの技術者一覧")
    matched_engineers = conn.execute("""
        SELECT e.id, e.name, e.document, r.score 
        FROM matching_results r
        JOIN engineers e ON r.engineer_id = e.id
        WHERE r.job_id = ? AND (e.is_hidden = 0 OR e.is_hidden IS NULL)
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
                    if st.button("技術者詳細へ", key=f"matched_eng_detail_{eng['id']}", use_container_width=True):
                        st.session_state['selected_engineer_id'] = eng['id']
                        st.switch_page("pages/5_技術者詳細.py")
else:
    st.error("指定されたIDの案件情報が見つかりませんでした。")

conn.close()
st.divider()
if st.button("一覧に戻る"):
    if 'selected_job_id' in st.session_state: del st.session_state['selected_job_id']
    st.switch_page("pages/4_案件管理.py")
