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
import json # ★ jsonをインポート
import html # ★ HTMLエスケープのために追加
import random # ★★★ ランダム選択のために追加 ★★★




AI_COMMENTS = [
    "今日も順調に稼働中です！何かお探しですか？",
    "新しい案件、見逃していませんか？リストをチェック！",
    "データベースの健康状態は良好です。",
    "マッチング精度向上のため、日々学習しています。",
    "良い出会いは、素早いアクションから生まれます。",
    "お疲れ様です。一息つきませんか？",
    "現在、最高の候補者を探しています…お待ちください。",
    "何か面白い情報は見つかりましたか？",
]


CHAT_LOG_HTML = """
<style>
    .chat-container-wrapper {
        position: relative;
        /* ★ 変更点 1: 幅を親要素の100%に設定 */
        width: 100%;
        /* ★ 変更点 2: paddingやborderを幅の内側に含める（安全策）*/
        box-sizing: border-box;
    }
    .chat-container {
        height: 375px;
        background-color: #1a1a1a;
        border: 1px solid #333;
        border-radius: 12px;
        padding: 1rem;
        display: flex;
        flex-direction: column;
        overflow-y: auto;
        font-family: 'Segoe UI', 'Meiryo', sans-serif;
    }
    .chat-container::after {
        content: '';
        display: block;
        height: 0.5rem;
        flex-shrink: 0;
    }
    /* (以降のCSSとJavaScriptは変更なし) */
    .chat-container::-webkit-scrollbar { width: 8px; }
    .chat-container::-webkit-scrollbar-track { background: #1a1a1a; border-radius: 10px; }
    .chat-container::-webkit-scrollbar-thumb { background-color: #555; border-radius: 10px; border: 2px solid #1a1a1a; }
    a.chat-message { display: flex; align-items: flex-start; background-color: #31333F; border: 1px solid #4A4D59; padding: 0.75rem 1rem; border-radius: 8px; margin-top: 0.6rem; animation: slide-in-from-bottom 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards; opacity: 0; box-shadow: 0 2px 5px rgba(0,0,0,0.2); transition: background-color 0.2s ease, transform 0.2s ease; text-decoration: none; color: inherit; cursor: pointer; }
    a.chat-message:hover { background-color: #404452; transform: scale(1.01); }
    .chat-message .icon { font-size: 1.2rem; margin-right: 0.8rem; line-height: 1.5; }
    .chat-message .content-wrapper { display: flex; flex-direction: column; }
    .chat-message .source { font-size: 0.8rem; font-weight: bold; color: #aaa; margin-bottom: 0.2rem; }
    .chat-message.input .source { color: #58a6ff; }
    .chat-message.processing .source { color: #56d364; }
    .chat-message .text { font-size: 0.95rem; color: #e6edf3; line-height: 1.5; }
    .chat-message .text strong { color: #f1c40f; font-weight: 600; }
    .new-message-toast { position: absolute; bottom: 1rem; left: 50%; transform: translateX(-50%); background-color: #3498db; color: white; padding: 0.5rem 1rem; border-radius: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); cursor: pointer; z-index: 10; font-size: 0.9rem; font-weight: bold; animation: toast-in 0.3s ease-out forwards; opacity: 0; }
    @keyframes toast-in { from { opacity: 0; transform: translate(-50%, 10px); } to { opacity: 1; transform: translate(-50%, 0); } }
    @keyframes slide-in-from-bottom { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
</style>
<div class="chat-container-wrapper">
    <div id="chat-log-box" class="chat-container"></div>
    <div id="new-message-toast" class="new-message-toast" style="display: none;">⬇️ 新着メッセージ</div>
</div>
<script>
    const chatBox = document.getElementById('chat-log-box');
    const newMsgToast = document.getElementById('new-message-toast');
    
    __LOG_DATA_PLACEHOLDER__

    const existingIds = new Set();
    chatBox.querySelectorAll('.chat-message').forEach(el => { existingIds.add(el.id); });
    const scrollBottomOffset = chatBox.scrollHeight - chatBox.clientHeight - chatBox.scrollTop;
    const scrollThreshold = 50;
    const isScrolledToBottom = scrollBottomOffset < scrollThreshold;
    newLogs.slice().reverse().forEach((log, index) => {
        const logId = `log-${log.timestamp}`;
        if (!existingIds.has(logId)) {
            const msgEl = document.createElement('a');
            msgEl.id = logId;
            msgEl.className = `chat-message ${log.type}`;
            msgEl.href = '#';
            if (log.link_data) {
                msgEl.onclick = (event) => {
                    event.preventDefault();
                    Streamlit.setComponentValue(log.link_data);
                };
            } else {
                msgEl.style.cursor = 'default';
                msgEl.onclick = (event) => event.preventDefault();
            }
            msgEl.innerHTML = `<span class="icon">${log.icon}</span><div class="content-wrapper"><span class="source">${log.source_text}</span><span class="text">${log.html_content}</span></div>`;
            setTimeout(() => {
                chatBox.appendChild(msgEl);
                if (isScrolledToBottom) {
                    chatBox.scrollTop = chatBox.scrollHeight;
                } else {
                    newMsgToast.style.display = 'block';
                }
            }, index * 200);
        }
    });
    newMsgToast.onclick = () => { chatBox.scrollTo({ top: chatBox.scrollHeight, behavior: 'smooth' }); };
    chatBox.onscroll = () => {
        const currentScrollBottomOffset = chatBox.scrollHeight - chatBox.clientHeight - chatBox.scrollTop;
        if (currentScrollBottomOffset < scrollThreshold) { newMsgToast.style.display = 'none'; }
    };
</script>
"""





