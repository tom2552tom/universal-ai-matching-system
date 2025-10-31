import streamlit as st
import backend as be
import json
import html
import time
from datetime import datetime
import ui_components as ui

try:
    from backend import get_evaluation_html
except ImportError:
    def get_evaluation_html(grade, font_size='2em'):
        if not grade: return ""
        return f"<p style='font-size:{font_size}; text-align:center;'>{grade}</p>"

ui.apply_global_styles()
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


# ▼▼▼【ここからが修正箇所】▼▼▼

# --- ID取得ロジックの修正 ---
# 1. URLのクエリパラメータからIDを取得
query_id = st.query_params.get("id")

# 2. session_state からIDを取得
session_id = st.session_state.get('selected_job_id')

selected_id = None
if query_id:
    # URLにIDがあれば最優先で採用
    try:
        selected_id = int(query_id)
        # ページ内での状態維持のため、session_stateにもIDをセットしておく
        st.session_state['selected_job_id'] = selected_id
    except (ValueError, TypeError):
        st.error("URLのIDが不正な形式です。")
        st.stop()
elif session_id:
    # URLにIDがなく、session_stateにあればそれを使用
    selected_id = session_id

# --- IDが取得できなかった場合の処理 ---
if selected_id is None:
    st.error("案件が選択されていません。案件管理ページまたはAIアシスタントから案件を選択してください。")
    # 戻るボタンのリンク先も実際のファイル名に合わせる
    if st.button("案件管理に戻る"):
        st.switch_page("pages/4_案件管理") 
    st.stop()

# ▲▲▲【修正ここまで】▲▲▲


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
    # ★★★【ここからが修正の核】★★★
    # --- タイトル・案件名編集セクション ---
    is_currently_hidden = job_data['is_hidden'] == 1
    current_project_name = job_data['project_name'] or "" # Noneの場合は空文字列に

    # 非表示ステータスをタイトルに含める
    title_display = "💼 案件詳細"
    if is_currently_hidden:
        title_display += " `非表示`"
    st.title(title_display)
    st.caption(f"ID: {selected_id}")

    # 案件名を編集するためのフォーム
    with st.form(key="project_name_edit_form"):
        new_project_name = st.text_input(
            "案件名",
            value=current_project_name,
            placeholder="案件名を入力してください"
        )
        submitted_name_change = st.form_submit_button("案件名を更新", use_container_width=True)

        if submitted_name_change:
            if new_project_name.strip() == current_project_name.strip():
                st.toast("案件名に変更はありません。", icon="ℹ️")
            elif be.update_job_project_name(selected_id, new_project_name):
                st.success(f"案件名を「{new_project_name}」に更新しました。")
                st.balloons()
                time.sleep(1)
                st.rerun()
            else:
                st.error("案件名の更新に失敗しました。")
    
    st.divider()
    # ★★★【修正ここまで】★★★



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

# --- UIと状態管理 ---
CONFIRM_KEY = f"rematch_confirm_{selected_id}"
RUN_KEY = f"run_rematch_{selected_id}"
RANK_KEY = f"rematch_rank_{selected_id}"
COUNT_KEY = f"rematch_count_{selected_id}"

if CONFIRM_KEY not in st.session_state:
    st.session_state[CONFIRM_KEY] = False
if RUN_KEY not in st.session_state:
    st.session_state[RUN_KEY] = False

# --- UI定義 ---
with st.container(border=True):
    st.info("この案件の元情報からAIがキーワードを抽出し、関連する技術者候補を絞り込んでから、最新のAI評価に基づいた再マッチングを実行します。")
    
    st.markdown("##### マッチング条件設定")
    col1, col2 = st.columns(2)
    with col1:
        st.selectbox(
            "最低ランク", ['S', 'A', 'B', 'C'], index=1, key=RANK_KEY,
            help="ここで選択したランク以上のマッチング結果を生成します。"
        )
    with col2:
        st.number_input(
            "最大ヒット件数(1-10件)", 1, 10, 5, key=COUNT_KEY,
            help="指定ランク以上のマッチングがこの件数に達すると処理を終了します。"
        )

    if st.button("🤖 AIキーワード抽出による再マッチングを実行", type="primary", use_container_width=True):
        st.session_state[CONFIRM_KEY] = True
        st.rerun()

# --- 確認UIと実行トリガー ---
if st.session_state.get(CONFIRM_KEY):
    with st.container(border=True):
        st.warning(f"**本当に再マッチングを実行しますか？**\n\nこの案件に関する既存のマッチング結果は**すべて削除**されます。")
        st.markdown(f"""
        **実行条件:**
        - **目標ランク:** `{st.session_state[RANK_KEY]}` ランク以上
        - **目標件数:** `{st.session_state[COUNT_KEY]}` 件
        """)
        
        agree = st.checkbox("はい、既存のマッチング結果の削除を承認し、再実行します。")
        
        col_run, col_cancel = st.columns(2)
        with col_run:
            if st.button("実行", disabled=not agree, use_container_width=True):
                st.session_state[RUN_KEY] = True
                st.session_state[CONFIRM_KEY] = False
                st.rerun()
        with col_cancel:
            if st.button("キャンセル"):
                st.session_state[CONFIRM_KEY] = False
                st.rerun()

# --- 実行ロジック (st.status) ---
if st.session_state.get(RUN_KEY):
    st.session_state[RUN_KEY] = False
    
    with st.status("AIキーワード抽出による再マッチングを実行中...", expanded=True) as status:
        try:
            # ★★★ 新しい専用関数を呼び出す ★★★
            response_generator = be.rematch_job_with_keyword_filtering(
                job_id=selected_id,
                target_rank=st.session_state[RANK_KEY],
                target_count=st.session_state[COUNT_KEY]
            )
            
            final_message = ""
            for log_message in response_generator:
                st.markdown(log_message, unsafe_allow_html=True)
                final_message = log_message

            if "✅" in final_message or "🎉" in final_message or "ℹ️" in final_message:
                status.update(label="処理が正常に完了しました！", state="complete", expanded=False)
                st.success("再マッチングが完了しました。ページをリロードして結果を確認してください。")
                st.balloons()
            else:
                status.update(label="処理が完了しませんでした。", state="error", expanded=True)
                st.error("処理が完了しませんでした。上記のログを確認してください。")

        except Exception as e:
            st.error(f"UI処理中に予期せぬエラーが発生しました: {e}")
            status.update(label="UIエラー", state="error", expanded=True)

    if st.button("ページを更新して結果を確認"):
        st.rerun()



st.divider()


if st.button("一覧に戻る"):
    if 'selected_job_id' in st.session_state: del st.session_state['selected_job_id']
    st.switch_page("pages/4_案件管理.py")

ui.display_footer()