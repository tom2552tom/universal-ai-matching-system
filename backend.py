import streamlit as st
import sqlite3
import faiss
from sentence_transformers import SentenceTransformer
import numpy as np
import os
import google.generativeai as genai
import json
from datetime import datetime
import imaplib
import email
from email.header import decode_header
import io
import contextlib
import toml
import fitz
import docx
import psycopg2
from psycopg2.extras import DictCursor


# --- 1. 初期設定と定数 ---
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=API_KEY)
except (KeyError, Exception):
    st.error("`secrets.toml` に `GOOGLE_API_KEY` が設定されていません。")
    st.stop()

DB_FILE = "backend_system.db"
JOB_INDEX_FILE = "backend_job_index.faiss"
ENGINEER_INDEX_FILE = "backend_engineer_index.faiss"
MODEL_NAME = 'intfloat/multilingual-e5-large'
TOP_K_CANDIDATES = 500
MIN_SCORE_THRESHOLD = 70.0 # 推奨値に設定

@st.cache_data
def load_app_config():
    config_file_path = "config.toml"
    
    # --- デバッグ情報出力 ---
    print("--- load_app_config デバッグ開始 ---")
    
    # 1. 現在の作業ディレクトリを確認
    current_directory = os.getcwd()
    print(f"現在の作業ディレクトリ: {current_directory}")

    # 2. config.toml の絶対パスを計算
    absolute_path = os.path.abspath(config_file_path)
    print(f"探している設定ファイルの絶対パス: {absolute_path}")

    # 3. ファイルが存在するかどうかをチェック
    if not os.path.exists(config_file_path):
        print(f"❌ エラー: '{config_file_path}' が見つかりません。")
        print("--- デバッグ終了 ---")
        # ファイルが見つからない場合は、デフォルトの辞書を返す
        return {"app": {"title": "Universal AI Agent (Default)"}}
    
    print(f"✅ '{config_file_path}' が見つかりました。読み込みを試みます。")
    # --- デバッグ情報ここまで ---

    try:
        with open(config_file_path, "r", encoding="utf-8") as f:
            loaded_config = toml.load(f)
            print("✅ tomlファイルの読み込みに成功しました。")
            print(f"読み込まれた内容: {loaded_config}")
            print("--- デバッグ終了 ---")
            return loaded_config
    except FileNotFoundError:
        # この部分は os.path.exists でチェックしているので通常は通らない
        print("❌ エラー: FileNotFoundErrorが発生しました。")
        print("--- デバッグ終了 ---")
        return {"app": {"title": "Universal AI Agent (Default)"}}
    except Exception as e:
        # tomlの構文エラーなど、その他のエラーをキャッチ
        print(f"❌ エラー: 設定ファイルの読み込み中に予期せぬエラーが発生しました: {e}")
        print("--- デバッグ終了 ---")
        return {"app": {"title": "Universal AI Agent (Error)"}}
    



@st.cache_resource
def load_embedding_model():
    try: return SentenceTransformer(MODEL_NAME)
    except Exception as e: st.error(f"埋め込みモデル '{MODEL_NAME}' の読み込みに失敗しました: {e}"); return None


# backend.py

# ▼▼▼【この関数全体を置き換えてください】▼▼▼

# backend.py の init_database 関数を以下に置き換え

