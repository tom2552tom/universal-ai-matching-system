import streamlit as st
import backend as be
import json
import html
import time
from datetime import datetime

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
job_data = None
matched_engineers = []
try:
    with conn.cursor() as cursor:
        # 案件データの取得
        job_query = """
        SELECT 
            j.id, j.project_name, j.document, j.source_data_json, j.assigned_user_id, j.is_hidden,
            u.username as assigned_username
        FROM jobs j
        LEFT JOIN users u ON j.assigned_user_id = u.id
        WHERE j.id = %s
        """
        cursor.execute(job_query, (selected_id,))
        job_data = cursor.fetchone()

        if job_data:
            # マッチング済み技術者データの取得
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
finally:
    if conn:
        conn.close()


if job_data:
    # --- タイトル表示 ---
    is_currently_hidden = job_data['is_hidden'] == 1
    project_name = job_data['project_name'] or f"案件 (ID: {selected_id})"
    title_display = f"💼 {project_name}"
    if is_currently_hidden:
        title_display += " `非表示`"
    st.title(title_display)
    st.caption(f"ID: {selected_id}")
    st.divider()

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

    # --- 案件の操作（表示/非表示/削除）セクション ---
    with st.expander("案件の操作", expanded=False):
        if is_currently_hidden:
            if st.button("✅ この案件を再表示する", use_container_width=True, type="primary"):
                if be.set_job_visibility(selected_id, 0): st.success("案件を再表示しました。"); st.rerun()
                else: st.error("更新に失敗しました。")
        else:
            if st.button("🙈 この案件を非表示にする (アーカイブ)", type="secondary", use_container_width=True):
                if be.set_job_visibility(selected_id, 1): st.success("案件を非表示にしました。"); st.rerun()
                else: st.error("更新に失敗しました。")
        
        st.markdown("---")
        
        delete_confirmation_key = f"confirm_delete_job_{selected_id}"

        if delete_confirmation_key not in st.session_state:
            st.session_state[delete_confirmation_key] = False

        if st.button("🚨 この案件を完全に削除する", type="secondary", use_container_width=True, key=f"delete_job_main_btn_{selected_id}"):
            st.session_state[delete_confirmation_key] = not st.session_state[delete_confirmation_key]

        if st.session_state[delete_confirmation_key]:
            st.warning("**本当にこの案件を削除しますか？**\n\nこの操作は取り消せません。関連するマッチング結果もすべて削除されます。")
            
            col_check, col_btn = st.columns([3,1])
            with col_check:
                confirm_check = st.checkbox("はい、削除を承認します。", key=f"delete_job_confirm_checkbox_{selected_id}")
            with col_btn:
                if st.button("削除実行", disabled=not confirm_check, use_container_width=True, key=f"delete_job_execute_btn_{selected_id}"):
                    if be.delete_job(selected_id):
                        st.success(f"案件 (ID: {selected_id}) を完全に削除しました。案件管理ページに戻ります。")
                        time.sleep(2)
                        del st.session_state['selected_job_id']
                        if delete_confirmation_key in st.session_state:
                            del st.session_state[delete_confirmation_key]
                        st.switch_page("pages/4_案件管理.py")
                    else:
                        st.error("案件の削除に失敗しました。")
            
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
    source_json_str = job_data.get('source_data_json')
    if source_json_str:
        try:
            source_data = json.loads(source_json_str)

            # ▼▼▼ 変更点: UIを「受信元」「本文」「添付」に分割 ▼▼▼
            st.subheader("✉️ 受信元情報")
            received_at_iso = source_data.get('received_at')
            from_address = source_data.get('from', '取得不可')
            if received_at_iso:
                dt_obj = datetime.fromisoformat(received_at_iso)
                formatted_date = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
            else:
                formatted_date = '取得不可'
            
            with st.container(border=True):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**受信日時**"); st.write(formatted_date)
                with col2:
                    st.markdown("**差出人**"); st.write(from_address)
            
            st.subheader("📝 メール本文（編集可能）")
            edited_body = st.text_area("メール本文を編集", value=source_data.get("body", ""), height=300, label_visibility="collapsed", key=f"job_body_editor_{selected_id}")
            
            if st.button("メール本文を更新する", type="primary"):
                # 本文のみを更新し、添付ファイルには触れない
                source_data['body'] = edited_body
                new_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
                if be.update_job_source_json(selected_id, new_json_str):
                    st.success("メール本文を更新しました。")
                    time.sleep(1); st.rerun()
                else:
                    st.error("データベースの更新に失敗しました。")

            st.subheader("📎 添付ファイル内容（読み取り専用）")
            attachments = source_data.get("attachments", [])
            if attachments:
                for i, att in enumerate(attachments):
                    with st.container(border=True):
                        st.markdown(f"**ファイル名:** `{att.get('filename', '名称不明')}`")
                        content = att.get('content', '（内容なし）')
                        st.text_area(f"att_content_{i}", value=content, height=200, disabled=True, label_visibility="collapsed")
            else:
                st.info("このメールには解析可能な添付ファイルはありませんでした。")
            # ▲▲▲ 変更点 ここまで ▲▲▲


        except (json.JSONDecodeError, TypeError, ValueError):
            st.error("元のデータの解析に失敗しました。")
    else: st.warning("このデータには元のテキストが保存されていません。")
    st.divider()

    # --- マッチング済みの技術者一覧 ---
    st.header("🤝 マッチング済みの技術者一覧")

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

