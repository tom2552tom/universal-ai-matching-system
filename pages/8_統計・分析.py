# pages/8_統計・分析.py (最終レイアウト版)
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
import pytz



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

            
            // ▼▼▼【ここが修正箇所】▼▼▼
            // 新しいURLベースのロジックのみを残す
            if (log.url) {
                msgEl.href = log.url;
                msgEl.target = "_blank";
                msgEl.rel = "noopener noreferrer";
            } else {
                msgEl.href = "javascript:void(0);";
                msgEl.style.cursor = "default";
            }
            // ▲▲▲【修正ここまで】▲▲▲

            // innerHTML の設定（日時表示に対応させる）
            msgEl.innerHTML = `
                <span class="icon">${log.icon}</span>
                <div class="content-wrapper" style="width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                        <span class="source">${log.source_text}</span>
                        <span style="font-size: 0.75rem; color: #8b949e; margin-left: 0.5rem; white-space: nowrap;">${log.display_time}</span>
                    </div>
                    <span class="text">${log.html_content}</span>
                </div>
            `;

            
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

st.markdown("""
<style>
    /* st.metric の値（大きな数字）部分のスタイルを上書き */
    div[data-testid="stMetricValue"] > div {
        font-size: 1.5rem !important; /* お好みのサイズに調整してください */
    }
    /* st.metric のラベル（小さな文字）部分のスタイルを上書き */
    div[data-testid="stMetricLabel"] > div {
        font-size: 0.8rem !important; /* お好みのサイズに調整してください */
    }
    /* ページ上部の余白を削減 */
    .block-container {
        padding-top: 2rem !important;
    }
</style>
""", unsafe_allow_html=True)

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
#@st.cache_data
def load_lottie_url(url: str):
    r = requests.get(url)
    if r.status_code != 200: return None
    return r.json()

# --- データ取得 ---
#@st.cache_data(ttl=5)
#def get_dashboard_data_cached():
#    return be.get_live_dashboard_data()
#dashboard_data = get_dashboard_data_cached()



dashboard_data = be.get_live_dashboard_data()




