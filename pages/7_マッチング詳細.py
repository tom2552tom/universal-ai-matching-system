import streamlit as st
import sys
import os
import json
import html
import time # timeモジュールを追加
from backend import get_matching_result_details, save_match_feedback, get_all_users, hide_match, update_match_status, save_proposal_text, generate_proposal_reply_with_llm, save_internal_memo, delete_match # ← delete_match を追加
import ui_components as ui



# プロジェクトルートをパスに追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)

import backend as be

st.set_page_config(page_title="マッチング詳細", layout="wide")

st.title("マッチング詳細")

# --- マッチングIDの取得ロジック ---
# 1. URLパラメータから 'result_id' を取得
selected_match_id_from_url = st.query_params.get("result_id")

# 2. セッションステートから 'selected_match_id' を取得
selected_match_id_from_session = st.session_state.get('selected_match_id', None)

# 優先順位: URLパラメータ > セッションステート
if selected_match_id_from_url:
    try:
        selected_match_id = int(selected_match_id_from_url)
        # URLからIDが渡された場合、セッションステートも更新しておく
        st.session_state['selected_match_id'] = selected_match_id
    except ValueError:
        st.error("URLパラメータの 'result_id' が無効です。数値で指定してください。")
        selected_match_id = None
elif selected_match_id_from_session:
    selected_match_id = selected_match_id_from_session
else:
    selected_match_id = None


if selected_match_id is None:
    st.error("表示するマッチング結果IDが指定されていません。")
    st.info("ダッシュボードから詳細を見たいマッチングを選択するか、URLの末尾に `?result_id=XXX` (XXXはマッチング結果のID) を追加してアクセスしてください。")
    if st.button("ダッシュボードに戻る"): st.switch_page("1_ダッシュボード.py")
    st.stop()


# --- データ取得 ---
details = be.get_matching_result_details(selected_match_id)

if not details:
    st.error(f"指定されたマッチング情報 (ID: {selected_match_id}) が見つかりませんでした。データベースを確認してください。")
    st.stop()

match_data = details["match_result"]
job_data = details["job_data"]
engineer_data = details["engineer_data"]

if not job_data or not engineer_data:
    st.error("案件または技術者の情報が見つかりませんでした。データベースを確認してください。"); st.stop()


# --- ヘルパー関数 ---
def get_evaluation_html(grade):
    """
    評価（A-E）に基づいて色とスタイルが適用されたHTMLを生成します。
    """
    if not grade:
        return ""

    color_map = {
        'S': '#00b894', # Sを追加 (Emerald Green)
        'A': '#28a745',  # Green (Success)
        'B': '#17a2b8',  # Cyan (Info)
        'C': '#ffc107',  # Yellow (Warning)
        'D': '#fd7e14',  # Orange
        'E': '#dc3545',  # Red (Danger)
    }
    color = color_map.get(grade.upper(), '#6c757d')
    
    style = f"""
        color: {color};
        font-size: 3em;
        font-weight: bold;
        text-align: center;
        line-height: 1.1;
        margin-bottom: -10px;
    """
    
    html_code = f"""
    <div style='{style}'>
        {grade.upper()}
    </div>
    <div style='text-align: center; font-weight: bold; color: #888;'>
        判定
    </div>
    """
    return html_code

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
# ▼▼▼【画面レイアウト】▼▼▼
# ==================================================================


# --- 進捗ステータス管理セクション ---
st.header("📈 進捗ステータス")

# SEC事業で想定されるステータスオプション
status_options = [
    "新規", "提案準備中", "提案中", "クライアント面談", "結果待ち", 
    "採用", "見送り（自社都合）", "見送り（クライアント都合）", "見送り（技術者都合）", "クローズ"
]

current_status = match_data.get('status', '新規') # DBにstatusがない場合も考慮

with st.container(border=True):
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("現在のステータス", current_status)
    with col2:
        try:
            default_index = status_options.index(current_status)
        except ValueError:
            default_index = 0 # リストにない場合は先頭を選択
        
        selected_status = st.selectbox(
            "ステータスを変更",
            options=status_options,
            index=default_index,
            key=f"status_selector_{selected_match_id}"
        )
        if st.button("ステータスを更新", use_container_width=True):
            if be.update_match_status(selected_match_id, selected_status):
                st.success(f"ステータスを「{selected_status}」に更新しました。")
                time.sleep(1) # 1秒待機
                st.rerun()
            else:
                st.error("ステータスの更新に失敗しました。")
