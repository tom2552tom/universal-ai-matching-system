import streamlit as st
import backend as be
import json
import html
import base64
import time
from datetime import datetime
import ui_components as ui

# backend から get_evaluation_html をインポート
try:
    from backend import get_evaluation_html
except ImportError:
    # インポート失敗時のフォールバック
    def get_evaluation_html(grade, font_size='2em'):
        if not grade: return ""
        return f"<p style='font-size:{font_size}; text-align:center;'>{grade}</p>"

ui.apply_global_styles()
st.set_page_config(page_title="技術者詳細", layout="wide")



# ▼▼▼【ここからが修正箇所】▼▼▼

# --- ID取得ロジックの修正 ---
# 1. URLのクエリパラメータからIDを取得
query_id = st.query_params.get("id")

# 2. session_state からIDを取得
session_id = st.session_state.get('selected_engineer_id')

selected_id = None
if query_id:
    # URLにIDがあれば最優先で採用
    try:
        selected_id = int(query_id)
        # ページ内での状態維持のため、session_stateにもIDをセットしておく
        st.session_state['selected_engineer_id'] = selected_id
    except (ValueError, TypeError):
        st.error("URLのIDが不正な形式です。")
        st.stop()
elif session_id:
    # URLにIDがなく、session_stateにあればそれを使用
    selected_id = session_id

# --- IDが取得できなかった場合の処理 ---
if selected_id is None:
    st.error("技術者が選択されていません。技術者管理ページまたはAIアシスタントから技術者を選択してください。")
    # 戻るボタンのリンク先も実際のファイル名に合わせる
    if st.button("技術者管理に戻る"):
        st.switch_page("pages/3_技術者管理.py") 
    st.stop()


# --- DBから全データを取得 ---
conn = be.get_db_connection()
engineer_data = None
matched_jobs = []
try:
    with conn.cursor() as cursor:
        engineer_query = """
        SELECT 
            e.id, e.name, e.document, e.source_data_json, e.assigned_user_id, e.is_hidden,
            u.username as assigned_username
        FROM engineers e
        LEFT JOIN users u ON e.assigned_user_id = u.id
        WHERE e.id = %s
        """
        cursor.execute(engineer_query, (selected_id,))
        engineer_data = cursor.fetchone()

        if engineer_data:
            matched_jobs_query = """
                SELECT 
                    j.id as job_id, j.project_name, j.document, 
                    r.score, r.id as match_id, r.grade
                FROM matching_results r
                JOIN jobs j ON r.job_id = j.id
                WHERE r.engineer_id = %s 
                  AND j.is_hidden = 0
                  AND r.is_hidden = 0
                ORDER BY r.score DESC
            """
            cursor.execute(matched_jobs_query, (selected_id,))
            matched_jobs = cursor.fetchall()
finally:
    if conn:
        conn.close()