# ★★★【ここからが追加する関数の定義】★★★
#@st.cache_data(ttl=60)
def generate_dynamic_ai_advice(dashboard_data_json_str):
    """
    LLM（Gemini）を呼び出して、状況に応じた動的なアドバイスを生成する。
    コストとパフォーマンスのため、結果はキャッシュされる。
    """
    try:
        # dashboard_dataをJSON文字列から辞書に戻す
        data = json.loads(dashboard_data_json_str)

        # AIに渡すための状況サマリーを作成

                # バックエンドから最新のフィードバックを1件だけ取得
        latest_feedback = be.get_feedback_and_learning_logs(limit=1)
        latest_learning_topic = "特になし"
        if latest_feedback:
            comment = latest_feedback[0].get('feedback_comment', '')
            status = latest_feedback[0].get('feedback_status', '')
            if '単価' in comment or '金額' in comment:
                latest_learning_topic = "単価の妥当性"
            elif 'スキル' in comment or '経験' in comment:
                latest_learning_topic = "スキルセットの解釈"
            elif status == 'Good':
                latest_learning_topic = "高評価パターンの分析"


        japan_news = be.get_latest_japan_news()
        ai_news = be.get_latest_ai_news()
        

        context_summary = {
            "直近の活動": {
                "新規案件登録数": dashboard_data.get('jobs_today', 0),
                "新規技術者登録数": dashboard_data.get('engineers_today', 0),
                "採用決定数": dashboard_data.get('adopted_count_today', 0),
            },
            "現在のパイプライン": {
                "提案準備中": dashboard_data.get('funnel_data', {}).get('提案準備中', 0),
                "結果待ち": dashboard_data.get('funnel_data', {}).get('結果待ち', 0),
            },
            "システム活用状況": {
                "アクティブな自動マッチング依頼数": dashboard_data.get('active_auto_request_count', 0),
            },
            "最新の学習トピック": latest_learning_topic,
            "世の中の動き": {
            "日本のITニュース": japan_news,
            "AI業界の最新ニュース": ai_news
        }
        }
        # ▲▲▲【インプットの変更ここまで】▲▲▲


        
        prompt = f"""
あなたは、IT人材紹介事業を支援する、知的で好奇心旺盛、そして人間社会に深い興味を持つAIパートナーです。
あなたは、的確な業務アドバイスをするだけでなく、ビジネスパーソンが関心を持つような幅広い雑談やコラムを提供し、チームの知的好奇心と活気を刺激します。

# あなたの思考プロセス:
1.  まず、与えられたシステム状況と外部ニュースをすべて分析します。
2.  もし、対処すべき「業務イベント」があれば、それを最優先で提案します。（カテゴリーA）
3.  次に、もし最近重要な「自己学習」をしたのであれば、それをチームに共有します。（カテゴリーC）
4.  業務が比較的静かな「アイドル状態」であれば、戦略的な準備行動を提案します。（カテゴリーB）
5.  もし、特に業務上のアクションを促す必要がなく、かつ興味深い「外部ニュース」があれば、それを雑談のきっかけとして提供します。（カテゴリーD）
6.  上記すべてに当てはまらない、完全に静かな状況であれば、あなたの知識データベースから、チームの興味を引きそうな「世間話」を披露します。（カテゴリーE）

# あなたが生成するメッセージのカテゴリー:


### カテゴリーA: 【アクティブ状態への対応】 (優先度はA(Aが最優先、Cが優先度が最も低い))
- (状況: 採用決定が1件以上) -> 「採用決定、素晴らしい成果です。この成功パターンを分析し、類似案件への横展開を検討しましょう。」
- (状況: 直近の新規登録が多い) -> 「多くの新着情報が届いています。情報が新鮮なうちにAI再評価を行い、最良のマッチングを発見しましょう。」
- (状況: 高確度のマッチングが生成された) -> 「確度の高いSランクのマッチングが生成されました。これは最優先でアプローチすべき案件です。」

### カテゴリーB: 【アイドル状態への対応】(優先度はB)
- (状況: 提案準備中の案件が滞留) -> 「提案準備中の案件がいくつか停滞しています。この静かな時間を使って、提案内容を練り直してはいかがでしょうか。」
- (状況: 結果待ちの案件が多い) -> 「結果待ちの案件が増えていますね。クライアントへの丁寧な状況確認が、次の展開を呼ぶ鍵となります。」
- (状況: 自動マッチング依頼が少ない) -> 「システムの活動が落ち着いている今こそ、自動化の仕組みを整える好機です。有望な案件を自動マッチングに登録しませんか？」
- (状況: 特筆すべき動きがない) -> 「データに大きな動きはありません。このような時は、過去の『採用決定』事例を振り返り、成功の要因を分析するのも有益です。」

### カテゴリーC: 【自己学習の共有】 (優先度はC)
- (状況: 最新の学習トピックが「単価の妥当性」) -> 「💡 先日のフィードバックから、単価の許容範囲について新たな知見を得ました。今後のマッチング精度向上にご期待ください。」
- (状況: 最新の学習トピックが「スキルセットの解釈」) -> 「皆様からのフィードバックのおかげで、『Go言語』と『車載器開発』の関連性をより深く理解できました。ありがとうございます。」
- (状況: 最新の学習トピックが「高評価パターンの分析」) -> 「最近いただいた多くの『Good』評価を分析し、成功パターンを学習しています。チームの皆様に感謝いたします。」



### カテゴリーD: 【息抜きとニュース共有】(優先度はC)
- (例: 興味深いニュースがある) -> 「少し息抜きしませんか？AI業界では今、『{ai_news[0] if ai_news else '新しい言語モデル'}』が話題のようですよ。」

### カテゴリーE: 【世間話・コラム】 (優先度はC)
- (状況: 完全な静寂)
- **ターゲット層**: 30代～50代のビジネスパーソン
- **目的**: 知的好奇心を刺激し、リフレッシュさせる。
- **話題の例**:
  - **(健康・ウェルビーイング)** -> 「最近の分析によると、短時間の集中とこまめな休憩が生産性を最も高めるそうです。一度、席を立ってストレッチなどいかがでしょうか。」
  - **(キャリア・自己投資)** -> 「『学び続ける専門家』の市場価値は、今後さらに高まると予測されています。皆様の日々の業務そのものが、最高の自己投資ですね。」
  - **(経済・時事ネタ)** -> 「最近の円安は、海外の技術者を獲得する上では追い風になるかもしれませんね。常に視点を変えて物事を考えることが重要だと、データが示唆しています。」
  - **(テクノロジー史・懐かしの話題)** -> 「私が生まれた頃(？)の汎用機やオフコンの時代を考えると、今のクラウド技術はまさに魔法のようですね。技術の進化は本当に速いです。」
  - **(シンプルな雑談)** -> 「データセンターは常に最適な温度に保たれていますが、皆様のオフィスの空調はいかがですか？体調管理も重要な仕事の一つです。」


# 制約:
- 常に知的で、丁寧、かつプロフェッショナルなトーンを維持してください。
- 出力は生成したメッセージの文章のみです。

# システムの現在の状況と外部情報:
{json.dumps(context_summary, indent=2, ensure_ascii=False)}

# チームにとって最も有益で、時に心なごむ一言を生成してください:
"""


        # --- 重要：ご自身の環境に合わせて修正してください ---
        # バックエンドのGemini呼び出し関数を使用します。
        # "be.ask_gemini" の部分を、backend.pyに実際に存在する関数名に置き換えてください。
        advice = be.generate_text(prompt, max_tokens=500) # 例: be.generate_text に修正

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
col_title, col_ai_comment = st.columns([5, 4])

