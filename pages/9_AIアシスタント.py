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
                # プログレスバーを管理するための辞書
                progress_bars = {} 

                permanent_logs = []
                
                try:
                    for chunk in response_generator:
                        
                        # 1. chunkが辞書かどうかをチェック
                        if isinstance(chunk, dict):
                            chunk_type = chunk.get("type")
                            key = chunk.get("key")

                            if chunk_type == "progress_start":
                                progress_bars[key] = st.progress(0, text=chunk.get("text", "..."))
                            
                            elif chunk_type == "progress_update":
                                if key in progress_bars:
                                    progress_bars[key].progress(chunk["value"], text=chunk["text"])
                            
                            elif chunk_type == "progress_end":
                                if key in progress_bars:
                                    progress_bars[key].progress(1.0, text="完了！")
                                    time.sleep(0.5)
                                    progress_bars[key].empty()
                                    del progress_bars[key]

                            elif chunk_type == "eval_progress":
                                # ★★★【ここが今回の修正の核】★★★
                                message = chunk.get("message", "")
                                skills = chunk.get("skills", "")
                                
                                # 整形して一時ログとして表示
                                if skills:
                                    temp_log_placeholder.info(f"{message}\n\n> **スキル:** {skills}")
                                else:
                                    temp_log_placeholder.info(message)
                        
                        # 2. それ以外（通常の文字列ログ）の場合
                        else:
                            chunk_str = str(chunk)
                            # ヒットログやステップ区切りは永続ログへ
                            if "✅ ヒット！" in chunk_str or "ステップ" in chunk_str or "最終候補者リスト" in chunk_str or "---" in chunk_str or "🎉" in chunk_str or "ℹ️" in chunk_str:
                                permanent_logs.append(chunk_str)
                                permanent_log_placeholder.markdown("".join(permanent_logs))
                                temp_log_placeholder.empty() # ヒットしたら一時ログはクリア
                            
                            # スキップログは一時ログへ
                            elif "ｽｷｯﾌﾟ" in chunk_str:
                                temp_log_placeholder.warning(chunk_str.strip())
                            
                            # その他のログも永続ログへ
                            else:
                                permanent_logs.append(chunk_str)
                                permanent_log_placeholder.markdown("".join(permanent_logs))

                except Exception as e:
                    st.error("処理中に予期せぬエラーが発生しました。")
                    st.exception(e)
                
                finally:
                    # 処理完了後、残っている一時ログとプログレスバーをすべて消去
                    temp_log_placeholder.empty()
                    for bar in progress_bars.values():
                        bar.empty()
                        
                # ▲▲▲【ログ表示ロジックここまで】▲▲▲
                

# フッター表示
ui.display_footer()
