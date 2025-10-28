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
        target_rank = st.selectbox("最低ランク", ['S', 'A', 'B', 'C'], index=2)
    with col2:
        target_count = st.number_input("最大表示件数", 1, 50, 10)
    submitted = st.form_submit_button("この条件で候補者を探す", type="primary", use_container_width=True)


# ▼▼▼【ここからが全面的に修正する処理ロジック】▼▼▼

# --- 処理ロジック ---
if submitted:
    if not input_text.strip():
        st.error("案件情報または技術者情報を入力してください。")
    else:
        # 結果表示用のコンテナをフォームの外側に用意
        results_container = st.container()
        
        with results_container:
            with st.expander("処理ログと結果", expanded=True):
                
                # ジェネレータ関数を呼び出す
                response_generator = be.find_candidates_on_demand(
                    input_text=input_text,
                    target_rank=target_rank,
                    target_count=target_count
                )
                
                # st.empty() を使って、リアルタイムでログを表示する場所を確保
                log_placeholder = st.empty()
                log_chunks = []
                
                try:
                    # ジェネレータをループで回して、yieldされた値を取得
                    for chunk in response_generator:
                        log_chunks.append(str(chunk))
                        # これまで受信したログをすべて結合して表示
                        log_placeholder.markdown("".join(log_chunks))
                
                except Exception as e:
                    # ジェネレータの実行中にエラーが発生した場合
                    st.error("処理中に予期せぬエラーが発生しました。")
                    st.exception(e)

# ▲▲▲【修正ここまで】▲▲▲

# フッター表示
ui.display_footer()