# ★★★【修正ここまで】★★★


# --- ページの基本設定 ---
st.set_page_config(page_title="リアルタイム分析", layout="wide", initial_sidebar_state="collapsed")
ui.apply_global_styles()

if not ui.check_password():
    st.stop() # 認証が通らない場合、ここで処理を停止

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




# ★★★【ここからが追加する関数の定義】★★★
@st.cache_data(ttl=60) # 10分間 (600秒) 結果をキャッシュする
def generate_dynamic_ai_advice(dashboard_data_json_str):
    """
    LLM（Gemini）を呼び出して、状況に応じた動的なアドバイスを生成する。
    コストとパフォーマンスのため、結果はキャッシュされる。
    """
    try:
        # dashboard_dataをJSON文字列から辞書に戻す
        data = json.loads(dashboard_data_json_str)

        # AIに渡すための状況サマリーを作成
        context_summary = {
            "今日の案件登録数": data.get('jobs_today', 0),
            "今日の技術者登録数": data.get('engineers_today', 0),
            "今日の採用決定数": data.get('adopted_count_today', 0),
            "現在の自動マッチング依頼数": data.get('active_auto_request_count', 0),
            "現在の時刻": datetime.now().strftime('%H:%M'),
        }

        # AIへの指示（プロンプト）
        prompt = f"""
        あなたは、企業の営業担当者やリクルーターが利用するAIマッチングシステムの優秀なアシスタントです。
        以下のシステム状況を分析し、ユーザーのモチベーションを高め、次にしてほしい行動を優しく促すような、短くて気の利いたアドバイスを生成してください。

        # 制約条件:
        - 非常に簡潔に、40字以内で記述してください。
        - 親しみやすいですが、プロフェッショナルなトーンを保ってください。
        - 生成するのはアドバイスの文章のみです。余計な前置きや記号は含めないでください。

        # システムの現在の状況:
        {json.dumps(context_summary, indent=2, ensure_ascii=False)}

        # アドバイスの例:
        - 新しい案件がまだ未チェックですよ！
        - 採用決定おめでとうございます！素晴らしい成果です！
        - 午後もこの調子で頑張りましょう！

        # アドバイスを生成してください:
        """

        # --- 重要：ご自身の環境に合わせて修正してください ---
        # バックエンドのGemini呼び出し関数を使用します。
        # "be.ask_gemini" の部分を、backend.pyに実際に存在する関数名に置き換えてください。
        advice = be.generate_text(prompt, max_tokens=60) # 例: be.generate_text に修正

        # AIの応答が空でないことを確認
        if advice and advice.strip():
            return advice.strip()
        else:
            # AIが空の応答を返した場合、固定のメッセージにフォールバック
            return random.choice(AI_COMMENTS)

    except Exception as e:
        # APIエラーなど、何らかの例外が発生した場合
        print(f"AIアドバイスの生成に失敗しました: {e}")
        # 固定のメッセージを返すことで、エラーをユーザーに見せない（フォールバック）
        return random.choice(AI_COMMENTS)

# ★★★【ここまでが追加する関数の定義】★★★


# ==================================
# === ヘッダーエリア ===
# ==================================
col_title, col_ai_comment = st.columns([3, 2])

