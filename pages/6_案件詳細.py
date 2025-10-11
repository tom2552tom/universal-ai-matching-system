import streamlit as st
import backend as be
import json
import html
import time

try:
    from backend import get_evaluation_html
except ImportError:
    def get_evaluation_html(grade, font_size='2em'):
        if not grade: return ""
        return f"<p style='font-size:{font_size}; text-align:center;'>{grade}</p>"

st.set_page_config(page_title="案件詳細", layout="wide")

# --- 表示用のカスタムCSS ---
st.markdown("""
<style>
    .text-container {
        border: 1px solid #333; padding: 15px; border-radius: 5px; background-color: #1a1a1a;
        max-height: 400px; overflow-y: auto; white-space: pre-wrap;
        word-wrap: break-word; font-family: monospace; font-size: 0.9em;
    }
</style>
""", unsafe_allow_html=True)

# --- ID取得 ---
selected_id = st.session_state.get('selected_job_id', None)
if selected_id is None:
    st.error("案件が選択されていません。案件管理ページから案件を選択してください。")
    if st.button("案件管理に戻る"): st.switch_page("pages/4_案件管理.py")
    st.stop()

# --- DBから全データを取得 ---
conn = be.get_db_connection()
cursor = conn.cursor()

# ▼▼▼【ここが修正箇所】▼▼▼
# プレースホルダを %s に変更し、executeとfetchoneを分離
query = """
SELECT 
    j.id, j.project_name, j.document, j.source_data_json, j.assigned_user_id, j.is_hidden,
    u.username as assigned_username
FROM jobs j
LEFT JOIN users u ON j.assigned_user_id = u.id
WHERE j.id = %s
"""
cursor.execute(query, (selected_id,))
job_data = cursor.fetchone()
# ▲▲▲【修正ここまで】▲▲▲

if job_data:
    # --- タイトル表示 ---
    is_currently_hidden = job_data['is_hidden'] == 1
    project_name = job_data['project_name'] or f"案件 (ID: {selected_id})"
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
                st.success(f"担当者を更新しました。"); time.sleep(1); st.rerun()
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
            if meta_info: st.caption(meta_info.replace("][", " | ").strip("[]"))
            st.markdown(main_doc)
    else:
        st.info("この案件にはAIによる要約情報がありません。")
    st.divider()

    # --- 元のメール・添付ファイル内容 ---
    st.header("📄 元の情報ソース（編集可能）")
    source_json_str = job_data['source_data_json']
    if source_json_str:
        try:
            source_data = json.loads(source_json_str)
            st.subheader("情報ソース（メール本文・添付ファイル内容）")
            # 技術者詳細と同様に、本文と添付ファイル内容を統合して表示
            initial_text_parts = [source_data.get("body", "")]
            attachments = source_data.get("attachments", [])
            if attachments:
                for att in attachments:
                    filename = att.get("filename", "名称不明")
                    content = att.get("content", "")
                    if content:
                        initial_text_parts.append(f"\n\n--- 添付ファイル: {filename} ---\n{content}")
            full_source_text = "".join(initial_text_parts)

            edited_text = st.text_area("情報ソースを編集", value=full_source_text, height=400, label_visibility="collapsed", key=f"job_source_editor_{selected_id}")
            
            if st.button("情報ソースを更新する", type="primary"):
                source_data['body'] = edited_text
                if 'attachments' in source_data:
                    for att in source_data['attachments']:
                        if 'content' in att: att['content'] = ''
                
                new_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
                if be.update_job_source_json(selected_id, new_json_str):
                    st.success("情報ソースを更新しました。今後、この案件の再評価を行う際にこの内容が使用されます。")
                    time.sleep(2); st.rerun()
                else: st.error("データベースの更新に失敗しました。")

        except json.JSONDecodeError: st.error("元のデータの解析に失敗しました。")
    else: st.warning("このデータには元のテキストが保存されていません。")
    st.divider()

    # --- マッチング済みの技術者一覧 ---
    st.header("🤝 マッチング済みの技術者一覧")

    # ▼▼▼【ここも修正箇所】▼▼▼
    # プレースホルダを %s に変更し、executeとfetchallを分離
    matched_engineers_query = """
        SELECT 
            e.id as engineer_id, e.name, e.document, 
            r.score, r.id as match_id, r.grade
        FROM matching_results r
        JOIN engineers e ON r.engineer_id = e.id
        WHERE r.job_id = %s 
          AND e.is_hidden = 0
          AND r.is_hidden = 0
        ORDER BY r.score DESC
    """
    cursor.execute(matched_engineers_query, (selected_id,))
    matched_engineers = cursor.fetchall()
    # ▲▲▲【修正ここまで】▲▲▲

    if not matched_engineers:
        st.info("この案件にマッチング済みの技術者はいません。")
    else:
        st.write(f"計 {len(matched_engineers)} 名の技術者がマッチングしています。")
        for eng in matched_engineers:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    engineer_name = eng['name'] or f"技術者 (ID: {eng['engineer_id']})"
                    st.markdown(f"##### {engineer_name}")
                    eng_doc_parts = eng['document'].split('\n---\n', 1)
                    eng_main_doc = eng_doc_parts[1] if len(eng_doc_parts) > 1 else eng['document']
                    st.caption(eng_main_doc.replace('\n', ' ').replace('\r', '')[:200] + "...")
                with col2:
                    st.markdown(get_evaluation_html(eng['grade'], font_size='2em'), unsafe_allow_html=True)
                    
                    if st.button("マッチング詳細へ", key=f"matched_job_detail_{eng['match_id']}", use_container_width=True):
                        st.session_state['selected_match_id'] = eng['match_id']
                        st.switch_page("pages/7_マッチング詳細.py")

else:
    st.error("指定されたIDの案件情報が見つかりませんでした。")

conn.close()
st.divider()
if st.button("一覧に戻る"):
    if 'selected_job_id' in st.session_state: del st.session_state['selected_job_id']
    st.switch_page("pages/4_案件管理.py")