if engineer_data:
    # --- タイトル表示 ---
    is_currently_hidden = engineer_data['is_hidden'] == 1
    engineer_name = engineer_data['name'] or f"技術者 (ID: {selected_id})"
    
    title_display = f"👨‍💻 {engineer_name}"
    if is_currently_hidden:
        title_display += " `非表示`"
    
    st.title(title_display)
    st.caption(f"ID: {selected_id}")
    st.divider()

    # --- 基本情報セクション ---
    st.subheader("👤 基本情報")
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            new_engineer_name = st.text_input("技術者氏名", value=engineer_data['name'] or "")
            if st.button("氏名を更新", use_container_width=True):
                if be.update_engineer_name(selected_id, new_engineer_name):
                    st.success("氏名を更新しました。")
                    time.sleep(1); st.rerun()
                else:
                    st.error("氏名の更新に失敗しました。")
        
        with col2:
            all_users = be.get_all_users()
            user_options = {"未割り当て": None, **{user['username']: user['id'] for user in all_users}}
            current_user_id = engineer_data['assigned_user_id']
            id_to_username = {v: k for k, v in user_options.items()}
            current_username = id_to_username.get(current_user_id, "未割り当て")
            
            option_names = list(user_options.keys())
            default_index = option_names.index(current_username)
            selected_username = st.selectbox("担当者を変更/割り当て", options=option_names, index=default_index, key=f"eng_user_assign_{selected_id}")
            if st.button("担当者を更新", use_container_width=True, key="assign_user_btn"):
                selected_user_id = user_options[selected_username]
                if be.assign_user_to_engineer(selected_id, selected_user_id):
                    st.success(f"担当者を「{selected_username}」に更新しました。")
                    time.sleep(1); st.rerun()
                else: 
                    st.error("担当者の更新に失敗しました。")
    st.divider()

    # --- 技術者の操作（表示/非表示/削除）セクション ---
    with st.expander("技術者の操作", expanded=False):
        if is_currently_hidden:
            if st.button("✅ この技術者を再表示する", use_container_width=True):
                if be.set_engineer_visibility(selected_id, 0): st.success("技術者を再表示しました。"); st.rerun()
                else: st.error("更新に失敗しました。")
        else:
            if st.button("🙈 この技術者を非表示にする (アーカイブ)", type="secondary", use_container_width=True):
                if be.set_engineer_visibility(selected_id, 1): st.success("技術者を非表示にしました。"); st.rerun()
                else: st.error("更新に失敗しました。")
        
        st.markdown("---")
        
        delete_confirmation_key = f"confirm_delete_engineer_{selected_id}"

        if delete_confirmation_key not in st.session_state:
            st.session_state[delete_confirmation_key] = False

        if st.button("🚨 この技術者を完全に削除する", type="secondary", use_container_width=True, key=f"delete_eng_main_btn_{selected_id}"):
            st.session_state[delete_confirmation_key] = not st.session_state[delete_confirmation_key]

        if st.session_state[delete_confirmation_key]:
            st.warning("**本当にこの技術者を削除しますか？**\n\nこの操作は取り消せません。関連するマッチング結果もすべて削除されます。")
            
            col_check, col_btn = st.columns([3,1])
            with col_check:
                confirm_check = st.checkbox("はい、削除を承認します。", key=f"delete_eng_confirm_checkbox_{selected_id}")
            with col_btn:
                if st.button("削除実行", disabled=not confirm_check, use_container_width=True, key=f"delete_eng_execute_btn_{selected_id}"):
                    if be.delete_engineer(selected_id):
                        st.success(f"技術者 (ID: {selected_id}) を完全に削除しました。技術者管理ページに戻ります。")
                        time.sleep(2)
                        del st.session_state['selected_engineer_id']
                        if delete_confirmation_key in st.session_state:
                            del st.session_state[delete_confirmation_key]
                        st.switch_page("pages/3_技術者管理.py")
                    else:
                        st.error("技術者の削除に失敗しました。")
    st.divider()

    # --- AIによる要約情報の表示 ---
    st.header("🤖 AIによる要約情報")

    # ▼▼▼【ここからが修正箇所です】▼▼▼
    doc_parts = engineer_data['document'].split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", engineer_data['document'])

    # メタ情報を枠で囲んで表示
    if meta_info:
        with st.container(border=True):
            st.markdown("**抽出されたメタ情報**")
            # 各メタ情報を整形して表示
            # 例: "[国籍: 日本] [稼働可能日: 即日]" -> "国籍: 日本 | 稼働可能日: 即日"
            formatted_meta = meta_info.replace("][", " | ").strip("[]")
            st.caption(formatted_meta)

    # AIによる要約文を枠で囲んで表示
    with st.container(border=True):
        st.markdown("**AIによる要約文**")
        st.write(main_doc)
    # ▲▲▲【修正ここまで】▲▲▲



    # --- 元の情報の表示 ---
    st.header("📄 元の情報ソース（編集可能）")
    source_json_str = engineer_data.get('source_data_json')
    
    if source_json_str:
        try:
            source_data = json.loads(source_json_str)

            # ▼▼▼ 変更点: 受信元情報をこのセクションに移動 ▼▼▼
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
                    st.markdown("**受信日時**")
                    st.write(formatted_date)
                with col2:
                    st.markdown("**差出人**")
                    st.write(from_address)
            # ▲▲▲ 変更点 ここまで ▲▲▲

            st.subheader("📝 ソーステキスト")
            initial_text_parts = [source_data.get("body", "")]
            attachments = source_data.get("attachments", [])
            if attachments:
                for att in attachments:
                    filename = att.get("filename", "名称不明")
                    content = att.get("content", "")
                    if content:
                        initial_text_parts.append(f"\n\n--- 添付ファイル: {filename} ---\n{content}")
            full_source_text = "".join(initial_text_parts)

            st.markdown("メール本文と添付ファイルの内容が統合されています。スキル情報の追加や修正はこちらで行ってください。")
            edited_source_text = st.text_area(
                "情報ソースを編集", value=full_source_text, height=600,
                label_visibility="collapsed", key=f"eng_source_editor_{selected_id}"
            )
            #st.warning("アピールしたいポイントやスキルなどを追加・修正し、「情報ソースを更新する」ボタンを押した後、「AI再評価」を実行することで、新たな案件がマッチする可能性があります。")

            if st.button("情報ソースを更新する", type="primary"):
                source_data['body'] = edited_source_text
                if 'attachments' in source_data:
                    for att in source_data['attachments']:
                        if 'content' in att: att['content'] = ''
                
                new_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
                if be.update_engineer_source_json(selected_id, new_json_str):
                    st.success("情報ソースを更新しました。下の「AI再評価」ボタンを押して、変更をマッチングに反映させてください。")
                    time.sleep(2); st.rerun()
                else:
                    st.error("データベースの更新に失敗しました。")

            st.divider()

            if attachments:
                st.subheader("原本ファイルのダウンロード")
                st.info("この機能は現在実装されていません。")

        except (json.JSONDecodeError, TypeError, ValueError):
            st.error("元のデータの解析に失敗しました。"); st.text(source_json_str)
    else: st.warning("このデータには元のテキストが保存されていません。")
    st.divider()

    # --- マッチング済みの案件一覧 ---
    st.header("🤝 マッチング済みの案件一覧")
    
    if not matched_jobs:
        st.info("この技術者にマッチング済みの案件はありません。")
    else:
        st.write(f"計 {len(matched_jobs)} 件の案件がマッチングしています。")
        for job in matched_jobs:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    project_name = job['project_name'] or f"案件 (ID: {job['job_id']})"
                    st.markdown(f"##### {project_name}")
                    job_doc_parts = job['document'].split('\n---\n', 1)
                    job_main_doc = job_doc_parts[1] if len(job_doc_parts) > 1 else job['document']
                    st.caption(job_main_doc.replace('\n', ' ').replace('\r', '')[:200] + "...")
                with col2:
                    st.markdown(get_evaluation_html(job['grade'], font_size='2em'), unsafe_allow_html=True)
                    if st.button("詳細を見る", key=f"matched_job_detail_{job['match_id']}", use_container_width=True):
                        st.session_state['selected_match_id'] = job['match_id']
                        st.switch_page("pages/7_マッチング詳細.py")
                
