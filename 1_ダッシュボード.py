# 1_ダッシュボード.py
import streamlit as st
from datetime import datetime, timedelta
# backend.pyから必要な関数と定数をインポート
from backend import (
    init_database,
    load_embedding_model,
    get_db_connection,
    get_match_summary_with_llm,
    hide_match
)

# ページ設定 (カスタムCSSの読み込みは不要)
st.set_page_config(page_title="Universal AIマッチングシステム | ダッシュボード", layout="wide")

# アプリケーションの初期化
init_database()
load_embedding_model()

st.title("Universal AIマッチングシステム")
st.divider()

# --- サイドバーのフィルター機能 (テーマ切り替えトグルは削除) ---
st.sidebar.header("フィルター")
min_score_filter = st.sidebar.slider("最小マッチ度 (%)", 0, 100, 0)
today = datetime.now().date()
default_start_date = today - timedelta(days=30)
start_date_filter = st.sidebar.date_input("開始日", value=default_start_date)
end_date_filter = st.sidebar.date_input("終了日", value=today)
keyword_filter = st.sidebar.text_input("キーワード検索")
show_hidden_filter = st.sidebar.checkbox("非表示も表示する", value=False)

st.header("最新マッチング結果一覧")

# --- DBからフィルタリングされた結果を取得 ---
# (この部分は変更なし)
conn = get_db_connection()
query = '''
    SELECT r.id as res_id, r.job_id, j.document as job_doc, r.engineer_id, e.document as eng_doc, r.score, r.created_at, r.is_hidden
    FROM matching_results r
    JOIN jobs j ON r.job_id = j.id
    JOIN engineers e ON r.engineer_id = e.id
    WHERE r.score >= ?
'''
params = [min_score_filter]
if start_date_filter: query += " AND date(r.created_at) >= ?"; params.append(start_date_filter)
if end_date_filter: query += " AND date(r.created_at) <= ?"; params.append(end_date_filter)
if keyword_filter: query += " AND (j.document LIKE ? OR e.document LIKE ?)"; params.extend([f'%{keyword_filter}%', f'%{keyword_filter}%'])
if not show_hidden_filter: query += " AND (r.is_hidden = 0 OR r.is_hidden IS NULL)"
query += " ORDER BY r.created_at DESC, r.score DESC LIMIT 50"
results = conn.execute(query, tuple(params)).fetchall()
conn.close()

# --- 結果の表示 (Streamlitネイティブコンポーネント使用) ---
if not results:
    st.info("フィルタリング条件に合致するマッチング結果はありませんでした。")
else:
    PREVIEW_LENGTH = 120

    for res in results:
        score = res['score']
        is_hidden = res['is_hidden'] == 1

        # ★★★ st.containerを使用して各結果を囲む ★★★
        with st.container(border=True):
            # --- ヘッダー部分 ---
            header_col1, header_col2 = st.columns([4, 1])
            with header_col1:
                st.caption(f"マッチング日時: {res['created_at']}")
            with header_col2:
                if is_hidden:
                    st.markdown('<p style="text-align: right; opacity: 0.7;">非表示</p>', unsafe_allow_html=True)
                elif score > 75:
                    st.markdown('<p style="text-align: right; color: #28a745; font-weight: bold;">高マッチ</p>', unsafe_allow_html=True)
            
            # --- メインコンテンツ部分 ---
            col1, col2, col3 = st.columns([5, 2, 5])
            with col1:
                st.markdown(f"##### 💼 案件情報 (ID: {res['job_id']})")
                job_preview = res['job_doc']
                if len(job_preview) > PREVIEW_LENGTH: job_preview = job_preview[:PREVIEW_LENGTH] + "..."
                st.caption(job_preview.replace("\n", "  \n"))

            with col2:
                st.metric(label="マッチ度", value=f"{score:.1f}%")

            with col3:
                st.markdown(f"##### 👤 技術者情報 (ID: {res['engineer_id']})")
                eng_preview = res['eng_doc']
                if len(eng_preview) > PREVIEW_LENGTH: eng_preview = eng_preview[:PREVIEW_LENGTH] + "..."
                st.caption(eng_preview.replace("\n", "  \n"))

            st.divider()

            # --- アクションボタン部分 ---
            spacer_col, ai_button_col, hide_button_col = st.columns([10, 2, 2])
            
            with ai_button_col:
                show_details_button = st.button("AI評価", key=f"detail_btn_{res['res_id']}", type="primary")

            with hide_button_col:
                if not is_hidden:
                    hide_button_clicked = st.button("非表示", key=f"hide_btn_{res['res_id']}", type="secondary")
                    if hide_button_clicked:
                        hide_match(res['res_id'])
                        st.toast(f"マッチング ID:{res['res_id']} を非表示にしました。")
                        st.rerun()

            # --- AI評価の表示 ---
            if show_details_button:
                summary_data = get_match_summary_with_llm(res['job_doc'], res['eng_doc'])
                if summary_data:
                    st.info(f"**🤖 総合評価:** {summary_data.get('summary', 'N/A')}")
                    
                    summary_col1, summary_col2 = st.columns(2)
                    with summary_col1:
                        st.markdown("###### ✅ ポジティブな点")
                        for point in summary_data.get('positive_points', ["特になし"]):
                            st.markdown(f"- {point}")
                    with summary_col2:
                        st.markdown("###### ⚠️ 懸念点")
                        concern_points = summary_data.get('concern_points', [])
                        if concern_points:
                            for point in concern_points:
                                st.markdown(f"- {point}")
                        else:
                            st.caption("特に懸念点は見つかりませんでした。")
        
        # 結果ごとのスペースを確保
        st.empty()