def init_database():
    """
    PostgreSQLデータベースとテーブルを初期化する。
    既存のテーブルやカラムをチェックし、不足している場合は追加する。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # --- ヘルパー関数 (カラム存在チェック用) ---
        def column_exists(table, column):
            cursor.execute("""
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """, (table, column))
            return cursor.fetchone() is not None

        # --- テーブル作成 (PostgreSQL互換) ---
        cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id SERIAL PRIMARY KEY, project_name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS engineers (id SERIAL PRIMARY KEY, name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT)')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS matching_results (
                id SERIAL PRIMARY KEY,
                job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
                engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
                score REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_hidden INTEGER DEFAULT 0,
                grade TEXT,
                positive_points TEXT,
                concern_points TEXT,
                proposal_text TEXT,
                status TEXT DEFAULT '新規',
                UNIQUE (job_id, engineer_id)
            )
        ''')

        # --- 初回起動時のテストユーザー追加 ---
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            print("初回起動のため、テストユーザーを追加します...")
            users_to_add = [
                ('熊崎', 'yamada@example.com'), ('岩本', 'suzuki@example.com'),
                ('小関', 'sato@example.com'), ('内山', 'uchiyama@example.com'),
                ('島田', 'shimada@example.com'), ('長谷川', 'hasegawa@example.com'),
                ('北島', 'kitajima@example.com'), ('岩崎', 'iwasaki@example.com'),
                ('根岸', 'negishi@example.com'), ('添田', 'soeda@example.com'),
                ('山浦', 'yamaura@example.com'), ('福田', 'fukuda@example.com')
            ]
            # executemanyで一括挿入
            cursor.executemany("INSERT INTO users (username, email) VALUES (%s, %s)", users_to_add)
            print(f" -> {len(users_to_add)}名のテストユーザーを追加しました。")

        # --- カラムの自動追加処理 (PostgreSQL版) ---
        # (jobsテーブル)
        if not column_exists('jobs', 'assigned_user_id'):
            cursor.execute("ALTER TABLE jobs ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
        if not column_exists('jobs', 'is_hidden'):
            cursor.execute("ALTER TABLE jobs ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")

        # (engineersテーブル)
        if not column_exists('engineers', 'assigned_user_id'):
            cursor.execute("ALTER TABLE engineers ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
        if not column_exists('engineers', 'is_hidden'):
            cursor.execute("ALTER TABLE engineers ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")

        # (matching_resultsテーブル)
        if not column_exists('matching_results', 'proposal_text'):
            cursor.execute("ALTER TABLE matching_results ADD COLUMN proposal_text TEXT")
        if not column_exists('matching_results', 'grade'):
            cursor.execute("ALTER TABLE matching_results ADD COLUMN grade TEXT")
        if not column_exists('matching_results', 'positive_points'):
            cursor.execute("ALTER TABLE matching_results ADD COLUMN positive_points TEXT")
        if not column_exists('matching_results', 'concern_points'):
            cursor.execute("ALTER TABLE matching_results ADD COLUMN concern_points TEXT")
        if not column_exists('matching_results', 'status'):
            cursor.execute("ALTER TABLE matching_results ADD COLUMN status TEXT DEFAULT '新規'")

        conn.commit()
        print("Database initialized and schema verified for PostgreSQL successfully.")

    except Exception as e:
        print(f"❌ データベース初期化中にエラーが発生しました: {e}")
        conn.rollback()
    finally:
        # カーソルと接続を閉じる
        if 'cursor' in locals() and not cursor.closed:
            cursor.close()
        if 'conn' in locals() and not conn.closed:
            conn.close()



def get_db_connection():
    """
    PostgreSQLデータベースへの接続を取得します。
    接続情報は Streamlit の Secrets から読み込みます。
    """
    try:
        conn_string = st.secrets["DATABASE_URL"]
        conn = psycopg2.connect(conn_string)
        # カラム名でアクセスできるように cursor_factory を設定
        conn.cursor_factory = DictCursor
        return conn
    except Exception as e:
        st.error(f"データベース接続エラー: {e}")
        st.info("Supabaseの接続情報がStreamlitのSecretsに正しく設定されているか確認してください。")
        st.stop()


#def get_db_connection():
#    """
#    データベース接続を取得します。
#    row_factoryを設定し、カラム名でアクセスできるようにします。
#    """
#    conn = sqlite3.connect(DB_FILE)
#    # ▼▼▼【この一行を追加・修正します】▼▼▼
#    conn.row_factory = sqlite3.Row
#    # ▲▲▲【この一行を追加・修正します】▲▲▲
#    return conn


#def get_db_connection():
#    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; return conn



