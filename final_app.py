import streamlit as st
import sqlite3
import faiss
from sentence_transformers import SentenceTransformer
import numpy as np
import os
import google.generativeai as genai
import json
import shutil
from datetime import datetime, timedelta # timedeltaを追加
import pandas as pd

# --- 1. 初期設定と定数 ---
# グローバル変数としてAPIキーを定義
API_KEY = "AIzaSyC46t0x01KwILNwK1a3U2DO5cm0blvztOU" # ★★★ あなたのGoogle AI APIキーに書き換えてください ★★★

# 起動時に一度だけAPIキーの有効性をチェック
try:
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error(f"起動時のAPIキー設定に問題があります: {e}")
    st.stop()

DB_FILE = "backend_system.db"
JOB_INDEX_FILE = "backend_job_index.faiss"
ENGINEER_INDEX_FILE = "backend_engineer_index.faiss"
MODEL_NAME = 'intfloat/multilingual-e5-large'
MAILBOX_DIR = "mailbox"
PROCESSED_DIR = "processed"

# --- 2. モデル読み込みとDB初期化 ---
@st.cache_resource
def load_embedding_model():
    return SentenceTransformer(MODEL_NAME)

def init_database():
    os.makedirs(MAILBOX_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, document TEXT NOT NULL, created_at TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS engineers (id INTEGER PRIMARY KEY AUTOINCREMENT, document TEXT NOT NULL, created_at TEXT)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matching_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        engineer_id INTEGER,
        score REAL,
        created_at TEXT,
        FOREIGN KEY (job_id) REFERENCES jobs (id),
        FOREIGN KEY (engineer_id) REFERENCES engineers (id)
    )''')
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# --- 3. LLM関連の関数 ---

# キャッシュを無効化
def split_text_with_llm(text_content):
    # 関数内でAPIキーを再設定
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('models/gemini-2.5-pro')
    prompt = f"""
あなたは、IT業界の案件情報と技術者情報を整理する優秀なアシスタントです。
以下のテキストから、「案件情報」と「技術者情報」をそれぞれ個別の単位で抽出し、JSON形式のリストで出力してください。
# 制約条件
- 案件情報には、ポジション、業務内容、スキルなどの情報を含めてください。
- 技術者情報には、氏名、スキル、経験などの情報を含めてください。
- 元のテキストに含まれない情報は創作しないでください。
- それぞれ明確に分割し、他の案件や技術者の情報が混ざらないようにしてください。
- 該当する情報がない場合は、空のリスト `[]` を返してください。
# 対象テキスト
---
{text_content}
---
# 出力形式 (JSONのみを出力すること)
{{
  "jobs": [ {{ "document": "<抽出した案件1の情報>" }} ],
  "engineers": [ {{ "document": "<抽出した技術者1の情報>" }} ]
}}
"""
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {
        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
    }
    try:
        with st.spinner("LLMがテキストを解析・分割中..."):
            response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        return json.loads(response.text)
    except Exception as e:
        st.error(f"LLMによる分割に失敗: {e}")
        return None

# キャッシュを無効化
def get_match_summary_with_llm(job_doc, engineer_doc):
    # 関数内でAPIキーを再設定
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('models/gemini-2.5-pro')
    prompt = f"""
あなたは優秀なIT採用担当者です。以下の【案件情報】と【技術者情報】を比較し、なぜこの二者がマッチするのか、あるいはしないのかを分析してください。
結果は必ず指定のJSON形式で出力してください。
# 分析のポイント
- positive_points: 案件の必須スキルや業務内容と、技術者のスキルや経験が合致する点を具体的に挙げてください。
- concern_points: 案件が要求しているが技術者の経歴からは読み取れないスキルや、経験年数のギャップなど、懸念される点を挙げてください。
- summary: 上記を総合的に判断し、採用担当者向けの簡潔なサマリーを記述してください。
# 【案件情報】
{job_doc}
# 【技術者情報】
{engineer_doc}
# 出力形式 (JSONのみ)
{{
  "positive_points": ["<合致する点1>", "<合致する点2>"],
  "concern_points": ["<懸念点1>", "<懸念点2>"],
  "summary": "<総合評価サマリー>"
}}
"""
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {
        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
    }
    try:
        with st.spinner("AIがマッチング根拠を分析中..."):
            response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        return json.loads(response.text)
    except Exception as e:
        st.error(f"根拠の分析中にエラー: {e}")
        return None

# --- 4. インデックスと検索の関数 ---
def update_index(index_path, new_items):
    embedding_model = load_embedding_model()
    dimension = embedding_model.get_sentence_embedding_dimension()
    if os.path.exists(index_path):
        index = faiss.read_index(index_path)
    else:
        index = faiss.IndexIDMap(faiss.IndexFlatL2(dimension))
    ids = np.array([item['id'] for item in new_items], dtype=np.int64)
    texts = [item['document'] for item in new_items]
    embeddings = embedding_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    index.add_with_ids(embeddings, ids)
    faiss.write_index(index, index_path)

def search(query_text, index_path, top_k=5):
    if not os.path.exists(index_path): return [], []
    index = faiss.read_index(index_path)
    if index.ntotal == 0: return [], []
    embedding_model = load_embedding_model()
    query_vector = embedding_model.encode(query_text, normalize_embeddings=True).reshape(1, -1)
    distances, ids = index.search(query_vector, min(top_k, index.ntotal))
    return distances[0].tolist(), ids[0].tolist()

# --- 5. メインのバックエンド処理関数 ---
def process_new_mails():
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    existing_job_ids = {row['id'] for row in conn.execute('SELECT id FROM jobs').fetchall()}
    existing_engineer_ids = {row['id'] for row in conn.execute('SELECT id FROM engineers').fetchall()}

    unread_mails = [f for f in os.listdir(MAILBOX_DIR) if f.endswith('.txt')]
    if not unread_mails:
        st.toast("新しいメールはありませんでした。")
        return True
    st.toast(f"{len(unread_mails)}件の新しいメールを処理します。")
    all_new_jobs, all_new_engineers = [], []
    for mail_file in unread_mails:
        mail_path = os.path.join(MAILBOX_DIR, mail_file)
        with open(mail_path, 'r', encoding='utf-8') as f: content = f.read()
        parsed_data = split_text_with_llm(content)
        if not parsed_data:
            st.warning(f"ファイル '{mail_file}' の処理中にエラーが発生したため、中断しました。")
            return False

        new_jobs = parsed_data.get("jobs", [])
        new_engineers = parsed_data.get("engineers", [])
        
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        # ★【修正点】'document'の中身が辞書か文字列かを判定して処理する ★
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        if new_jobs:
            for job in new_jobs:
                doc_content = job.get('document')
                # doc_contentが辞書の場合、見やすい文字列に変換する
                if isinstance(doc_content, dict):
                    doc_str = "\n".join([f"{k}：{v}" for k, v in doc_content.items()])
                else:
                    doc_str = str(doc_content) # 文字列ならそのまま
                
                cursor.execute('INSERT INTO jobs (document, created_at) VALUES (?, ?)', (doc_str, now_str))
                job['id'] = cursor.lastrowid
                job['document'] = doc_str # 後続処理のために文字列で上書き
                all_new_jobs.append(job)

        if new_engineers:
            for engineer in new_engineers:
                doc_content = engineer.get('document')
                # doc_contentが辞書の場合、見やすい文字列に変換する
                if isinstance(doc_content, dict):
                    doc_str = "\n".join([f"{k}：{v}" for k, v in doc_content.items()])
                else:
                    doc_str = str(doc_content) # 文字列ならそのまま

                cursor.execute('INSERT INTO engineers (document, created_at) VALUES (?, ?)', (doc_str, now_str))
                engineer['id'] = cursor.lastrowid
                engineer['document'] = doc_str # 後続処理のために文字列で上書き
                all_new_engineers.append(engineer)
        
        conn.commit()
        shutil.move(mail_path, os.path.join(PROCESSED_DIR, mail_file))

    # (以降のマッチングロジックは変更なし)
    if all_new_jobs: update_index(JOB_INDEX_FILE, all_new_jobs)
    if all_new_engineers: update_index(ENGINEER_INDEX_FILE, all_new_engineers)
    
    # ... (重複排除マッチングロジック) ...
    # 新しい案件と既存の技術者のマッチング
    if all_new_jobs and existing_engineer_ids:
        for job in all_new_jobs:
            # 既存の技術者全体を対象に検索（ただし、IDは既存技術者に限定）
            distances, ids = search(job['document'], ENGINEER_INDEX_FILE, top_k=len(existing_engineer_ids) if existing_engineer_ids else 1)
            for dist, eng_id in zip(distances, ids):
                if eng_id != -1 and eng_id in existing_engineer_ids: # 既存の技術者IDに存在することを確認
                    score = (1 - dist) * 100
                    cursor.execute('INSERT INTO matching_results (job_id, engineer_id, score, created_at) VALUES (?, ?, ?, ?)',
                                   (job['id'], int(eng_id), score, now_str))

    # 新しい技術者と既存の案件のマッチング
    if all_new_engineers and existing_job_ids:
        for engineer in all_new_engineers:
            # 既存の案件全体を対象に検索（ただし、IDは既存案件に限定）
            distances, ids = search(engineer['document'], JOB_INDEX_FILE, top_k=len(existing_job_ids) if existing_job_ids else 1)
            for dist, job_id in zip(distances, ids):
                if job_id != -1 and job_id in existing_job_ids: # 既存の案件IDに存在することを確認
                    score = (1 - dist) * 100
                    cursor.execute('INSERT INTO matching_results (job_id, engineer_id, score, created_at) VALUES (?, ?, ?, ?)',
                                   (int(job_id), engineer['id'], score, now_str))


    conn.commit()
    conn.close()
    st.success("メール処理とマッチングが完了しました。")
    return True


# --- 6. Streamlit UIの定義 ---
st.set_page_config(page_title="AIマッチングシステム", layout="wide")
st.markdown('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">', unsafe_allow_html=True)

load_embedding_model()
init_database()

st.title("AIマッチングシステム ダッシュボード")
if st.button("📧 新着メールをチェックしてマッチング実行", type="primary"):
    with st.spinner("処理を実行中..."):
        success = process_new_mails()
    if success:
        st.rerun()

st.divider()

# --- サイドバーにフィルター機能を追加 ---
st.sidebar.header("マッチング結果フィルター")

# 最小マッチ度フィルター
min_score_filter = st.sidebar.slider("最小マッチ度 (%)", 0, 100, 0)

# 日付範囲フィルター
today = datetime.now().date()
default_start_date = today - timedelta(days=30) # デフォルトで過去30日
start_date_filter = st.sidebar.date_input("開始日", value=default_start_date)
end_date_filter = st.sidebar.date_input("終了日", value=today)

# キーワード検索フィルター
keyword_filter = st.sidebar.text_input("キーワード検索 (案件/技術者情報)")

st.header("最新マッチング結果一覧")

conn = get_db_connection()

# フィルタリング条件に基づいてSQLクエリを構築
query = '''
    SELECT r.id as res_id, r.job_id, j.document as job_doc, r.engineer_id, e.document as eng_doc, r.score, r.created_at
    FROM matching_results r
    JOIN jobs j ON r.job_id = j.id
    JOIN engineers e ON r.engineer_id = e.id
    WHERE r.score >= ?
