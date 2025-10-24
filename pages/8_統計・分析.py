# pages/8_統計・分析.py

import streamlit as st
import plotly.express as px
import pandas as pd
from backend import get_dashboard_data
import ui_components as ui

ui.apply_global_styles()
st.set_page_config(page_title="統計・分析ダッシュボード", layout="wide")

st.title("📊 統計・分析ダッシュボード")
st.write("このページでは、システム全体の活動状況やマッチングの品質を可視化します。")

# --- データ取得 ---
try:
    # ▼▼▼【ここが修正箇所です】▼▼▼
    summary_metrics, rank_counts, time_series_df, assignee_counts_df, match_rank_by_assignee = get_dashboard_data()
except Exception as e:
    st.error(f"データの読み込み中にエラーが発生しました: {e}")
    st.exception(e)
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
col1, col2 = st.columns(2)
with col1:
    fig_pie = px.pie(
        values=rank_counts.values,
        names=rank_counts.index,
        title="AI評価ランクの割合",
        color=rank_counts.index,
        color_discrete_map={ 'S': '#FF4B4B', 'A': '#FF8C00', 'B': '#1E90FF', 'C': '#90EE90', 'D': '#D3D3D3' },
        category_orders={"names": ['S', 'A', 'B', 'C', 'D']}
    )
    fig_pie.update_layout(legend_title_text='AIランク')
    st.plotly_chart(fig_pie, use_container_width=True)
with col2:
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
    st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# --- 3. 時系列分析 ---
st.header("活動状況の推移")
try:
    if not time_series_df.empty:
        min_date, max_date = time_series_df.index.min().date(), time_series_df.index.max().date()
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("開始日", min_date, min_value=min_date, max_value=max_date, key="start_date_selector")
        with col2:
            end_date = st.date_input("終了日", max_date, min_value=min_date, max_value=max_date, key="end_date_selector")

        if start_date > end_date:
            st.error("開始日は終了日より前の日付を選択してください。")
        else:
            filtered_df = time_series_df[(time_series_df.index.date >= start_date) & (time_series_df.index.date <= end_date)]
            period = st.radio("集計単位", ['日別', '週別', '月別'], horizontal=True, key="time_series_period")
            
            resample_map = {'日別': 'D', '週別': 'W-MON', '月別': 'M'}
            period_label_map = {'日別': '日', '週別': '週', '月別': '月'}
            
            display_df = filtered_df.resample(resample_map[period]).sum() if period != '日別' else filtered_df

            if not display_df.empty:
                fig_line = px.line(
                    display_df, x=display_df.index, y=display_df.columns,
                    title=f"{period_label_map[period]}ごとの活動推移",
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
    st.error(f"時系列グラフの描画中にエラーが発生しました: {e}")
    st.exception(e)

st.divider()

# --- 4. 担当者別分析 ---
st.header("担当者別分析")
col1, col2 = st.columns(2)
with col1:
    if not match_rank_by_assignee.empty:
        df_melted = match_rank_by_assignee.reset_index().melt(id_vars='responsible_person', var_name='ランク', value_name='件数')
        fig_assignee_rank = px.bar(
            df_melted, x='responsible_person', y='件数', color='ランク',
            title='担当者別 マッチングランク分布',
            labels={'responsible_person': '担当者'},
            category_orders={"ランク": ["S", "A", "B", "C", "D"]},
            color_discrete_map={ 'S': '#FF4B4B', 'A': '#FF8C00', 'B': '#1E90FF', 'C': '#90EE90', 'D': '#D3D3D3' }
        )
        fig_assignee_rank.update_layout(barmode='stack')
        st.plotly_chart(fig_assignee_rank, use_container_width=True)
    else:
        st.info("担当者別のマッチングランクデータがありません。")
with col2:
    if not assignee_counts_df.empty:
        fig_assignee_count = px.bar(
            assignee_counts_df, x=assignee_counts_df.index, y=['案件担当数', '技術者担当数'],
            title='担当者別 担当件数',
            labels={'value': '件数', 'variable': '項目', 'index': '担当者'},
            barmode='group'
        )
        st.plotly_chart(fig_assignee_count, use_container_width=True)
    else:
        st.info("担当者別の担当件数データがありません。")


ui.display_footer()