st.divider()



st.header("⚙️ AI再評価＋マッチング")
st.info("「情報ソースを更新する」ボタンで要件を変更した場合、このボタンを押すことで、最新の情報ですべての技術者とのマッチングを再実行します。")

with st.container(border=True):
    st.markdown("##### マッチング条件設定")
    col1, col2 = st.columns(2)
    with col1:
        target_rank = st.selectbox(
            "目標ランク",
            options=['S', 'A', 'B', 'C'],
            index=2,
            help="このランク以上のマッチングが見つかるまで処理を続けます。",
            key=f"job_target_rank_{selected_id}" # キーを案件用に変更
        )
    with col2:
        target_count = st.number_input(
            "目標件数",
            min_value=1,
            max_value=50,
            value=5,
            help="目標ランク以上のマッチングがこの件数に達したら処理を終了します。",
            key=f"job_target_count_{selected_id}" # キーを案件用に変更
        )

re_eval_confirmation_key = f"confirm_re_evaluate_job_{selected_id}"

if re_eval_confirmation_key not in st.session_state:
    st.session_state[re_eval_confirmation_key] = False

if st.button("🤖 AI再評価と再マッチングを実行する", type="primary", use_container_width=True, key=f"re_eval_job_main_btn_{selected_id}"):
    st.session_state[re_eval_confirmation_key] = not st.session_state[re_eval_confirmation_key]
    st.rerun()

if st.session_state[re_eval_confirmation_key]:
    with st.container(border=True):
        st.warning(f"**本当に再評価と再マッチングを実行しますか？**\n\nこの案件に関する既存のマッチング結果は**すべて削除**され、最新の情報で再計算されます。\n\n**実行条件:**\n- **目標ランク:** {target_rank} ランク以上\n- **目標件数:** {target_count} 件")
        
        confirm_check = st.checkbox("はい、すべての既存マッチング結果の削除を承認し、再実行します。", key=f"re_eval_job_confirm_checkbox_{selected_id}")
        
        col_run, col_cancel, _ = st.columns([1, 1, 3])
        with col_run:
            execute_button_clicked = st.button("再評価実行", disabled=not confirm_check, use_container_width=True, key=f"re_eval_job_execute_btn_{selected_id}")
        with col_cancel:
            if st.button("キャンセル", use_container_width=True, key=f"cancel_job_re_eval_{selected_id}"):
                st.session_state[re_eval_confirmation_key] = False
                st.rerun()

        if execute_button_clicked:
            log_placeholder = st.container()
            with log_placeholder:
                with st.spinner("再評価と再マッチングを実行中..."):
                    # ▼▼▼【backendの新しい関数を呼び出す】▼▼▼
                    success = be.re_evaluate_and_match_single_job(
                        job_id=selected_id, # ここでは案件IDを渡す
                        target_rank=target_rank,
                        target_count=target_count
                    )
                
                if success:
                    st.success("AIによる再評価と再マッチングが完了しました。")
                    st.balloons()
                    st.info("2秒後に画面を自動で更新します...")
                    time.sleep(2)
                    st.session_state[re_eval_confirmation_key] = False
                    st.rerun()
                else:
                    st.error("処理中にエラーが発生しました。詳細は上記のログを確認してください。")

st.divider()


if st.button("一覧に戻る"):
    if 'selected_job_id' in st.session_state: del st.session_state['selected_job_id']
    st.switch_page("pages/4_案件管理.py")
