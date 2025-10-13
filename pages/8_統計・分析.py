# pages/8_統計・分析.py

import streamlit as st
import plotly.express as px
import pandas as pd # pandasのインポートも確認
from backend import get_dashboard_data

st.set_page_config(page_title="統計・分析ダッシュボード", layout="wide")

st.title("📊 統計・分析ダッシュボード")
st.write("このページでは、システム全体の活動状況やマッチングの品質を可視化します。")

# --- データ取得 ---
try:
    # ▼▼▼【ここが修正箇所です】▼▼▼
    summary_metrics, rank_counts, time_series_df = get_dashboard_data()
except Exception as e:
    st.error(f"データの読み込み中にエラーが発生しました: {e}")
    st.exception(e) # 詳細なトレースバックも表示
    st.stop()

# --- 1. サマリー指標（KPI）の表示 ---
st.header("サマリー指標")
col1, col2, col3 = st.columns(3)
with col1:
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
    color_discrete_map={ 'S': '#FF4B4B', 'A': '#FF8C00', 'B': '#1E90FF', 'C': '#90EE90', 'D': '#D3D3D3' },
    category_orders={"names": ['S', 'A', 'B', 'C', 'D']}
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
    color_discrete_map={ 'S': '#FF4B4B', 'A': '#FF8C00', 'B': '#1E90FF', 'C': '#90EE90', 'D': '#D3D3D3' }
)
fig_bar.update_traces(textposition='outside')

col1, col2 = st.columns(2)
with col1:
    st.plotly_chart(fig_pie, use_container_width=True)
with col2:
    st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# --- 3. 時系列分析 ---
st.header("活動状況の推移")

try:
    if not time_series_df.empty:
        # 日付範囲セレクター
        min_date = time_series_df.index.min().date()
        max_date = time_series_df.index.max().date()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("開始日", min_date, min_value=min_date, max_value=max_date, key="start_date_selector")
        with col2:
            end_date = st.date_input("終了日", max_date, min_value=min_date, max_value=max_date, key="end_date_selector")

        # 開始日と終了日の順序をチェック
        if start_date > end_date:
            st.error("開始日は終了日より前の日付を選択してください。")
        else:
            # 選択された日付範囲でデータをフィルタリング
            filtered_df = time_series_df[(time_series_df.index.date >= start_date) & (time_series_df.index.date <= end_date)]

            # 集計期間の選択
            period = st.radio("集計単位", ['日別', '週別', '月別'], horizontal=True, key="time_series_period")

            # 選択に応じてデータを再集計
            if period == '週別':
                display_df = filtered_df.resample('W-MON').sum()
                period_label = "週"
            elif period == '月別':
                display_df = filtered_df.resample('M').sum()
                period_label = "月"
            else: # 日別
                display_df = filtered_df
                period_label = "日"

            # 折れ線グラフの描画
            if not display_df.empty:
                fig_line = px.line(
                    display_df, 
                    x=display_df.index, 
                    y=display_df.columns,
                    title=f"{period_label}ごとの活動推移",
                    labels={'value': '件数', 'created_at': '日付', 'variable': '項目'},
                    markers=True
                )
                fig_line.update_layout(legend_title_text='項目')
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.warning("選択された期間にデータがありません。")
    else:
        st.info("時系列分析を行うためのデータがまだありません。")

except Exception as e:
    st.error(f"グラフの描画中にエラーが発生しました: {e}")
    st.exception(e)

