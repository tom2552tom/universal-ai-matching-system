# pages/1_統計・分析ダッシュボード.py

import streamlit as st
import plotly.express as px
from backend import get_dashboard_data # backend.pyから関数をインポート

st.set_page_config(page_title="統計・分析ダッシュボード", layout="wide")

st.title("📊 統計・分析ダッシュボード")
st.write("このページでは、システム全体の活動状況やマッチングの品質を可視化します。")

# --- データ取得 ---
# エラーハンドリングを追加
try:
    summary_metrics, rank_counts = get_dashboard_data()
except Exception as e:
    st.error(f"データの読み込み中にエラーが発生しました: {e}")
    st.exception(e) # 詳細なトレースバックも表示
    st.stop() # エラーが発生したら処理を停止

# --- 1. サマリー指標（KPI）の表示 ---
st.header("サマリー指標")
col1, col2, col3 = st.columns(3)
with col1:
    # こちらを修正
    st.metric("総案件登録数", summary_metrics["total_jobs"], f"{summary_metrics['jobs_this_month']} (今月)")
with col2:
    st.metric("総技術者登録数", summary_metrics["total_engineers"], f"{summary_metrics['engineers_this_month']} (今月)")
with col3:
    st.metric("総マッチング生成数", summary_metrics["total_matches"])

st.divider()

# --- 2. マッチング品質分析 ---
st.header("マッチング品質分析")

# AI評価ランクの割合を円グラフで表示
fig_pie = px.pie(
    values=rank_counts.values,
    names=rank_counts.index,
    title="AI評価ランクの割合",
    color=rank_counts.index,
    color_discrete_map={ # ランクごとに色を固定
        'S': '#FF4B4B',
        'A': '#FF8C00',
        'B': '#1E90FF',
        'C': '#90EE90',
        'D': '#D3D3D3'
    },
    category_orders={"names": ['S', 'A', 'B', 'C', 'D']} # 順番を固定
)
fig_pie.update_layout(legend_title_text='AIランク')

# AI評価ランクの件数を棒グラフで表示
fig_bar = px.bar(
    x=rank_counts.index,
    y=rank_counts.values,
    title="AI評価ランクごとの件数",
    labels={'x': 'AIランク', 'y': '件数'},
    text=rank_counts.values,
    color=rank_counts.index,
    # 棒グラフの色も円グラフと合わせると統一感が出ます
    color_discrete_map={
        'S': '#FF4B4B',
        'A': '#FF8C00',
        'B': '#1E90FF',
        'C': '#90EE90',
        'D': '#D3D3D3'
    }
)
fig_bar.update_traces(textposition='outside')

col1, col2 = st.columns(2)
with col1:
    st.plotly_chart(fig_pie, use_container_width=True)
with col2:
    st.plotly_chart(fig_bar, use_container_width=True)
