# pages/0_ライブモニタリング.py (最終レイアウト版)

import streamlit as st
import backend as be
import time
import pandas as pd
import plotly.express as px
from datetime import datetime
import ui_components as ui
import requests
from streamlit_lottie import st_lottie

# --- ページの基本設定 ---
st.set_page_config(page_title="リアルタイム分析", layout="wide", initial_sidebar_state="collapsed")
ui.apply_global_styles()

# --- アニメーション用のJavaScriptとCSS ---
# ページ冒頭で一度だけ定義する
JS_COUNTER_CODE = """
<script>
function animateValue(obj, start, end, duration) {
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        obj.innerHTML = Math.floor(progress * (end - start) + start).toLocaleString();
        if (progress < 1) { window.requestAnimationFrame(step); }
    };
    window.requestAnimationFrame(step);
}
document.addEventListener("DOMContentLoaded", function() {
    const metrics = parent.document.querySelectorAll('.animated-metric');
    metrics.forEach(metric => {
        const targetValue = parseInt(metric.getAttribute('data-value'));
        const obj = metric.querySelector('div.value');
        if (obj) {
            const startValue = parseInt(obj.textContent.replace(/,/g, '')) || 0;
            if (startValue !== targetValue) {
                animateValue(obj, startValue, targetValue, 800);
            }
        }
    });
});
</script>
"""
st.components.v1.html(JS_COUNTER_CODE, height=0)

st.markdown("""
<style>
.custom-metric {
    border: 1px solid #444; border-radius: 8px; padding: 1rem;
    text-align: center; background-color: #262730; height: 100%;
}
.custom-metric .label { font-size: 0.9rem; color: #a0a0a0; margin-bottom: 0.5rem; }
.custom-metric .value { font-size: 2.5rem; font-weight: bold; line-height: 1.2; color: #fafafa; }
</style>
""", unsafe_allow_html=True)


# --- Lottieアニメーション読み込み関数 ---
@st.cache_data
def load_lottie_url(url: str):
    r = requests.get(url)
    if r.status_code != 200: return None
    return r.json()

# --- データ取得 ---
@st.cache_data(ttl=5)
def get_dashboard_data_cached():
    return be.get_live_dashboard_data()
dashboard_data = get_dashboard_data_cached()


# ==================================
# === ヘッダーエリア ===
# ==================================
col_title, col_counter = st.columns([3, 2]) # カラムの比率を調整

with col_title:
    st.title("🚀 AIシステム リアルタイム分析")
    st.caption(f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

with col_counter:
    # 垂直位置を調整するためのスペーサー
    st.write("") 
    
    with st.container(border=True):
        col_anim, col_val = st.columns([1, 2]) # アニメーションの比率を少し広げる

        with col_anim:
            lottie_url = "https://lottie.host/6944da1c-9801-4b65-a942-df7837fc1157/eFcKKThSu1.json"
            lottie_json = load_lottie_url(lottie_url)
            if lottie_json:
                st_lottie(lottie_json, speed=1, height=100, width=100, key="ai_robot") 

        with col_val:
            total_ai_activities = sum(dashboard_data.get('ai_activity_counts', {}).values())
            st.markdown("###### 本日のAI総思考回数")
            # style内の text-align を 'center' に変更
            st.markdown(f"""
                <div class="animated-metric" data-value="{total_ai_activities}" style="text-align: center;">
                    <div class="value" style="font-size: 2.5rem; color: #28a745; line-height: 1.2;">{total_ai_activities:,}</div>
                </div>
            """, unsafe_allow_html=True)
            # ★★★【修正ここまで】★★★

st.divider()


# ==================================
# === サマリーKPIエリア ===
# ==================================
st.header("📊 今日の活動サマリー")

def animated_metric(label, value):
    st.markdown(f"""
        <div class="custom-metric">
            <div class="label">{label}</div>
            <div class="animated-metric" data-value="{value}">
                <div class="value">{value:,}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

# 4つのKPIを横に並べて表示
kpi_cols = st.columns(3)
kpi_map = {
    "本日登録の案件数": dashboard_data.get('jobs_today', 0),
    "本日登録の技術者数": dashboard_data.get('engineers_today', 0),
    #"現在の総提案件数": dashboard_data.get('proposal_count_total', 0),
    "本日の採用決定数": dashboard_data.get('adopted_count_today', 0)
}
for col, (label, value) in zip(kpi_cols, kpi_map.items()):
    with col:
        animated_metric(label, value)

st.divider()


# ==================================
# === ビジネス成果エリア (OUTPUT) ===
# ==================================
st.header("📈 マッチングの進捗状況")

# ファネルチャートと担当者ランキングを横に並べる
col_funnel, col_rank = st.columns([2, 1], gap="large")

with col_funnel:
    st.subheader("ステータス別の状況")
    funnel_data = dashboard_data.get('funnel_data', {})
    funnel_stages = ["新規", "提案準備中", "提案中", "クライアント面談", "結果待ち", "採用"]
    funnel_df = pd.DataFrame({
        "ステータス": [stage for stage in funnel_stages if stage in funnel_data],
        "件数": [funnel_data.get(stage, 0) for stage in funnel_stages if stage in funnel_data]
    })
    
    if not funnel_df.empty:
        fig = px.funnel(funnel_df, x='件数', y='ステータス', orientation='h')
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


# ★★★【ここからが新しいセクション】★★★
st.divider()



# ★★★【ここからが修正の核】★★★
# バックエンドから総数を取得
active_request_count = dashboard_data.get('active_auto_request_count', 0)

# ヘッダーに総数を表示
st.header(f"🤖 現在有効な自動マッチング依頼 ({active_request_count} 件)")

active_requests = dashboard_data.get('active_auto_requests', [])

if not active_requests:
    st.info("現在、アクティブな自動マッチング依頼はありません。")
else:
    # リスト表示部分は変更なし
    st.caption(f"最新 {len(active_requests)} 件を表示しています。")
    
    # ★★★【ここからが修正の核】★★★
    for req in active_requests:
        item_type = req['item_type']
        item_id = req['item_id']
        
        # アイコンとリンク先ページを決定
        if item_type == 'job':
            item_type_icon = "💼"
            page_path = "pages/6_案件詳細.py"
            session_key = "selected_job_id"
        else:
            item_type_icon = "👤"
            page_path = "pages/5_技術者詳細.py"
            session_key = "selected_engineer_id"

        item_name = req['item_name']
        target_rank = req['target_rank']
        match_count = req['match_count']
        
        # AI要約のプレビューを生成
        doc_parts = req.get('document', '').split('\n---\n', 1)
        main_doc_preview = (doc_parts[1] if len(doc_parts) > 1 else doc_parts[0]).replace('\n', ' ').strip()
        main_doc_preview = main_doc_preview[:100] + "..." if len(main_doc_preview) > 100 else main_doc_preview

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                # タイトルをクリック可能にする
                if st.button(f"**{item_type_icon} {item_name}** (ID: {item_id})", key=f"req_title_{req['id']}", use_container_width=True):
                    st.session_state[session_key] = item_id
                    st.switch_page(page_path)
                
                # AI要約のプレビュー
                st.caption(main_doc_preview)
            
            with col2:
                # チップ風に情報を表示
                chips_html = ""
                chips_html += f"<span style='...'>🎯 {target_rank}以上</span>" # スタイルは適宜調整
                if match_count > 0:
                    chips_html += f"<span style='...'>🤝 {match_count}件</span>"
                st.markdown(chips_html, unsafe_allow_html=True)

# ★★★【修正ここまで】★★★



# --- 自動リフレッシュ ---
time.sleep(10)
st.rerun()
