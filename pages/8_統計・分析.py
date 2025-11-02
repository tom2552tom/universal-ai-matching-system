# pages/0_ライブモニタリング.py (縦型レイアウト改善版)

import streamlit as st
import backend as be
import time
import pandas as pd
import plotly.express as px
from datetime import datetime
import ui_components as ui

# --- ページの基本設定 ---
st.set_page_config(page_title="リアルタイム分析", layout="wide", initial_sidebar_state="collapsed")
ui.apply_global_styles()



# ★★★【ここからが修正の核】★★★
# --- アニメーション用のHTML/CSS/JavaScript ---
# 数字をアニメーションさせるためのJavaScript
JS_COUNTER_CODE = """
<script>
// この関数は、指定されたオブジェクトの数値をアニメーションさせます
function animateValue(obj, start, end, duration) {
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        // 現在の値を計算して表示
        obj.innerHTML = Math.floor(progress * (end - start) + start).toLocaleString();
        // アニメーションが完了していなければ、次のフレームを要求
        if (progress < 1) {
            window.requestAnimationFrame(step);
        }
    };
    window.requestAnimationFrame(step);
}

// ページ内のすべての 'animated-metric' クラスを持つ要素に対して処理を実行
const metrics = parent.document.querySelectorAll('.animated-metric');
metrics.forEach(metric => {
    const targetValue = parseInt(metric.getAttribute('data-value'));
    const obj = metric.querySelector('div'); // 最初のdivタグ（数字を表示する場所）を取得
    if (obj) {
        // 現在表示されている数値を取得（なければ0）
        const startValue = parseInt(obj.textContent.replace(/,/g, '')) || 0;
        // 現在の数値から目標値まで、500ミリ秒かけてアニメーション
        if (startValue !== targetValue) {
            animateValue(obj, startValue, targetValue, 500);
        }
    }
});
</script>
"""
# HTMLコンポーネントとしてJavaScriptをページのヘッドに埋め込む
st.components.v1.html(JS_COUNTER_CODE, height=0)
# ★★★【修正ここまで】★★★



# --- タイトル ---
st.title("🚀 AIシステム リアルタイム分析")
st.caption(f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- データ取得 ---
dashboard_data = be.get_live_dashboard_data()

st.divider()

# ==================================
# === サマリーKPIエリア ===
# ==================================
st.header("📊 今日の活動サマリー")

# 3つの主要なKPIを横に並べて強調
col1, col2, col3, col4 , col5 = st.columns(5)

# ★★★【ここからが修正の核】★★★
with col1:
    st.metric(
        label="登録案件数",
        value=f"{dashboard_data.get('jobs_today', 0)} 件"
    )

with col2:
    st.metric(
        label="登録技術者数",
        value=f"{dashboard_data.get('engineers_today', 0)} 件"
    )
# ★★★【修正ここまで】★★★

with col3:
    st.metric(
        label="マッチング件数",
        value=f"{dashboard_data.get('new_matches_today', 0)} 件"
    )

with col4:
    st.metric(
        label="提案件数",
        value=f"{dashboard_data.get('proposal_count_total', 0)} 件",
        help="ステータスが「提案準備中」または「提案中」の総数です。"
    )

with col5:
    adopted_count_today = dashboard_data.get('adopted_count_today', 0)
    st.metric(
        label="採用決定数",
        value=f"{adopted_count_today} 件"
    )

st.divider()

# ==================================
# === AI活動のライブ表示エリア ===
# ==================================
st.header("🤖 AI稼働状況")
with st.container(border=True):
    
    ai_activities = dashboard_data.get('ai_activity_counts', {})
    total_evals = sum(ai_activities.values())

    ai_evals_today = dashboard_data.get('ai_evaluations_today', 0)
    
    st.markdown("##### 本日のAI実行回数")
    # アニメーション付きカウンター
    st.markdown(f"""
        <div class="animated-metric" data-value="{total_evals}" style="text-align: center;">
            <div style="font-size: 4.5rem; font-weight: bold; color: #28a745; line-height: 1.1;">{total_evals:,}</div>
        </div>
    """, unsafe_allow_html=True)
    

    st.caption("AIが案件と技術者のマッチング評価を行った累計回数です。バックグラウンドで稼働しています。")

st.divider()


# ==================================
# === ビジネス成果エリア (OUTPUT) ===
# ==================================
st.header("📈 ビジネス成果")

# ファネルチャートと担当者ランキングを横に並べる
col_funnel, col_rank = st.columns([2, 1], gap="large")

with col_funnel:
    st.subheader("マッチングファネル")
    funnel_data = dashboard_data.get('funnel_data', {})
    funnel_stages = ["新規", "提案準備中", "提案中", "クライアント面談", "結果待ち", "採用"]
    funnel_df = pd.DataFrame({
        "ステージ": [stage for stage in funnel_stages if stage in funnel_data],
        "件数": [funnel_data.get(stage, 0) for stage in funnel_stages if stage in funnel_data]
    })
    
    if not funnel_df.empty:
        fig = px.funnel(funnel_df, x='件数', y='ステージ', orientation='h')
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("ファネルデータがありません。")

with col_rank:
    st.subheader("トップパフォーマー")
    st.caption("今月の採用件数ランキング")
    top_performers = dashboard_data.get('top_performers', [])
    if not top_performers:
        st.info("今月の採用実績はまだありません。")
    else:
        rank_icons = ["🥇", "🥈", "🥉"]
        for i, performer in enumerate(top_performers):
            icon = rank_icons[i] if i < len(rank_icons) else f"**{i+1}.**"
            st.markdown(f"{icon} {performer['username']} : **{performer['adoption_count']}** 件")

st.divider()

# ==================================
# === リアルタイム活動ログエリア ===
# ==================================
st.header("⚙️ リアルタイム活動ログ")

# ログ表示エリアを2つに分ける
col_input, col_process = st.columns(2, gap="large")

with col_input:
    st.subheader("📥 データ登録 (INPUT)")
    with st.container(height=300, border=True):
        # デモ用にランダムなログを表示
        demo_logs_input = [
            "INFO: 新着メールをチェック中...",
            "SUCCESS: (株)ABC商事からのメールを発見。",
            "INFO: 添付ファイル「【急募】インフラエンジニア.docx」を解析中...",
            "INFO: AIが内容を「案件情報」と判断しました。",
            "SUCCESS: DBへの登録が完了しました (Job ID: 16501)。"
        ]
        st.code("\n".join(demo_logs_input), language="log")

with col_process:
    st.subheader("🤖 AIマッチング (PROCESSING)")
    with st.container(height=300, border=True):
        recent_matches = dashboard_data.get('recent_matches', [])
        if not recent_matches:
            st.info("まだマッチングログがありません。")
        else:
            log_text = ""
            for match in recent_matches:
                log_text += f"✅ HIT! [案件] {match['project_name']} ⇔ [技術者] {match['engineer_name']} (ランク: {match['grade']})\n"
            st.code(log_text, language="log")


# --- 自動リフレッシュ ---
time.sleep(10)
st.rerun()
