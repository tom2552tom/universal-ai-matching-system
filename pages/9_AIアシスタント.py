# 9_AIアシスタント.py (最終修正版)

import streamlit as st
import backend as be
import ui_components as ui
import time

# --- ページ設定 ---
st.set_page_config(page_title="AIオンデマンド・マッチング", layout="wide")
# ui.check_password()
ui.apply_global_styles()

st.title("🤖 AIオンデマンド・マッチング")
st.markdown("---")

# --- session_state の初期化 ---
# このページの実行で初めてアクセスされたときに一度だけ実行される
if "ondemand_initialized" not in st.session_state:
    st.session_state.ondemand_initialized = True
    st.session_state.ondemand_step = "initial"
    st.session_state.all_candidate_ids = []
    st.session_state.source_doc = ""
    st.session_state.search_target_type = ""
    st.session_state.eval_index = 0
    st.session_state.permanent_logs = []
    st.session_state.is_evaluating = False
    st.session_state.hit_candidates = []
    st.session_state.input_text_from_form = ""
    st.session_state.target_rank_from_form = "A"

# --- 関数定義 ---
def reset_state():
    """検索状態をリセットし、ページを再実行する"""
    st.session_state.ondemand_initialized = False # これにより次回アクセス時に全初期化が走る
    st.rerun()

# --- UIセクション ---
st.subheader("STEP 1: 検索条件の入力")
col_form, col_logs = st.columns([1, 1])

with col_form:
    # ★★★ st.form のロジックをシンプル化 ★★★
    with st.form("ondemand_matching_form"):
        input_text = st.text_area(
            "ここに案件情報または技術者情報を貼り付け",
            height=300,
            placeholder="【案件】...\nまたは\n【技術者】...",
        )
        target_rank = st.selectbox(
            "結果として表示する最低ランク",
            ['S', 'A', 'B', 'C'],
            index=1,
        )
        submitted = st.form_submit_button("候補者の検索を開始", type="primary", use_container_width=True)
    
    # フォームが送信されたら、その値をセッションステートに保存し、初回検索フラグを立てる
    if submitted:
        st.session_state.input_text_from_form = input_text
        st.session_state.target_rank_from_form = target_rank
        st.session_state.run_initial_search = True
        st.rerun() # フォームの値を確定させ、初回検索ロジックをキックするために再実行

with col_logs:
    st.subheader("処理ログ")
    log_container = st.container(height=400)
    with log_container:
        permanent_log_placeholder = st.empty()
        if st.session_state.permanent_logs:
            permanent_log_placeholder.markdown("\n\n".join(st.session_state.permanent_logs))
        temp_log_placeholder = st.empty()

st.subheader("STEP 2: 逐次評価")
control_container = st.container()

# --- メインロジック ---

# --- 初回検索の実行 ---
if st.session_state.get("run_initial_search"):
    st.session_state.run_initial_search = False
    # 初回検索の前に、ヒットリストとログのみリセット
    st.session_state.hit_candidates = []
    st.session_state.permanent_logs = []
    st.session_state.eval_index = 0
    
    st.session_state.ondemand_step = "evaluating"
    
    with log_container, st.spinner("入力情報を解析し、候補をリストアップしています..."):
        initial_data = be.get_all_candidate_ids_and_source_doc(st.session_state.input_text_from_form)
        
        if initial_data and initial_data.get("all_candidate_ids"):
            st.session_state.all_candidate_ids = initial_data["all_candidate_ids"]
            st.session_state.source_doc = initial_data["source_doc"]
            st.session_state.search_target_type = initial_data["search_target_type"]
            st.session_state.permanent_logs = initial_data.get("logs", [])
            st.session_state.permanent_logs.append(f"**合計 {len(st.session_state.all_candidate_ids)} 件の候補が見つかりました。最初の候補の評価を開始します。**")
            st.session_state.is_evaluating = True
        else:
            st.session_state.permanent_logs = initial_data.get("logs", ["エラーが発生しました。"])
            st.session_state.ondemand_step = "finished"
    st.rerun()