st.divider()



# --- AI要約比較セクション ---
st.header("🤖 AIによる案件・技術者の要約")
col_job, col_eng = st.columns(2)

def display_summary(title, document_text, assignee, item_id, item_type, page_link, session_key):
    doc_parts = document_text.split('\n---\n', 1)
    meta_info, main_doc = (doc_parts[0], doc_parts[1]) if len(doc_parts) > 1 else ("", document_text)
    
    with st.container(border=True):
        st.subheader(title)
        if assignee: st.caption(f"**担当:** {assignee}")
        if meta_info: st.caption(meta_info.replace("][", " | ").strip("[]"))
        st.markdown(main_doc)
        
        if st.button("詳細を見る", key=f"nav_{item_type}_{item_id}", use_container_width=True):
            st.session_state[session_key] = item_id
            st.switch_page(page_link)

with col_job:
    project_name = job_data['project_name'] or f"案件 (ID: {job_data['id']})"
    display_summary(
        title=f"💼 {project_name}",
        document_text=job_data['document'],
        assignee=job_data['assignee_name'],
        item_id=job_data['id'],
        item_type='job',
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
        item_type='engineer',
        page_link="pages/5_技術者詳細.py",
        session_key='selected_engineer_id'
    )
st.divider()


# --- AIマッチング評価セクション ---
st.header("📊 AIマッチング評価")
# LLMを毎回呼び出すのはパフォーマンスに影響するため、可能であればDBに保存されたgradeを使用
# ただし、positive_pointsやconcern_pointsはDBに保存されていないため、再生成が必要
# ここでは、常にLLMを呼び出して最新の分析結果を表示するロジックを維持

# ▼▼▼【ここから修正】▼▼▼
# DBに評価結果が保存されているかチェック
has_existing_evaluation = (
    match_data.get('grade') and 
    match_data.get('positive_points') and 
    match_data.get('concern_points')
)

summary_data = {}

if has_existing_evaluation:
    # DBに評価結果が存在する場合、そのデータを表示する
    #st.info("ℹ️ データベースに保存されているAI評価結果を表示しています。")
    summary_data['summary'] = match_data['grade']
    try:
        # JSON文字列をリストに変換
        summary_data['positive_points'] = json.loads(match_data['positive_points'])
        summary_data['concern_points'] = json.loads(match_data['concern_points'])
    except (json.JSONDecodeError, TypeError):
        # JSONのパースに失敗した場合は空リストとして扱う
        st.warning("保存されている評価根拠のフォーマットが正しくありません。")
        summary_data['positive_points'] = []
        summary_data['concern_points'] = []
else:
    # DBに評価結果が存在しない場合のみ、AIによる再評価を実行
    st.info("ℹ️ データベースに評価結果がなかったため、AIによる評価を実行します。")
    with st.spinner("AIがマッチング評価を実行中..."):
        ai_result = be.get_match_summary_with_llm(job_data['document'], engineer_data['document'])
    
    if ai_result and ai_result.get('summary'):
        summary_data = ai_result
        # 評価結果をDBに保存・更新する
        if be.update_match_evaluation(selected_match_id, summary_data):
            st.success("AI評価結果をデータベースに保存しました。")
            # ページをリロードして、次回からはDBのデータを表示するようにする
            time.sleep(1)
            st.rerun()
        else:
            st.error("AI評価結果のデータベースへの保存に失敗しました。")
    else:
        st.error("AIによる評価の取得に失敗しました。")

# --- 評価結果の表示 ---
with st.container(border=True):
    col1, col2, col3 = st.columns([1.5, 3, 3])
    with col1:
        grade = summary_data.get('summary')
        if grade:
            evaluation_html = get_evaluation_html(grade)
            st.markdown(evaluation_html, unsafe_allow_html=True)
        else:
            st.warning("評価がありません。")

    with col2:
        st.markdown("###### ✅ ポジティブな点")
        positive_points = summary_data.get('positive_points', [])
        if positive_points:
            for point in positive_points: st.markdown(f"- {point}")
        else: st.caption("特筆すべき点はありません。")
    with col3:
        st.markdown("###### ⚠️ 懸念点・確認事項")
        concern_points = summary_data.get('concern_points', [])
        if concern_points:
            for point in concern_points: st.markdown(f"- {point}")
        else: st.caption("特に懸念はありません。")