'''
params = [min_score_filter]

# 日付フィルタの追加
if start_date_filter:
    query += " AND r.created_at >= ?"
    params.append(start_date_filter.strftime('%Y-%m-%d 00:00:00'))
if end_date_filter:
    query += " AND r.created_at <= ?"
    params.append(end_date_filter.strftime('%Y-%m-%d 23:59:59'))

# キーワードフィルタの追加
if keyword_filter:
    query += " AND (j.document LIKE ? OR e.document LIKE ?)"
    params.append(f'%{keyword_filter}%')
    params.append(f'%{keyword_filter}%')

query += " ORDER BY r.created_at DESC, r.score DESC LIMIT 50"

results = conn.execute(query, params).fetchall()
conn.close()

if not results:
    st.info("フィルタリング条件に合致するマッチング結果はありませんでした。")
else:
    for res in results:
        score = res['score']
        if score > 75: border_class = "border-success"
        elif score > 60: border_class = "border-primary"
        else: border_class = "border-secondary"
        st.markdown(f'<div class="card {border_class} mb-3">', unsafe_allow_html=True)
        header_html = f'<div class="card-header d-flex justify-content-between align-items-center"><span>マッチング日時: {res["created_at"]}</span>'
        if score > 75: header_html += f'<span class="badge bg-success">高マッチ</span>'
        header_html += '</div>'
        st.markdown(header_html, unsafe_allow_html=True)
        st.markdown('<div class="card-body">', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"<h6>案件 (ID: {res['job_id']})</h6>", unsafe_allow_html=True)
            st.text_area("", res['job_doc'], height=150, disabled=True, key=f"job_{res['res_id']}")
        with col2:
            st.markdown(f"<h6>技術者 (ID: {res['engineer_id']})</h6>", unsafe_allow_html=True)
            st.text_area("", res['eng_doc'], height=150, disabled=True, key=f"eng_{res['res_id']}")
        st.progress(int(score), text=f"マッチ度: {score:.1f}%")
        button_key = f"summary_btn_{res['res_id']}"
        if st.button("AIによる評価サマリーを表示", key=button_key):
            summary_data = get_match_summary_with_llm(res['job_doc'], res['eng_doc'])
            if summary_data:
                st.markdown("---")
                st.markdown("<h5><i class='bi bi-search-heart'></i> AI評価サマリー</h5>", unsafe_allow_html=True)
                st.info(f"**総合評価:** {summary_data.get('summary', 'N/A')}")
                st.markdown("<h6>ポジティブな点</h6>", unsafe_allow_html=True)
                for point in summary_data.get('positive_points', []):
                    st.markdown(f"- {point}")
                st.markdown("<h6 style='margin-top: 1rem;'>懸念点</h6>", unsafe_allow_html=True)
                concern_points = summary_data.get('concern_points', [])
                if concern_points:
                    for point in concern_points:
                        st.markdown(f"- {point}")
                else:
                    st.caption("特に懸念点は見つかりませんでした。")
        st.markdown('</div></div>', unsafe_allow_html=True)