else:
    st.error("指定されたIDの技術者情報が見つかりませんでした。")





# pages/5_技術者詳細.py の「AI再評価＋マッチング」セクションをこちらに置き換えてください

st.divider()
st.header("⚙️ AI再評価＋マッチング")
st.info("「情報ソースを更新する」ボタンでスキル情報を変更した場合、このボタンを押すことで、最新の情報ですべての案件とのマッチングを再実行します。")

with st.container(border=True):
    st.markdown("##### マッチング条件設定")
    col1, col2 = st.columns(2)
    with col1:
        target_rank = st.selectbox(
            "最低ランク",
            options=['S', 'A', 'B', 'C'],
            index=2, 
            help="ここで選択したランク以上のマッチングを検索します。（例: Bを選択するとS, A, Bが対象となります）"
        )
    with col2:
        # ▼▼▼【ここを修正】▼▼▼
        target_count = st.number_input(
            "最大ヒット件数(1-10件)", # ラベルを少し変更
            min_value=1,
            max_value=10,
            value=5, 
            help="指定したランク以上のマッチングがこの件数に達した時点で、AIの評価処理を自動的に終了します。処理時間の短縮とコスト削減に繋がります。" # helpテキストを修正
        )
        #st.caption("ヒットさせたい最低件数を指定します。") # ラベルの下に説明を追加
        # ▲▲▲【修正ここまで】▲▲▲

# 各技術者IDに固有のセッションステートキーを定義
re_eval_confirmation_key = f"confirm_re_evaluate_{selected_id}"

if re_eval_confirmation_key not in st.session_state:
    st.session_state[re_eval_confirmation_key] = False

# 確認UIの表示/非表示を切り替えるボタン
if st.button("🤖 AI再評価と再マッチングを実行する", type="primary", use_container_width=True, key=f"re_eval_main_btn_{selected_id}"):
    st.session_state[re_eval_confirmation_key] = not st.session_state[re_eval_confirmation_key]
    st.rerun()

# 確認UIの表示
if st.session_state[re_eval_confirmation_key]:
    with st.container(border=True):
        st.warning(f"**本当に再評価と再マッチングを実行しますか？**\n\nこの技術者に関する既存のマッチング結果は**すべて削除**され、最新の情報で再計算されます。\n\n**実行条件:**\n- **目標ランク:** {target_rank} ランク以上\n- **目標件数:** {target_count} 件")
        
        confirm_check = st.checkbox("はい、すべての既存マッチング結果の削除を承認し、再実行します。", key=f"re_eval_confirm_checkbox_{selected_id}")
        
        col_run, col_cancel, _ = st.columns([1, 1, 3])
        with col_run:
            execute_button_clicked = st.button("再評価実行", disabled=not confirm_check, use_container_width=True, key=f"re_eval_execute_btn_{selected_id}")
        with col_cancel:
            if st.button("キャンセル", use_container_width=True):
                st.session_state[re_eval_confirmation_key] = False
                st.rerun()

        # 「再評価実行」ボタンが押された後の処理
        if execute_button_clicked:
            log_placeholder = st.container()
            with log_placeholder:
                with st.spinner("再評価と再マッチングを実行中..."):
                    # ▼▼▼【backendの関数に新しい引数を渡す】▼▼▼
                    success = be.re_evaluate_and_match_single_engineer(
                        engineer_id=selected_id,
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
    if 'selected_engineer_id' in st.session_state: del st.session_state['selected_engineer_id']
    st.switch_page("pages/3_技術者管理.py")


ui.display_footer()