# ▲▲▲【修正ここまで】▲▲▲

st.divider()




# --- AIによる提案メール案生成セクション ---
st.header("✉️ AIによる提案メール案")


# DBから保存済みの提案テキストを取得
proposal_text = match_data.get('proposal_text')

# 「再作成」ボタンを配置
regenerate_clicked = st.button("🔄 内容を再作成する", key="regenerate_proposal")


# テキストがDBにない、または再作成ボタンが押された場合にAIで生成
if not proposal_text or regenerate_clicked:
    if regenerate_clicked:
        st.info("AIが提案内容を再作成しています...")
    
    with st.spinner("AIが技術者のセールスポイントを盛り込んだ提案メールを作成中です..."):
        project_name_for_prompt = job_data['project_name'] or f"ID:{job_data['id']}の案件"
        engineer_name_for_prompt = engineer_data['name'] or f"ID:{engineer_data['id']}の技術者"

        new_proposal_text = be.generate_proposal_reply_with_llm(
            job_data['document'], engineer_data['document'], engineer_name_for_prompt, project_name_for_prompt
        )
        
        if new_proposal_text and "エラーが発生しました" not in new_proposal_text:
            if be.save_proposal_text(selected_match_id, new_proposal_text):
                proposal_text = new_proposal_text # 表示用に変数を更新
                if regenerate_clicked:
                    st.success("提案メールの再作成が完了しました。")
                    st.rerun()
            else:
                st.error("生成されたテキストのデータベースへの保存に失敗しました。")
                proposal_text = "DB保存エラー"
        else:
            st.error("提案メールの生成に失敗しました。")
            proposal_text = new_proposal_text

# テキスト表示用のコンテナ
with st.container(border=True):
    if proposal_text:
        st.info("以下の文面はAIによって生成されたものです。提案前に必ず内容を確認・修正してください。")
        st.text_area("生成されたメール文面", value=proposal_text, height=500, label_visibility="collapsed")
       # st.code(proposal_text, language="text")
        st.caption("▲ 上のボックス内をクリックすると全文をコピーできます。")
    else:
        st.warning("提案メールのテキストがまだ生成されていません。")

st.divider()





# --- 元情報（タブ）セクション ---
st.header("📄 元の情報ソース")
tab1, tab2 = st.tabs(["案件の元情報", "技術者の元情報"])
with tab1:
    st.text_area("案件ソース", value=get_source_text(job_data['source_data_json']), height=400, disabled=True, label_visibility="collapsed")
with tab2:
    st.text_area("技術者ソース", value=get_source_text(engineer_data['source_data_json']), height=400, disabled=True, label_visibility="collapsed")

st.divider()



# --- 社内共有メモセクション ---
st.header("📝 社内共有メモ")
with st.container(border=True):
    # DBから現在のメモを取得
    current_memo = match_data.get('internal_memo', '')

    # メモ入力エリア
    new_memo = st.text_area(
        "このマッチングに関する経緯や注意事項などを記録します（このメモは社内でのみ共有されます）。",
        value=current_memo,
        height=200,
        key=f"internal_memo_{selected_match_id}"
    )

    # 保存ボタン
    if st.button("メモを保存する", key=f"save_memo_{selected_match_id}"):
        if be.save_internal_memo(selected_match_id, new_memo):
            st.success("メモを保存しました。")
            # 変更を即時反映させるために1秒待ってからリロード
            time.sleep(1)
            st.rerun()
        else:
            st.error("メモの保存に失敗しました。")

st.divider()

# ... (既存のAI要約比較セクションなど) ...