def update_job_source_json(job_id, new_json_str):
    """
    指定された案件IDのsource_data_jsonを更新する。
    
    Args:
        job_id (int): 更新対象の案件ID。
        new_json_str (str): 更新後の新しいJSON文字列。
        
    Returns:
        bool: 更新が成功した場合はTrue、失敗した場合はFalse。
    """
    conn = get_db_connection()
    try:
        sql = "UPDATE jobs SET source_data_json = ? WHERE id = ?"
        cur = conn.cursor()
        cur.execute(sql, (new_json_str, job_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"データベース更新エラー: {e}")
        conn.rollback() # エラーが発生した場合は変更を元に戻す
        return False
    finally:
        if conn:
            conn.close()


def split_text_with_llm(text_content):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as f:
            prompt_template = f.read()
        prompt = prompt_template.replace('{text_content}', text_content)
    except FileNotFoundError:
        st.error("エラー: `prompt.txt` ファイルが見つかりません。`backend.py` と同じ場所に作成してください。")
        return None
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        with st.spinner("LLMがテキストを解析・構造化中..."):
            response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        raw_text = response.text
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        if start_index != -1 and end_index != -1 and start_index < end_index:
            json_str = raw_text[start_index : end_index + 1]
            return json.loads(json_str)
        else:
            st.error("LLMの応答から有効なJSON形式を抽出できませんでした。"); st.error("LLMからの生レスポンス:"); st.code(raw_text, language='text'); return None
    except Exception as e:
        st.error(f"LLMによる構造化に失敗しました: {e}"); st.error("LLMからの生レスポンス:");
        try: st.code(response.text, language='text')
        except NameError: st.text("レスポンスの取得にも失敗しました。")
        return None

@st.cache_data # 【この一行を追加するだけ】
def get_match_summary_with_llm(job_doc, engineer_doc):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    prompt = f"""
あなたは、経験豊富なIT人材紹介のエージェントです。
あなたの仕事は、提示された「案件情報」と「技術者情報」を比較し、客観的かつ具体的なマッチング評価を行うことです。
# 絶対的なルール
- `summary`は最も重要な項目です。絶対に省略せず、必ずS, A, B, C, Dのいずれかの文字列を返してください。
- ポジティブな点や懸念点が一つもない場合でも、その旨を正直に記載するか、空のリスト `[]` を返してください。
# 指示
以下の2つの情報を分析し、ポジティブな点と懸念点をリストアップしてください。最終的に、総合評価（summary）をS, A, B, C, Dの5段階で判定してください。
- S: 完璧なマッチ, A: 非常に良いマッチ, B: 良いマッチ, C: 検討の余地あり, D: ミスマッチ
# JSON出力形式
{{
  "summary": "S, A, B, C, Dのいずれか",
  "positive_points": ["スキル面での合致点"],
  "concern_points": ["スキル面での懸念点"]
}}
---
# 案件情報
{job_doc}
---
# 技術者情報
{engineer_doc}
---
"""
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        with st.spinner("AIがマッチング根拠を分析中..."):
            response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        raw_text = response.text
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        if start_index != -1 and end_index != -1 and start_index < end_index:
            json_str = raw_text[start_index : end_index + 1]
            return json.loads(json_str)
        else:
            st.error("評価の分析中にLLMが有効なJSONを返しませんでした。"); st.code(raw_text); return None
    except Exception as e:
        st.error(f"根拠の分析中にエラー: {e}"); return None

def update_index(index_path, items):
    embedding_model = load_embedding_model()
    if not embedding_model or not items: return
    dimension = embedding_model.get_sentence_embedding_dimension()
    index_map = faiss.IndexIDMap(faiss.IndexFlatIP(dimension))
    ids = np.array([item['id'] for item in items], dtype=np.int64)
    bodies = [str(item['document']).split('\n---\n', 1)[-1] for item in items]
    texts_with_prefix = ["passage: " + body for body in bodies]
    embeddings = embedding_model.encode(texts_with_prefix, normalize_embeddings=True, show_progress_bar=False)
    index_map.add_with_ids(embeddings, ids)
    faiss.write_index(index_map, index_path)

def search(query_text, index_path, top_k=5):
    embedding_model = load_embedding_model()
    if not embedding_model or not os.path.exists(index_path): return [], []
    index = faiss.read_index(index_path)
    if index.ntotal == 0: return [], []
    query_body = query_text.split('\n---\n', 1)[-1]
    prefixed_query = "query: " + query_body
    query_vector = embedding_model.encode([prefixed_query], normalize_embeddings=True).reshape(1, -1)
    similarities, ids = index.search(query_vector, min(top_k, index.ntotal))
    valid_ids = [int(i) for i in ids[0] if i != -1]
    valid_similarities = [similarities[0][j] for j, i in enumerate(ids[0]) if i != -1]
    return valid_similarities, valid_ids

def get_records_by_ids(table_name, ids):
    if not ids: return []
    with get_db_connection() as conn:
        placeholders = ','.join('?' for _ in ids)
        query = f"SELECT * FROM {table_name} WHERE id IN ({placeholders})"
        results = conn.execute(query, ids).fetchall()
        results_map = {res['id']: res for res in results}
        return [results_map[id] for id in ids if id in results_map]

def run_matching_for_item(item_data, item_type, cursor, now_str):
    """
    指定された案件または技術者データに対して、類似候補を検索し、LLMによる評価を行った上でマッチング結果をDBに保存する。
    LLMの評価が 'S', 'A', 'B', 'C' の場合のみDBに保存し、'D', 'E' などそれ以外の場合はスキップする。
    ログには案件名・技術者名を表示し、可読性を高める。
    """
    # 1. 検索対象のインデックス、テーブル、名称を決定
    if item_type == 'job':
        query_text, index_path = item_data['document'], ENGINEER_INDEX_FILE
        candidate_table = 'engineers'
        # item_data は辞書なので .get() が安全
        source_name = item_data.get('project_name', f"案件ID:{item_data['id']}")
    else:  # item_type == 'engineer'
        query_text, index_path = item_data['document'], JOB_INDEX_FILE
        candidate_table = 'jobs'
        # item_data は辞書なので .get() が安全
        source_name = item_data.get('name', f"技術者ID:{item_data['id']}")

    # 2. Faissによる類似度検索を実行
    similarities, ids = search(query_text, index_path, top_k=TOP_K_CANDIDATES)
    if not ids:
        st.write(f"▶ 『{source_name}』(ID:{item_data['id']}, {item_type}) の類似候補は見つかりませんでした。")
        return

    # 3. 検索結果の候補データをDBから一括取得
    candidate_records = get_records_by_ids(candidate_table, ids)
    candidate_map = {record['id']: record for record in candidate_records}

    st.write(f"▶ 『{source_name}』(ID:{item_data['id']}, {item_type}) との類似候補 {len(ids)}件を評価します。")

    # 4. 各候補をループして評価と保存処理
    for sim, candidate_id in zip(similarities, ids):
        score = float(sim) * 100

        if score < MIN_SCORE_THRESHOLD:
            continue

        candidate_record = candidate_map.get(candidate_id)
        if not candidate_record:
            st.write(f"  - 候補ID:{candidate_id} のデータがDBから取得できなかったため、スキップします。")
            continue

        # ▼▼▼【ここが修正箇所です】▼▼▼
        # candidate_record は sqlite3.Row オブジェクトのため、.get() ではなくキーでアクセスする
        if candidate_table == 'jobs':
            candidate_name = candidate_record['project_name'] if candidate_record['project_name'] else f"案件ID:{candidate_id}"
        else:  # 'engineers'
            candidate_name = candidate_record['name'] if candidate_record['name'] else f"技術者ID:{candidate_id}"
        # ▲▲▲【修正箇所はここまでです】▲▲▲

        # 5. LLM評価のための案件・技術者情報を準備
        if item_type == 'job':
            job_doc = item_data['document']
            engineer_doc = candidate_record['document']
            job_id = item_data['id']
            engineer_id = candidate_record['id']
        else:  # item_type == 'engineer'
            job_doc = candidate_record['document']
            engineer_doc = item_data['document']
            job_id = candidate_record['id']
            engineer_id = item_data['id']

        # 6. LLMによるマッチング評価を実行
        llm_result = get_match_summary_with_llm(job_doc, engineer_doc)

        # 7. LLMの評価結果に基づいてDBへの保存を判断
        if llm_result and 'summary' in llm_result:
            grade = llm_result.get('summary')

            if grade in ['S', 'A', 'B']:
                cursor.execute(
                    'INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade) VALUES (?, ?, ?, ?, ?)',
                    (job_id, engineer_id, score, now_str, grade)
                )
                st.write(f"  - 候補: 『{candidate_name}』(ID:{candidate_id}) -> マッチング評価: {grade} (スコア: {score:.2f}) ... ✅ DBに保存しました。")
            else:
                st.write(f"  - 候補: 『{candidate_name}』(ID:{candidate_id}) -> マッチング評価: {grade} (スコア: {score:.2f}) ... ❌ スキップしました。")
        else:
            st.write(f"  - 候補: 『{candidate_name}』(ID:{candidate_id}) -> LLM評価に失敗したためスキップします。")





def process_single_content(source_data: dict):
    if not source_data: st.warning("処理するデータが空です。"); return False
    valid_attachments_content = []
    for att in source_data.get('attachments', []):
        content = att.get('content', '')
        if content and not content.startswith("[") and not content.endswith("]"):
             valid_attachments_content.append(f"\n\n--- 添付ファイル: {att['filename']} ---\n{content}")
        else:
            st.write(f"⚠️ 添付ファイル '{att['filename']}' は内容を抽出できなかったため、解析から除外します。")
    full_text_for_llm = source_data.get('body', '') + "".join(valid_attachments_content)
    if not full_text_for_llm.strip(): st.warning("解析対象のテキストがありません。"); return False
    parsed_data = split_text_with_llm(full_text_for_llm)
    if not parsed_data: return False
    new_jobs_data = parsed_data.get("jobs", []); new_engineers_data = parsed_data.get("engineers", [])
    if not new_jobs_data and not new_engineers_data: st.warning("LLMはテキストから案件情報または技術者情報を抽出できませんでした。"); return False
    with get_db_connection() as conn:
        cursor = conn.cursor(); now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        source_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
        newly_added_jobs, newly_added_engineers = [], []
        
        for item_data in new_jobs_data:
            doc = item_data.get("document")
            project_name = item_data.get("project_name", "名称未定の案件") # 名前を取得
            if not (doc and str(doc).strip() and str(doc).lower() != 'none'): doc = full_text_for_llm
            
            #meta_info = f"[国籍要件: {item_data.get('nationality_requirement', '不明')}] [開始時期: {item_data.get('start_date', '不明')}]\n---\n"; full_document = meta_info + doc
            
            meta_info = _build_meta_info_string('job', item_data)
            full_document = meta_info + doc



            cursor.execute('INSERT INTO jobs (project_name, document, source_data_json, created_at) VALUES (?, ?, ?, ?)', (project_name, full_document, source_json_str, now_str));
            item_data['id'] = cursor.lastrowid; item_data['document'] = full_document; newly_added_jobs.append(item_data)
        
        for item_data in new_engineers_data:
            doc = item_data.get("document")
            engineer_name = item_data.get("name", "名称不明の技術者") # 名前を取得
            if not (doc and str(doc).strip() and str(doc).lower() != 'none'): doc = full_text_for_llm
            
            #meta_info = f"[国籍: {item_data.get('nationality', '不明')}] [稼働可能日: {item_data.get('start_date', '不明')}]\n---\n"; full_document = meta_info + doc

            meta_info = _build_meta_info_string('engineer', item_data)
            full_document = meta_info + doc

            
            cursor.execute('INSERT INTO engineers (name, document, source_data_json, created_at) VALUES (?, ?, ?, ?)', (engineer_name, full_document, source_json_str, now_str));
            item_data['id'] = cursor.lastrowid; item_data['document'] = full_document; newly_added_engineers.append(item_data)

        st.write("ベクトルインデックスを更新し、マッチング処理を開始します...")

        #all_jobs = conn.execute('SELECT id, document FROM jobs').fetchall()
        #all_engineers = conn.execute('SELECT id, document FROM engineers').fetchall()
        #if all_jobs: update_index(JOB_INDEX_FILE, all_jobs)
        #if all_engineers: update_index(ENGINEER_INDEX_FILE, all_engineers)

        # ▼▼▼ 修正点: is_hidden = 0 のアイテムのみを対象にインデックスを更新 ▼▼▼
        all_active_jobs = conn.execute('SELECT id, document FROM jobs WHERE is_hidden = 0').fetchall()
        all_active_engineers = conn.execute('SELECT id, document FROM engineers WHERE is_hidden = 0').fetchall()
        
        if all_active_jobs: update_index(JOB_INDEX_FILE, all_active_jobs)
        if all_active_engineers: update_index(ENGINEER_INDEX_FILE, all_active_engineers)
        # ▲▲▲ 修正点 ここまで ▲▲▲


        for new_job in newly_added_jobs: run_matching_for_item(new_job, 'job', cursor, now_str)
        for new_engineer in newly_added_engineers: run_matching_for_item(new_engineer, 'engineer', cursor, now_str)
    return True

def extract_text_from_pdf(file_bytes):
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc: text = "".join(page.get_text() for page in doc)
        return text if text.strip() else "[PDFテキスト抽出失敗: 内容が空または画像PDF]"
    except Exception as e: return f"[PDFテキスト抽出エラー: {e}]"

def extract_text_from_docx(file_bytes):
    try:
        doc = docx.Document(io.BytesIO(file_bytes)); text = "\n".join([para.text for para in doc.paragraphs])
        return text if text.strip() else "[DOCXテキスト抽出失敗: 内容が空]"
    except Exception as e: return f"[DOCXテキスト抽出エラー: {e}]"

def get_email_contents(msg) -> dict:
    body_text = ""; attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type(); content_disposition = str(part.get("Content-Disposition"))
            if 'text/plain' in content_type and 'attachment' not in content_disposition:
                charset = part.get_content_charset()
                try: body_text += part.get_payload(decode=True).decode(charset if charset else 'utf-8', errors='ignore')
                except Exception: body_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
            if 'attachment' in content_disposition:
                raw_filename = part.get_filename()
                if raw_filename:
                    decoded_header = decode_header(raw_filename)
                    filename = "".join([s.decode(c or 'utf-8', 'ignore') if isinstance(s, bytes) else s for s, c in decoded_header])
                    st.write(f"📄 添付ファイル '{filename}' を発見しました。")
                    file_bytes = part.get_payload(decode=True)
                    lower_filename = filename.lower()
                    if lower_filename.endswith(".pdf"): attachments.append({"filename": filename, "content": extract_text_from_pdf(file_bytes)})
                    elif lower_filename.endswith(".docx"): attachments.append({"filename": filename, "content": extract_text_from_docx(file_bytes)})
                    elif lower_filename.endswith(".txt"): attachments.append({"filename": filename, "content": file_bytes.decode('utf-8', errors='ignore')})
                    else: st.write(f"ℹ️ 添付ファイル '{filename}' は未対応の形式のため、テキスト抽出をスキップします。")
    else:
        charset = msg.get_content_charset()
        try: body_text = msg.get_payload(decode=True).decode(charset if charset else 'utf-8', errors='ignore')
        except Exception: body_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    return {"body": body_text.strip(), "attachments": attachments}

def fetch_and_process_emails():
    log_stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(log_stream):
            try: SERVER, USER, PASSWORD = st.secrets["EMAIL_SERVER"], st.secrets["EMAIL_USER"], st.secrets["EMAIL_PASSWORD"]
            except KeyError as e: st.error(f"メールサーバーの接続情報がSecretsに設定されていません: {e}"); return False, log_stream.getvalue()
            try: mail = imaplib.IMAP4_SSL(SERVER); mail.login(USER, PASSWORD); mail.select('inbox')
            except Exception as e: st.error(f"メールサーバーへの接続またはログインに失敗しました: {e}"); return False, log_stream.getvalue()
            total_processed_count = 0; checked_count = 0
            try:
                with st.status("最新の未読メールを取得・処理中...", expanded=True) as status:
                    _, messages = mail.search(None, 'UNSEEN')
                    email_ids = messages[0].split()
                    if not email_ids: st.write("処理対象の未読メールは見つかりませんでした。")
                    else:
                        latest_ids = email_ids[::-1][:10]; checked_count = len(latest_ids)
                        st.write(f"最新の未読メール {checked_count}件をチェックします。")
                        for i, email_id in enumerate(latest_ids):
                            _, msg_data = mail.fetch(email_id, '(RFC822)')
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    msg = email.message_from_bytes(response_part[1])
                                    source_data = get_email_contents(msg)
                                    if source_data['body'] or source_data['attachments']:
                                        st.write(f"✅ メールID {email_id.decode()} は処理対象です。解析を開始します...")
                                        if process_single_content(source_data):
                                            total_processed_count += 1; mail.store(email_id, '+FLAGS', '\\Seen')
                                    else: st.write(f"✖️ メールID {email_id.decode()} は本文も添付ファイルも無いため、スキップします。")
                            st.write(f"({i+1}/{checked_count}) チェック完了")
                    status.update(label="メールチェック完了", state="complete")
            finally: mail.close(); mail.logout()
        if checked_count > 0:
            if total_processed_count > 0: st.success(f"チェックした {checked_count} 件のメールのうち、{total_processed_count} 件からデータを抽出し、保存しました。"); st.balloons()
            else: st.warning(f"メールを {checked_count} 件チェックしましたが、データベースに保存できる情報は見つかりませんでした。")
        else: st.info("処理対象となる新しい未読メールはありませんでした。")
        return True, log_stream.getvalue()
    except Exception as e:
        st.error(f"予期せぬエラーが発生しました: {e}"); return False, log_stream.getvalue()

def hide_match(result_id):
    if not result_id: st.warning("非表示にするマッチング結果のIDが指定されていません。"); return False
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE matching_results SET is_hidden = 1 WHERE id = ?', (result_id,))
            conn.commit()
            if cursor.rowcount > 0: st.toast(f"マッチング結果 (ID: {result_id}) を非表示にしました。"); return True
            else: st.warning(f"マッチング結果 (ID: {result_id}) が見つかりませんでした。"); return False
    except sqlite3.Error as e: st.error(f"データベースの更新中にエラーが発生しました: {e}"); return False
    except Exception as e: st.error(f"hide_match関数で予期せぬエラーが発生しました: {e}"); return False

def get_all_users():
    """
    全てのユーザー情報を取得する。
    
    Returns:
        list: ユーザー情報の辞書を要素とするリスト。
    """
    conn = get_db_connection()
    # conn.row_factory = sqlite3.Row が get_db_connection で設定されている前提
    users = conn.execute("SELECT id, username FROM users ORDER BY id").fetchall()
    conn.close()
    return users

def assign_user_to_job(job_id, user_id):
    """
    案件に担当者を割り当てる。
    
    Args:
        job_id (int): 対象の案件ID。
        user_id (int or None): 割り当てるユーザーのID。Noneの場合は割り当て解除。
        
    Returns:
        bool: 更新が成功した場合はTrue、失敗した場合はFalse。
    """
    conn = get_db_connection()
    try:
        sql = "UPDATE jobs SET assigned_user_id = ? WHERE id = ?"
        cur = conn.cursor()
        cur.execute(sql, (user_id, job_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"担当者割り当てエラー: {e}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def set_job_visibility(job_id, is_hidden):
    """
    案件の表示/非表示状態を更新する。
    
    Args:
        job_id (int): 対象の案件ID。
        is_hidden (int): 0なら表示、1なら非表示。
        
    Returns:
        bool: 更新が成功した場合はTrue、失敗した場合はFalse。
    """
    conn = get_db_connection()
    try:
        sql = "UPDATE jobs SET is_hidden = ? WHERE id = ?"
        cur = conn.cursor()
        cur.execute(sql, (is_hidden, job_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"表示状態の更新エラー: {e}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# 【ここから追加】 --- 技術者向けのバックエンド関数 ---

def assign_user_to_engineer(engineer_id, user_id):
    """技術者に担当者を割り当てる。"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE engineers SET assigned_user_id = ? WHERE id = ?", (user_id, engineer_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"技術者への担当者割り当てエラー: {e}"); conn.rollback(); return False
    finally:
        conn.close()

def set_engineer_visibility(engineer_id, is_hidden):
    """技術者の表示/非表示状態を更新する (0:表示, 1:非表示)。"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE engineers SET is_hidden = ? WHERE id = ?", (is_hidden, engineer_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"技術者の表示状態の更新エラー: {e}"); conn.rollback(); return False
    finally:
        conn.close()

def update_engineer_source_json(engineer_id, new_json_str):
    """技術者のsource_data_jsonを更新する。"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE engineers SET source_data_json = ? WHERE id = ?", (new_json_str, engineer_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"技術者のJSONデータ更新エラー: {e}"); conn.rollback(); return False
    finally:
        conn.close()


def generate_proposal_reply_with_llm(job_summary, engineer_summary, engineer_name, project_name):
    """
    LLMを使用して、クライアントへの技術者提案メール文案を生成します。

    Args:
        job_summary (str): 案件の要約テキスト。
        engineer_summary (str): 技術者の要約テキスト。
        engineer_name (str): 技術者の名前。
        project_name (str): 案件名。

    Returns:
        str: 生成されたメール文案、またはエラーメッセージ。
    """


    # 必要な情報が揃っているか確認
    if not all([job_summary, engineer_summary, engineer_name, project_name]):
        return "情報が不足しているため、提案メールを生成できませんでした。"

    # AIへの指示（プロンプト）
    prompt = f"""
あなたは、クライアントに優秀な技術者を提案する、経験豊富なIT営業担当者です。
以下の案件情報と技術者情報をもとに、クライアントの心に響く、丁寧で説得力のある提案メールの文面を作成してください。

# 役割
- 優秀なIT営業担当者

# 指示
- 最初に、提案する技術者名と案件名を記載した件名を作成してください (例: 件名: 【〇〇様のご提案】〇〇プロジェクトの件)。
- 技術者のスキルや経験が、案件のどの要件に具体的にマッチしているかを明確に示してください。
- ポジティブな点（適合スキル）を強調し、技術者の魅力を最大限に伝えてください。
- 懸念点（スキルミスマッチや経験不足）がある場合は、正直に触れつつも、学習意欲や類似経験、ポテンシャルなどでどのようにカバーできるかを前向きに説明してください。
- 全体として、プロフェッショナルかつ丁寧なビジネスメールのトーンを維持してください。
- 最後に、ぜひ一度、オンラインでの面談の機会を設けていただけますようお願いする一文で締めくくってください。
- 出力は、件名と本文を含んだメール形式のテキストのみとしてください。余計な解説は不要です。

# 案件情報
{job_summary}

# 技術者情報
{engineer_summary}

# 提案する技術者の名前
{engineer_name}

# 案件名
{project_name}

---
それでは、上記の指示に基づいて、最適な提案メールを作成してください。
"""

    try:
        # st.secrets等でAPIキーを管理していることを想定
        # genai.configure(api_key=st.secrets["google_api_key"])
        #model = genai.GenerativeModel('gemini-2.5-pro')
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        # 本番環境では logging を使用することを推奨します
        print(f"Error generating proposal reply with LLM: {e}")
        return f"提案メールの生成中にエラーが発生しました: {e}"



def save_match_grade(match_id, grade):
    """
    指定されたマッチングIDに対して、AI評価の等級を保存します。

    Args:
        match_id (int): matching_resultsテーブルのID。
        grade (str): 保存する評価（'A', 'B'など）。

    Returns:
        bool: 保存が成功した場合はTrue、失敗した場合はFalse。
    """
    if not grade:  # gradeが空の場合は何もしない
        return False
        
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            "UPDATE matching_results SET grade = ? WHERE id = ?",
            (grade, match_id)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error saving match grade for match_id {match_id}: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def get_evaluation_html(grade, font_size='2.5em'):
    """
    評価（A-E）に基づいて色とスタイルが適用されたHTMLを生成します。
    """
    if not grade: return ""
    color_map = {'A': '#28a745', 'B': '#17a2b8', 'C': '#ffc107', 'D': '#fd7e14', 'E': '#dc3545'}
    color = color_map.get(grade.upper(), '#6c757d') 
    style = f"color: {color}; font-size: {font_size}; font-weight: bold; text-align: center; line-height: 1; padding-top: 10px;"
    # HTML構造もダッシュボードと同じにする
    html_code = f"<div style='text-align: center; margin-bottom: 5px;'><span style='{style}'>{grade.upper()}</span></div><div style='text-align: center; font-size: 0.8em; color: #888;'>判定</div>"
    return html_code


# ... (backend.pyの既存コード) ...

def get_matching_result_details(result_id):
    """
    指定されたマッチング結果IDの詳細情報（マッチング、案件、技術者）を取得する。
    案件、技術者情報には担当者名も含む。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # matching_results を取得
        cursor.execute("SELECT * FROM matching_results WHERE id = ?", (result_id,))
        match_result = cursor.fetchone()

        if not match_result:
            return None

        # job 情報を取得 (担当者名を含むようにJOIN)
        job_query = "SELECT j.*, u.username as assignee_name FROM jobs j LEFT JOIN users u ON j.assigned_user_id = u.id WHERE j.id = ?"
        cursor.execute(job_query, (match_result['job_id'],))
        job_data = cursor.fetchone()

        # engineer 情報を取得 (担当者名を含むようにJOIN)
        engineer_query = "SELECT e.*, u.username as assignee_name FROM engineers e LEFT JOIN users u ON e.assigned_user_id = u.id WHERE e.id = ?"
        cursor.execute(engineer_query, (match_result['engineer_id'],))
        engineer_data = cursor.fetchone()

        return {
            "match_result": dict(match_result), # sqlite3.Row を dict に変換
            "job_data": dict(job_data) if job_data else None,
            "engineer_data": dict(engineer_data) if engineer_data else None,
        }
    except sqlite3.Error as e:
        print(f"マッチング詳細取得エラー: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ... (backend.pyの既存コードの続き) ...





def re_evaluate_and_match_single_engineer(engineer_id):
    """
    指定された単一の技術者IDに対して、AIによる再評価と再マッチングを実行する。
    1. 最新のsource_data_jsonからドキュメントを再生成する。
    2. jobsテーブルとengineersテーブルのインデックスを更新する。
    3. run_matching_for_itemを呼び出して、全案件とのマッチングを再実行する。
    """
    conn = get_db_connection()
    try:
        # 1. 対象技術者の最新情報を取得
        engineer_record = conn.execute("SELECT * FROM engineers WHERE id = ?", (engineer_id,)).fetchone()
        if not engineer_record:
            st.error(f"技術者ID:{engineer_id} が見つかりませんでした。")
            return False

        source_data = json.loads(engineer_record['source_data_json'])
        full_text_for_llm = source_data.get('body', '')
        # 添付ファイルの内容も結合（もしあれば）
        for att in source_data.get('attachments', []):
            content = att.get('content', '')
            if content and not content.startswith("[") and not content.endswith("]"):
                full_text_for_llm += f"\n\n--- 添付ファイル: {att['filename']} ---\n{content}"

        # 2. LLMでドキュメントを再生成
        parsed_data = split_text_with_llm(full_text_for_llm)
        if not parsed_data or not parsed_data.get("engineers"):
            st.error("LLMによる再評価で、技術者情報の抽出に失敗しました。")
            return False

        # 複数抽出される可能性を考慮し、最初のものを使用する
        item_data = parsed_data["engineers"][0]
        doc = item_data.get("document")
        if not (doc and str(doc).strip() and str(doc).lower() != 'none'):
            doc = full_text_for_llm
        
        #meta_info = f"[国籍: {item_data.get('nationality', '不明')}] [稼働可能日: {item_data.get('start_date', '不明')}]\n---\n"

        meta_info = _build_meta_info_string('engineer', item_data)


        new_full_document = meta_info + doc
        
        # 3. データベースのドキュメントを更新
        cursor = conn.cursor()
        cursor.execute("UPDATE engineers SET document = ? WHERE id = ?", (new_full_document, engineer_id))
        
        # 4. 既存の関連マッチング結果を一旦削除（重複を避けるため）
        cursor.execute("DELETE FROM matching_results WHERE engineer_id = ?", (engineer_id,))
        st.write(f"技術者ID:{engineer_id} の既存マッチング結果をクリアしました。")

        # 5. インデックスを更新し、再マッチングを実行
        st.write("ベクトルインデックスを更新し、再マッチング処理を開始します...")
        all_jobs = conn.execute('SELECT id, document FROM jobs WHERE is_hidden = 0').fetchall()
        all_engineers = conn.execute('SELECT id, document FROM engineers WHERE is_hidden = 0').fetchall()
        if all_jobs: update_index(JOB_INDEX_FILE, all_jobs)
        if all_engineers: update_index(ENGINEER_INDEX_FILE, all_engineers)

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # run_matching_for_item に渡すためのデータ構造を整える
        engineer_data_for_matching = {
            'id': engineer_id,
            'document': new_full_document,
            'name': engineer_record['name']
        }
        run_matching_for_item(engineer_data_for_matching, 'engineer', cursor, now_str)
        
        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        st.error(f"再評価・再マッチング中にエラーが発生しました: {e}")
        return False
    finally:
        if conn:
            conn.close()


def update_engineer_name(engineer_id, new_name):
    """
    指定された技術者IDの氏名を更新する。
    """
    if not new_name or not new_name.strip():
        print("エラー: 新しい氏名が空です。")
        return False
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE engineers SET name = ? WHERE id = ?", (new_name.strip(), engineer_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"技術者氏名の更新エラー: {e}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()




def _build_meta_info_string(item_type, item_data):
    """メタ情報文字列を生成する共通ヘルパー関数"""
    
    if item_type == 'job':
        # 案件から抽出したいメタ情報を定義
        meta_fields = [
            ["国籍要件", "nationality_requirement"],
            ["開始時期", "start_date"],
            ["勤務地", "location"],
            ["単価", "unit_price"],
            ["必須スキル", "required_skills"]
        ]
    elif item_type == 'engineer':
        # 技術者から抽出したいメタ情報を定義
        meta_fields = [
            ["国籍", "nationality"],
            ["稼働可能日", "availability_date"],
            ["希望勤務地", "desired_location"],
            ["希望単価", "desired_salary"],
            ["主要スキル", "main_skills"]
        ]
    else:
        return "\n---\n" # 不明なタイプの場合は空

    meta_parts = []
    for display_name, key in meta_fields:
        value = item_data.get(key, '不明')
        meta_parts.append(f"[{display_name}: {value}]")
    
    return " ".join(meta_parts) + "\n---\n"


def update_match_status(match_id, new_status):
    """
    指定されたマッチングIDのステータスを更新する。
    """
    if not match_id or not new_status:
        return False
    
    with get_db_connection() as conn:
        try:
            conn.execute("UPDATE matching_results SET status = ? WHERE id = ?", (new_status, match_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"ステータスの更新エラー: {e}")
            conn.rollback()
            return False