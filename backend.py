import streamlit as st
import sqlite3
import faiss
from sentence_transformers import SentenceTransformer
import numpy as np
import os
import google.generativeai as genai
import json
import shutil
from datetime import datetime

# --- 1. 初期設定と定数 ---
# ★★★ 必ずご自身の有効なGoogle AI APIキーに書き換えてください ★★★
#API_KEY = "AIzaSyC46t0x01KwILNwK1a3U2DO5cm0blvztOU" 
# StreamlitのSecrets機能からAPIキーを安全に読み込む
API_KEY = st.secrets["GOOGLE_API_KEY"]

# APIキーの有効性を確認
try:
    genai.configure(api_key=API_KEY)
except Exception as e:
    # st.errorはUIスレッドでしか呼べないため、ここでは例外を発生させるかログに出力
    print(f"APIキー設定エラー: {e}")

DB_FILE = "backend_system.db"
JOB_INDEX_FILE = "backend_job_index.faiss"
ENGINEER_INDEX_FILE = "backend_engineer_index.faiss"
MODEL_NAME = 'intfloat/multilingual-e5-large'
MAILBOX_DIR = "mailbox"
PROCESSED_DIR = "processed"

# --- 2. モデル読み込みとDB初期化/更新 ---
@st.cache_resource
def load_embedding_model():
    """埋め込みモデルをロードしてキャッシュする"""
    try:
        return SentenceTransformer(MODEL_NAME)
    except Exception as e:
        st.error(f"埋め込みモデルの読み込みに失敗しました: {e}")
        return None

def init_database():
    """データベースとディレクトリを初期化し、必要に応じてテーブルを更新する"""
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

    # is_hiddenカラムが存在しない場合、追加する (後方互換性のため)
    cursor.execute("PRAGMA table_info(matching_results)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'is_hidden' not in columns:
        cursor.execute('ALTER TABLE matching_results ADD COLUMN is_hidden INTEGER DEFAULT 0')

    conn.commit()
    conn.close()

def get_db_connection():
    """データベース接続を取得する"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# --- 3. LLM関連の関数 ---
def split_text_with_llm(text_content):
    """LLMを使用してテキストを案件と技術者情報に分割する"""
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

def get_match_summary_with_llm(job_doc, engineer_doc):
    """LLMを使用してマッチングの根拠を分析する"""
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
    if not embedding_model: return
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
    embedding_model = load_embedding_model()
    if not embedding_model or not os.path.exists(index_path): return [], []
    index = faiss.read_index(index_path)
    if index.ntotal == 0: return [], []
    query_vector = embedding_model.encode(query_text, normalize_embeddings=True).reshape(1, -1)
    distances, ids = index.search(query_vector, min(top_k, index.ntotal))
    return distances[0].tolist(), ids[0].tolist()

# --- 5. メインのバックエンド処理関数 ---
def process_new_mails():
    """新しいメールを処理し、DB登録とマッチングを行う"""
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
    with st.spinner("メールを1件ずつ処理しています..."):
        for mail_file in unread_mails:
            mail_path = os.path.join(MAILBOX_DIR, mail_file)
            with open(mail_path, 'r', encoding='utf-8') as f: content = f.read()
            parsed_data = split_text_with_llm(content)
            if not parsed_data:
                st.warning(f"ファイル '{mail_file}' の処理中にエラーが発生したため、中断しました。")
                return False

            new_jobs = parsed_data.get("jobs", [])
            new_engineers = parsed_data.get("engineers", [])

            if new_jobs:
                for job in new_jobs:
                    doc_content = job.get('document')
                    doc_str = "\n".join([f"{k}：{v}" for k, v in doc_content.items()]) if isinstance(doc_content, dict) else str(doc_content)
                    cursor.execute('INSERT INTO jobs (document, created_at) VALUES (?, ?)', (doc_str, now_str))
                    job['id'] = cursor.lastrowid
                    job['document'] = doc_str
                    all_new_jobs.append(job)

            if new_engineers:
                for engineer in new_engineers:
                    doc_content = engineer.get('document')
                    doc_str = "\n".join([f"{k}：{v}" for k, v in doc_content.items()]) if isinstance(doc_content, dict) else str(doc_content)
                    cursor.execute('INSERT INTO engineers (document, created_at) VALUES (?, ?)', (doc_str, now_str))
                    engineer['id'] = cursor.lastrowid
                    engineer['document'] = doc_str
                    all_new_engineers.append(engineer)
            
            conn.commit()
            shutil.move(mail_path, os.path.join(PROCESSED_DIR, mail_file))

    with st.spinner("インデックスを更新し、マッチングを実行中..."):
        if all_new_jobs: update_index(JOB_INDEX_FILE, all_new_jobs)
        if all_new_engineers: update_index(ENGINEER_INDEX_FILE, all_new_engineers)

        if all_new_jobs and existing_engineer_ids:
            for job in all_new_jobs:
                distances, ids = search(job['document'], ENGINEER_INDEX_FILE, top_k=len(existing_engineer_ids))
                for dist, eng_id in zip(distances, ids):
                    if eng_id != -1 and eng_id in existing_engineer_ids:
                        score = (1 - dist) * 100
                        cursor.execute('INSERT INTO matching_results (job_id, engineer_id, score, created_at) VALUES (?, ?, ?, ?)',(job['id'], int(eng_id), score, now_str))
        
        if all_new_engineers:
            k_value = len(existing_job_ids) if existing_job_ids else 1
            for engineer in all_new_engineers:
                distances, ids = search(engineer['document'], JOB_INDEX_FILE, top_k=k_value)
                for dist, job_id in zip(distances, ids):
                    if job_id != -1:
                        score = (1 - dist) * 100
                        cursor.execute('INSERT INTO matching_results (job_id, engineer_id, score, created_at) VALUES (?, ?, ?, ?)', (int(job_id), engineer['id'], score, now_str))

    conn.commit()
    conn.close()
    st.success("メール処理とマッチングが完了しました。")
    return True

# --- 6. 個別のアクション関数 ---
def hide_match(result_id):
    """指定されたIDのマッチング結果を非表示にする"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE matching_results SET is_hidden = 1 WHERE id = ?", (result_id,))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"非表示処理中にエラーが発生しました: {e}")
        return False
    finally:
        conn.close()
