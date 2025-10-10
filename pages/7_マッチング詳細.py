import streamlit as st
import sys
import os
import json
import html

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
summary_data = be.get_match_summary_with_llm(job_data['document'], engineer_data['document'])

with st.container(border=True):
    col1, col2, col3 = st.columns([1.5, 3, 3])
    with col1:
        grade = None
        if summary_data and summary_data.get('summary'):
            grade = summary_data.get('summary')
            grade_to_save = summary_data.get('summary')

            # DBに保存されているgradeとLLMが生成したgradeが異なる場合のみ更新
            if match_data['grade'] != grade_to_save:
                be.save_match_grade(selected_match_id, grade_to_save)
                match_data['grade'] = grade_to_save # dict形式なので直接更新可能

            evaluation_html = get_evaluation_html(grade)
            st.markdown(evaluation_html, unsafe_allow_html=True)
        else:
            st.warning("AI評価のSummaryが取得できませんでした。")
        
        # ▼▼▼【ここをコメントアウトして類似度を非表示にします】▼▼▼
        # st.metric("類似度", f"{float(match_data['score']):.1f}%")
        # ▲▲▲【類似度非表示の修正はここまで】▲▲▲

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


# --- AIによる提案メール案生成セクション ---
st.header("✉️ AIによる提案メール案")
with st.spinner("AIが技術者のセールスポイントを盛り込んだ提案メールを作成中です..."):
    project_name_for_prompt = job_data['project_name'] or f"ID:{job_data['id']}の案件"
    engineer_name_for_prompt = engineer_data['name'] or f"ID:{engineer_data['id']}の技術者"

    proposal_text = be.generate_proposal_reply_with_llm(
        job_data['document'],
        engineer_data['document'],
        engineer_name_for_prompt,
        project_name_for_prompt
    )

with st.container(border=True):
    st.info("以下の文面はAIによって生成されたものです。提案前に必ず内容を確認・修正してください。")
    st.text_area(
        label="生成されたメール文面",
        value=proposal_text,
        height=500,
        label_visibility="collapsed"
    )
    if st.button("文面をクリップボードにコピー", use_container_width=True):
        st.toast("コピーしました！")
    st.code(proposal_text, language="text")
    st.caption("▲ 上のボックス内をクリックすると全文をコピーできます。")

st.divider()


# --- 元情報（タブ）セクション ---
st.header("📄 元の情報ソース")
tab1, tab2 = st.tabs(["案件の元情報", "技術者の元情報"])
with tab1:
    st.text_area("案件ソース", value=get_source_text(job_data['source_data_json']), height=400, disabled=True, label_visibility="collapsed")
with tab2:
    st.text_area("技術者ソース", value=get_source_text(engineer_data['source_data_json']), height=400, disabled=True, label_visibility="collapsed")

st.divider()

# --- 操作メニュー ---
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
    st.switch_page("1_ダッシュボード.py")

