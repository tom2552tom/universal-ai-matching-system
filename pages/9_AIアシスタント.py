import streamlit as st
import backend as be
import ui_components as ui

# --- ページ設定など ---
st.set_page_config(page_title="オンデマンド・マッチング", layout="wide")
# 認証が必要な場合はコメントを外す
# if not ui.check_password(): st.stop()
ui.apply_global_styles()

st.title("🤖 AIオンデマンド・マッチング")
st.info("下のテキストエリアに案件情報または技術者情報を貼り付け、条件を指定して検索を実行してください。")

# --- UIセクション (変更なし) ---
with st.form("ondemand_matching_form"):
    input_text = st.text_area(
        "ここに案件情報または技術者情報を貼り付け",
        height=400,
        placeholder="【案件】\n1.案件名：...\n\nまたは\n\n【技術者】\n氏名：...\nスキル：..."
    )
    st.divider()
    st.markdown("##### 検索条件")
    col1, col2 = st.columns(2)
    with col1:
        target_rank = st.selectbox("最低ランク", ['S', 'A', 'B', 'C'], index=1)
    with col2:
        target_count = st.number_input("最大表示件数", 1, 10, 5)
    submitted = st.form_submit_button("この条件で候補者を探す", type="primary", use_container_width=True)


# ▼▼▼【ここからが全面的に修正する処理ロジック】▼▼▼
# --- 処理ロジック ---
if submitted:
    if not input_text.strip():
        st.error("案件情報または技術者情報を入力してください。")
    else:
        results_container = st.container()
        with results_container:
            with st.expander("処理ログと結果", expanded=True):
                
                response_generator = be.find_candidates_on_demand(
                    input_text=input_text,
                    target_rank=target_rank,
                    target_count=target_count
                )
                

                # ▼▼▼【ここからが新しいログ表示ロジック】▼▼▼
                
                # 履歴として残すログを表示する場所
                permanent_log_placeholder = st.empty()
                # 上書きされる一時的なログを表示する場所
                temp_log_placeholder = st.empty()

                permanent_logs = []
                
                try:
                    for chunk in response_generator:
                        chunk_str = str(chunk)

                        # ヒットログか、ステップ区切りか、最終結果のヘッダーかを判断
                        if "✅ ヒット！" in chunk_str or "ステップ" in chunk_str or "最終候補者リスト" in chunk_str or "---" in chunk_str:
                            # 履歴として残すログ
                            permanent_logs.append(chunk_str)
                            permanent_log_placeholder.markdown("".join(permanent_logs))
                            # 一時ログはクリア
                            temp_log_placeholder.empty()
                        
                        elif "評価中..." in chunk_str or "ｽｷｯﾌﾟ" in chunk_str:
                            # 上書きする一時的なログ
                            # 評価中のログとスキップログはここに表示される
                            temp_log_placeholder.info(chunk_str.strip())
                        
                        else:
                            # 上記以外のログ（エラーなど）は履歴に残す
                            permanent_logs.append(chunk_str)
                            permanent_log_placeholder.markdown("".join(permanent_logs))

                except Exception as e:
                    st.error("処理中に予期せぬエラーが発生しました。")
                    st.exception(e)
                
                finally:
                    # 処理完了後、一時ログを完全にクリア
                    temp_log_placeholder.empty()

                # ▲▲▲【ログ表示ロジックここまで】▲▲▲

# フッター表示
ui.display_footer()