with col_title:
    st.title("🚀 AIシステム リアルタイム分析")
    st.caption(f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

with col_ai_comment:
    st.write("") 
    with st.container(border=True):
        col_anim, col_text = st.columns([1, 2], gap="small")
        with col_anim:
            # (Lottieアニメーションのコードは変更なし)
            lottie_url = "https://lottie.host/6944da1c-9801-4b65-a942-df7837fc1157/eFcKKThSu1.json"
            lottie_json = load_lottie_url(lottie_url)
            if lottie_json:
                st_lottie(lottie_json, speed=1, height=100, width=100, key="ai_robot") 

        with col_text:
            st.markdown("###### 🤖 AIからのアドバイス")
            

            # ★★★【ここからが修正の核】★★★

            # 1. コンテンツを表示するための空のプレースホルダーを作成
            advice_placeholder = st.empty()

            # datetimeオブジェクトをJSONシリアライズ可能にするためのカスタムエンコーダー
            def datetime_encoder(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

            try:
                dashboard_data_str = json.dumps(dashboard_data, default=datetime_encoder)
                advice = generate_dynamic_ai_advice(dashboard_data_str)
                
                # 2. プレースホルダーを使ってコンテンツを描画
                advice_placeholder.info(f"**{advice}**")

                

            except Exception as e:
                # json.dumpsで予期せぬエラーが発生した場合のフォールバック
                st.error("AIアドバイスの表示中にエラーが発生しました。")
                print(f"AIアドバイス表示エラー: {e}")

            # ★★★【修正ここまで】★★★


st.divider()

# ==================================
# === サマリーKPIエリア ===
# ==================================
st.header("📊 今日の活動サマリー")

def animated_metric(label, value):
    # (この関数の内容は変更なし)
    st.markdown(f"""
        <div class="custom-metric">
            <div class="label">{label}</div>
            <div class="animated-metric" data-value="{value}">
                <div class="value">{value:,}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

# ★★★【ここからが修正の核】★★★
# 4つのKPIを横に並べて表示するために st.columns(4) に変更
kpi_cols = st.columns(4) 

# AI総思考回数を計算
total_ai_activities = sum(dashboard_data.get('ai_activity_counts', {}).values())

# kpi_mapに「本日のAI総思考回数」を追加
kpi_map = {
    "本日登録の案件数": dashboard_data.get('jobs_today', 0),
    "本日登録の技術者数": dashboard_data.get('engineers_today', 0),
    "本日のマッチング数": dashboard_data.get('new_matches_today', 0),
    "本日の採用決定数": dashboard_data.get('adopted_count_today', 0)
}
# ★★★【修正ここまで】★★★
for col, (label, value) in zip(kpi_cols, kpi_map.items()):
    with col:
        animated_metric(label, value)

st.divider()



#with st.expander("⚙️ リアルタイム活動ログ（クリックで展開）", expanded=False):
st.header("⚙️ リアルタイム活動ログ") 
live_log_feed = dashboard_data.get('live_log_feed', [])

if live_log_feed:
    log_feed_data = []
    for log in live_log_feed:
        # ★★★【ここからが修正の核】★★★
        # created_at の処理は変更なし
        created_at_dt = log['created_at'] 
        if isinstance(created_at_dt, datetime):
            display_time_str = created_at_dt.strftime('%m/%d %H:%M')
            timestamp_iso_str = created_at_dt.isoformat()
        else:
            # 万が一 datetime でない場合は、空文字列をデフォルトにするか、エラーログを出す
            display_time_str = "不明"
            timestamp_iso_str = str(created_at_dt) # とりあえず文字列にする

        log_entry = {
            "timestamp": timestamp_iso_str,
            "display_time": display_time_str
        }
        # ▲▲▲【修正ここまで】▲▲▲

        link_data = None
        if log['log_type'] == 'input':
            # ▼▼▼【ここからが修正の核】▼▼▼
            # item_name が確実に文字列になるように修正
            item_name_raw = log.get('project_name') or log.get('engineer_name')
            item_name = item_name_raw if item_name_raw is not None else "名称不明"
            
            safe_item_name = html.escape(str(item_name)) # str() で確実に文字列に変換してからエスケープ
            # ▲▲▲【修正ここまで】▲▲▲
            
            log_entry['type'] = 'input'
            log_entry['icon'] = '📥'
            log_entry['source_text'] = 'NEW DATA'
            log_entry['html_content'] = f"新しいデータ <strong>{safe_item_name}</strong> が登録されました。"
            
            if log.get('job_id'):
                link_data = {"type": "job", "id": log['job_id']}
            elif log.get('engineer_id'):
                link_data = {"type": "engineer", "id": log['engineer_id']}

        elif log['log_type'] == 'processing':
            # ▼▼▼【ここからが修正の核】▼▼▼
            # name が None の場合に備えてデフォルト値を追加
            project_name = html.escape(str(log.get('project_name', '名称不明の案件')))
            engineer_name = html.escape(str(log.get('engineer_name', '名称不明の技術者')))
            rank = html.escape(str(log.get('grade', 'N/A')))
            # ▲▲▲【修正ここまで】▲▲▲

            log_entry['type'] = 'processing'
            log_entry['icon'] = '✅'
            log_entry['source_text'] = 'AI MATCH'
            log_entry['html_content'] = f"HIT! <strong>{project_name}</strong> ⇔ <strong>{engineer_name}</strong> (Rank: {rank})"
            
            if log.get('job_id'):
                link_data = {"type": "job", "id": log['job_id']}
        
        log_entry['link_data'] = link_data
        log_feed_data.append(log_entry)

    log_feed_json = json.dumps(log_feed_data)
    
    final_html = CHAT_LOG_HTML.replace(
        '__LOG_DATA_PLACEHOLDER__', 
        f'const newLogs = {log_feed_json};'
    )
    
    clicked_log = st.components.v1.html(
        final_html,
        height=420
    )




    if clicked_log and isinstance(clicked_log, dict):
        if clicked_log.get("type") == "job":
            st.session_state['selected_job_id'] = clicked_log.get("id")
            st.switch_page("pages/6_案件詳細.py")
        elif clicked_log.get("type") == "engineer":
            st.session_state['selected_engineer_id'] = clicked_log.get("id")
            st.switch_page("pages/5_技術者詳細.py")
else:
        
    with st.container(height=400, border=True):
        st.info("現在、表示するリアルタイム活動ログはありません。")



            
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