# --- 評価実行ロジック ---
if st.session_state.get("is_evaluating"):
    st.session_state.is_evaluating = False
    if st.session_state.eval_index < len(st.session_state.all_candidate_ids):
        candidate_id_to_eval = st.session_state.all_candidate_ids[st.session_state.eval_index]
        
        should_pause = False
        error_occurred = False
        
        try:
            temp_log_placeholder.empty()
            response_generator = be.evaluate_next_candidates(
                candidate_ids=[candidate_id_to_eval],
                source_doc=st.session_state.source_doc,
                search_target_type=st.session_state.search_target_type,
                target_rank=st.session_state.target_rank_from_form # フォームから取得した値を使用
            )
            
            for chunk in response_generator:
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type")
                    if chunk_type == "eval_progress":
                        temp_log_placeholder.info(chunk.get("message"))
                    elif chunk_type == "llm_start":
                        temp_log_placeholder.info(chunk.get("message"))
                    elif chunk_type == "pause":
                        should_pause = True
                    elif chunk_type == "skip_log":
                        # ★★★ スキップログは一時ログに表示 ★★★
                        temp_log_placeholder.warning(chunk.get("message"))
                    elif chunk_type == "hit_candidate":
                        st.session_state.hit_candidates.append(chunk.get("data"))
                        hit_data = chunk.get("data", {})
                        st.session_state.permanent_logs.append(f"**✅ ヒット！** 候補「{hit_data.get('name')}」 (ランク: {hit_data.get('grade')})")
        except Exception as e:
            error_occurred = True
            error_message = f"❌ 評価処理中にエラーが発生しました (候補ID: {candidate_id_to_eval})。この候補をスキップして次に進みます。"
            st.session_state.permanent_logs.append(f"\n---\n{error_message}\n```\n{e}\n```")
        
        finally:
            st.session_state.eval_index += 1
            if error_occurred:
                should_pause = False
            if st.session_state.eval_index >= len(st.session_state.all_candidate_ids):
                st.session_state.ondemand_step = "finished"
                if not any("🎉" in log for log in st.session_state.permanent_logs):
                    st.session_state.permanent_logs.append("**🎉 すべての候補者の評価が完了しました。**")
                should_pause = True
            if not should_pause:
                st.session_state.is_evaluating = True
            st.rerun()

# --- ボタン表示制御 ---
with control_container:
    col_next, col_reset = st.columns(2)
    with col_next:
        if st.session_state.get('ondemand_step') == "evaluating" and not st.session_state.get('is_evaluating'):
            st.button(
                f"次の候補を評価 ({st.session_state.get('eval_index', 0)}/{len(st.session_state.get('all_candidate_ids', []))})",
                on_click=lambda: st.session_state.update(is_evaluating=True),
                type="primary",
                use_container_width=True
            )
        else:
            st.button("次の候補を評価", disabled=True, use_container_width=True)
    with col_reset:
        st.button("新しい検索を始める (リセット)", on_click=reset_state, use_container_width=True)

# --- ヒット候補者リストの表示 ---
st.markdown("---")
st.subheader("ヒットした候補者リスト")
if not st.session_state.get('hit_candidates'):
    st.info("まだヒットした候補者はいません。")
else:
    for candidate in reversed(st.session_state.get('hit_candidates', [])):
        title = f"✅ **{candidate.get('name')}** (ID: {candidate.get('id')}) - ランク: **{candidate.get('grade')}**"
        with st.expander(title, expanded=True): # 最初から開いておく
            link = f"/{candidate.get('page_name')}?id={candidate.get('id')}"
            st.markdown(f"詳細ページへ: [{candidate.get('name')} (ID: {candidate.get('id')})]({link})")
            
            st.markdown("**ポジティブな点:**")
            pos_points = candidate.get('positive_points', [])
            if pos_points:
                for point in pos_points:
                    st.markdown(f"- {point}")
            else:
                st.write("N/A")
            st.markdown("**懸念点:**")
            con_points = candidate.get('concern_points', [])
            if con_points:
                for point in con_points:
                    st.markdown(f"- {point}")
            else:
                st.write("N/A")

# --- フッター ---
ui.display_footer()