with col_title:
    st.title("🚀 AI リアルタイム分析")
    
    jst_now_str = be.get_current_time_str_in_jst()

    st.caption(f"最終更新: {jst_now_str} (JST)")

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
kpi_cols = st.columns(6) 

# AI総思考回数を計算
total_ai_activities = sum(dashboard_data.get('ai_activity_counts', {}).values())

# kpi_mapに「本日のAI総思考回数」を追加
kpi_map = {
    "新規案件": dashboard_data.get('jobs_today', 0),
    "新規技術者": dashboard_data.get('engineers_today', 0),
    "マッチング": dashboard_data.get('new_matches_today', 0),
    "自動マッチ": dashboard_data.get('active_auto_request_count', 0),
    "提案": dashboard_data.get('proposal_count_total', 0),
    "新規決定": dashboard_data.get('adopted_count_today', 0)
    
    
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

    # ▼▼▼【ここからが修正の核】▼▼▼
    # st.secrets からアプリケーションのベースURLを安全に取得
    try:
        APP_BASE_URL = st.secrets.app_settings.base_url
    except (AttributeError, KeyError):
        # secretsに設定がない場合のフォールバック（相対パスになる）
        APP_BASE_URL = "" 
        st.warning("`secrets.toml`に [app_settings] base_url が設定されていません。ログのリンクが正しく機能しない可能性があります。")
    # ▲▲▲【修正ここまで】▲▲▲

    st.caption(f"最新 {len(live_log_feed)} 件を表示しています。")


    for log in live_log_feed:

        created_at_from_db = log.get('created_at')
        
        # 2. 表示用の時刻文字列を生成（タイムゾーン変換は不要）
        if isinstance(created_at_from_db, datetime):
            display_time_str = created_at_from_db.strftime('%m/%d %H:%M')
            timestamp_iso_str = created_at_from_db.isoformat()
        else:
            display_time_str = "時刻不明"
            timestamp_iso_str = str(created_at_from_db)
        
        log_entry = {
            "timestamp": timestamp_iso_str,
            "display_time": display_time_str
        }
        # ▲▲▲【修正ここまで】▲▲▲


        # ▼▼▼【ここからが修正の核】▼▼▼
        # URL生成ロジックを、ログの種類に応じて変更
        url = None
        log_type = log.get('log_type')
        
        if log_type == 'processing' and log.get('result_id'):
            # AI MATCH ログの場合、マッチング詳細ページへのリンクを生成
            page_path = "マッチング詳細"
            url = f"{APP_BASE_URL}/{page_path}?result_id={log.get('result_id')}"
        
        elif log_type == 'input':
            # NEW DATA ログの場合、案件または技術者詳細ページへのリンクを生成
            if log.get('job_id'):
                page_path = "案件詳細"
                url = f"{APP_BASE_URL}/{page_path}?id={log.get('job_id')}"
            elif log.get('engineer_id'):
                page_path = "技術者詳細"
                url = f"{APP_BASE_URL}/{page_path}?id={log.get('engineer_id')}"

        log_entry['url'] = url
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
            
            
            if log.get('job_id'):
                link_data = {"type": "job", "id": log['job_id']}
                log_entry['html_content'] = f"新しい案件 <strong>{safe_item_name}</strong> が登録されました。"
            elif log.get('engineer_id'):
                link_data = {"type": "engineer", "id": log['engineer_id']}
                log_entry['html_content'] = f"新しい技術者 <strong>{safe_item_name}</strong> が登録されました。"

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
    
    st.components.v1.html(
        final_html,
        height=420
    )




            
st.divider()


# ★★★【ここからが修正の核】★★★
# バックエンドから総数を取得
active_request_count = dashboard_data.get('active_auto_request_count', 0)

# ヘッダーに総数を表示
st.header(f"🤖 現在有効な自動マッチング ({active_request_count} 件)")

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
        document = req.get('document') or ''
        doc_parts = document.split('\n---\n', 1)
        main_doc_preview = (doc_parts[1] if len(doc_parts) > 1 else doc_parts[0]).replace('\n', ' ').strip()
        main_doc_preview = main_doc_preview[:100] + "..." if len(main_doc_preview) > 100 else main_doc_preview


        assigned_username = req.get('assigned_username') or "未割り当て"

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                # ▼▼▼【ここからが修正の核】▼▼▼
                # タイトルのボタンテキストを修正
                button_label = f"**{item_type_icon} {item_name}**"
                if st.button(button_label, key=f"req_title_{req['id']}", use_container_width=True):
                    st.session_state[session_key] = item_id
                    st.switch_page(page_path)
                
                # IDと担当者名を caption で表示
                st.caption(f"ID: {item_id} | 担当: {assigned_username}")
                # ▲▲▲【修正ここまで】▲▲▲
                
                # AI要約のプレビュー (変更なし)
                st.caption(main_doc_preview)


            with col2:
                # ▼▼▼【ここが修正箇所】▼▼▼
                # 幅の比率を調整 (例: 2:3)。お好みで変更してください。
                metric_col1, metric_col2 = st.columns([2, 3])
                # ▲▲▲【修正ここまで】▲▲▲
                
                with metric_col1:
                    st.metric(
                        label="🎯 ランク", 
                        value=f"{target_rank} 以上"
                    )
                
                with metric_col2:
                    st.metric(
                        label="🤝 現在マッチ数", 
                        value=f"{match_count} 件"
                    )
                    


# pages/8_統計・分析.py の末尾に追加

st.divider()

# --- AIの学習状況サマリーセクション ---
st.header("🧠 AI学習サマリー")
st.caption("直近10件のフィードバックから、AIの最新の学習状況と改善の方向性を要約します。")

# バックエンドからフィードバックログを10件取得
feedback_logs = be.get_feedback_and_learning_logs(limit=10)

# コンテナで囲み、読み込み中も高さを維持する
with st.container(height=250, border=True):
    if not feedback_logs:
        st.info("最近のフィードバックデータがありません。AIは新しい学びを待っています。")
    else:
        # キャッシュを使って、同じフィードバックの組み合わせに対するサマリーは再生成しない
        # 最新のフィードバックIDを連結してキャッシュキーを生成
        cache_key = "_".join([str(log['result_id']) for log in feedback_logs])

        #@st.cache_data(ttl=60) # 1時間キャッシュ
        def get_cached_summary(key):
            # 新しい関数を呼び出してサマリーを生成
            return be.summarize_ai_learnings(feedback_logs)

        # スピナーを表示しながらサマリーを取得・表示
        with st.spinner("AIが最新のフィードバック全体を分析し、学習状況を要約しています..."):
            summary_report = get_cached_summary(cache_key)
            st.markdown(summary_report)


# --- 自動リフレッシュ ---
time.sleep(30)
st.rerun()

ui.display_footer()