# --- 担当者フィードバック機能 ---
with st.expander("担当者フィードバック", expanded=True):
    # 現在のフィードバック情報を表示
    if details["match_result"].get("feedback_at"):
        feedback_time = details["match_result"]["feedback_at"].strftime('%Y-%m-%d %H:%M')
        # backendで取得した担当者名を表示
        feedback_user = details["match_result"].get("feedback_username", "不明") 
        st.info(f"最終フィードバック: {feedback_time} by **{feedback_user}**")
        st.write(f"評価: **{details['match_result']['feedback_status']}**")
        st.caption("コメント:")
        st.text(details['match_result']['feedback_comment'])
        st.write("---")

    st.subheader("フィードバックを登録・更新")
    
    # 担当者一覧を取得
    all_users = get_all_users()
    user_dict = {user['id']: user['username'] for user in all_users}
    
    # UIコンポーネント
    feedback_user_id = st.selectbox(
        "フィードバック担当者", 
        options=list(user_dict.keys()), 
        format_func=lambda x: user_dict[x],
        # ▼▼▼【ここから下の 'result_id' をすべて 'selected_match_id' に修正】▼▼▼
        key=f"feedback_user_{selected_match_id}"
    )
    
    feedback_status = st.radio(
        "このマッチングの評価",
        options=["👍 良いマッチング", "👎 改善の余地あり"],
        horizontal=True,
        key=f"feedback_status_{selected_match_id}"
    )
    
    feedback_comment = st.text_area(
        "評価の理由（なぜ良い/悪いと思いましたか？ 具体的なスキル名など）",
        key=f"feedback_comment_{selected_match_id}"
    )
    
    if st.button("フィードバックを送信", key=f"submit_feedback_{selected_match_id}"):
        if not feedback_comment.strip():
            st.warning("評価の理由を記入してください。")
        else:
            # backendの関数を呼び出してDBに保存
            success = save_match_feedback(
                match_id=selected_match_id, # この画面で表示しているマッチングID
                feedback_status=feedback_status,
                feedback_comment=feedback_comment,
                user_id=feedback_user_id
            )
            
            if success:
                st.success("フィードバックを保存しました。ありがとうございます！")
                st.rerun() # 画面を再読み込みして最新の情報を表示
            else:
                st.error("フィードバックの保存に失敗しました。")

st.divider()


# --- 操作メニュー ---
with st.expander("マッチングの操作"):
    is_hidden = match_data.get('is_hidden') == 1
    if not is_hidden:
        if st.button("🙈 このマッチング結果を非表示にする", use_container_width=True, type="secondary"):
            if be.hide_match(selected_match_id):
                st.success("このマッチングを非表示にしました。"); st.rerun()
            else:
                st.error("更新に失敗しました。")
    else:
        st.info("このマッチングは非表示に設定されています。")

    st.markdown("---")

    # ▼▼▼【ここからが削除機能の追加部分です】▼▼▼
    delete_confirmation_key = f"confirm_delete_match_{selected_match_id}"

    if delete_confirmation_key not in st.session_state:
        st.session_state[delete_confirmation_key] = False

    if st.button("🚨 このマッチングを完全に削除する", type="secondary", use_container_width=True, key=f"delete_match_main_btn_{selected_match_id}"):
        # 削除確認UIの表示/非表示を切り替える
        st.session_state[delete_confirmation_key] = not st.session_state[delete_confirmation_key]
        st.rerun()

    if st.session_state[delete_confirmation_key]:
        st.warning("**本当にこのマッチングを削除しますか？**\n\nこの操作は取り消せません。")
        
        col_check, col_btn = st.columns([3, 1])
        with col_check:
            confirm_check = st.checkbox("はい、削除を承認します。", key=f"delete_match_confirm_checkbox_{selected_match_id}")
        with col_btn:
            if st.button("削除実行", disabled=not confirm_check, use_container_width=True, key=f"delete_match_execute_btn_{selected_match_id}"):
                # backendのdelete_match関数を呼び出す
                if delete_match(selected_match_id):
                    st.success(f"マッチング結果 (ID: {selected_match_id}) を完全に削除しました。ダッシュボードに戻ります。")
                    time.sleep(2)
                    # セッションステートをクリーンアップ
                    if 'selected_match_id' in st.session_state:
                        del st.session_state['selected_match_id']
                    if delete_confirmation_key in st.session_state:
                        del st.session_state[delete_confirmation_key]
                    st.switch_page("1_ダッシュボード.py")
                else:
                    st.error("マッチング結果の削除に失敗しました。")
    # ▲▲▲【削除機能の追加ここまで】▲▲▲

st.divider()

if st.button("ダッシュボードに戻る"):
    st.switch_page("1_ダッシュボード.py")

ui.display_footer()