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
TOP_K_CANDIDATES = 50
MIN_SCORE_THRESHOLD = 90.0 # 推奨値に設定

@st.cache_data
def load_app_config():
    try:
        with open("config.toml", "r", encoding="utf-8") as f: return toml.load(f)
    except FileNotFoundError: return {"app": {"title": "Universal AI Agent"}}

@st.cache_resource
def load_embedding_model():
    try: return SentenceTransformer(MODEL_NAME)
    except Exception as e: st.error(f"埋め込みモデル '{MODEL_NAME}' の読み込みに失敗しました: {e}"); return None

# ▼▼▼【修正箇所】テーブルに新しい列を追加 ▼▼▼
def init_database():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # jobsテーブルに project_name 列を追加
        cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, project_name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT)')
        # engineersテーブルに name 列を追加
        cursor.execute('CREATE TABLE IF NOT EXISTS engineers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS matching_results (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, engineer_id INTEGER, score REAL, created_at TEXT, is_hidden INTEGER DEFAULT 0, FOREIGN KEY (job_id) REFERENCES jobs (id), FOREIGN KEY (engineer_id) REFERENCES engineers (id))')
        cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        email TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
        
        cursor.execute("SELECT COUNT(*) FROM users")

        user_count = cursor.fetchone()[0]
        if user_count == 0:
            print("初回起動のため、テストユーザーを追加します...")
            cursor.execute("INSERT INTO users (username, email) VALUES (?, ?)", ('熊崎', 'yamada@example.com'))
            cursor.execute("INSERT INTO users (username, email) VALUES (?, ?)", ('岩本', 'suzuki@example.com'))
            cursor.execute("INSERT INTO users (username, email) VALUES (?, ?)", ('小関', 'sato@example.com'))
            print(" -> 3名のテストユーザーを追加しました。")


    # --- 2. jobs テーブルに assigned_user_id カラムを追加 ---
    try:
        # jobs テーブルのカラム情報を取得
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # カラムが存在しない場合のみ追加
        if 'assigned_user_id' not in columns:
            print("`jobs` テーブルに `assigned_user_id` カラムが見つかりません。追加します...")
            cursor.execute("ALTER TABLE jobs ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
            print("✅ `assigned_user_id` カラムを追加しました。")
        else:
            print("✅ `assigned_user_id` カラムは既に存在します。")
            
    except sqlite3.Error as e:
        print(f"❌ `jobs` テーブルへのカラム追加中にエラーが発生しました: {e}")


  # --- 4. jobs テーブルに is_hidden カラムを追加 ---
    try:
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # 'is_hidden' カラムが存在しない場合のみ追加
        # 0 = 表示, 1 = 非表示。デフォルトは 0 (表示)
        if 'is_hidden' not in columns:
            print("`jobs` テーブルに `is_hidden` カラムが見つかりません。追加します...")
            cursor.execute("ALTER TABLE jobs ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
            print("✅ `is_hidden` カラムを追加し、デフォルト値を 0 (表示) に設定しました。")
        else:
            print("✅ `is_hidden` カラムは既に存在します。")
            
    except sqlite3.Error as e:
        print(f"❌ `jobs` テーブルへの is_hidden カラム追加中にエラーが発生しました: {e}")

 # 【ここから追加】 --- engineers テーブルのカラム追加 ---
    try:
        cursor.execute("PRAGMA table_info(engineers)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # assigned_user_id カラム (技術者の担当者)
        if 'assigned_user_id' not in columns:
            print("`engineers` テーブルに `assigned_user_id` カラムを追加します...")
            cursor.execute("ALTER TABLE engineers ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
            print("✅ `assigned_user_id` カラムを追加しました。")
        
        # is_hidden カラム (技術者の表示/非表示)
        if 'is_hidden' not in columns:
            print("`engineers` テーブルに `is_hidden` カラムを追加します...")
            cursor.execute("ALTER TABLE engineers ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
            print("✅ `is_hidden` カラムを追加し、デフォルト値を 0 (表示) に設定しました。")
            
    except sqlite3.Error as e:
        print(f"❌ `engineers` テーブルへのカラム追加中にエラーが発生しました: {e}")



def get_db_connection():
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; return conn



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
    model = genai.GenerativeModel('models/gemini-2.5-pro')
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

def get_match_summary_with_llm(job_doc, engineer_doc):
    model = genai.GenerativeModel('models/gemini-2.5-pro')
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
    if item_type == 'job': query_text, index_path = item_data['document'], ENGINEER_INDEX_FILE
    else: query_text, index_path = item_data['document'], JOB_INDEX_FILE
    similarities, ids = search(query_text, index_path, top_k=TOP_K_CANDIDATES)
    st.write(f"▶ ID:{item_data['id']} ({item_type}) の類似候補 {len(ids)}件を評価します。")
    for sim, candidate_id in zip(similarities, ids):
        score = float(sim) * 100
        if score >= MIN_SCORE_THRESHOLD:
            db_ids = {'job_id': item_data['id'] if item_type == 'job' else candidate_id, 'engineer_id': candidate_id if item_type == 'job' else item_data['id']}
            cursor.execute('INSERT INTO matching_results (job_id, engineer_id, score, created_at) VALUES (?, ?, ?, ?)', (db_ids['job_id'], db_ids['engineer_id'], score, now_str))

# ▼▼▼【修正箇所】新しい列にデータを保存するよう変更 ▼▼▼
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
            meta_info = f"[国籍要件: {item_data.get('nationality_requirement', '不明')}] [開始時期: {item_data.get('start_date', '不明')}]\n---\n"; full_document = meta_info + doc
            cursor.execute('INSERT INTO jobs (project_name, document, source_data_json, created_at) VALUES (?, ?, ?, ?)', (project_name, full_document, source_json_str, now_str));
            item_data['id'] = cursor.lastrowid; item_data['document'] = full_document; newly_added_jobs.append(item_data)
        
        for item_data in new_engineers_data:
            doc = item_data.get("document")
            engineer_name = item_data.get("name", "名称不明の技術者") # 名前を取得
            if not (doc and str(doc).strip() and str(doc).lower() != 'none'): doc = full_text_for_llm
            meta_info = f"[国籍: {item_data.get('nationality', '不明')}] [稼働可能日: {item_data.get('start_date', '不明')}]\n---\n"; full_document = meta_info + doc
            cursor.execute('INSERT INTO engineers (name, document, source_data_json, created_at) VALUES (?, ?, ?, ?)', (engineer_name, full_document, source_json_str, now_str));
            item_data['id'] = cursor.lastrowid; item_data['document'] = full_document; newly_added_engineers.append(item_data)

        st.write("ベクトルインデックスを更新し、マッチング処理を開始します...")
        all_jobs = conn.execute('SELECT id, document FROM jobs').fetchall()
        all_engineers = conn.execute('SELECT id, document FROM engineers').fetchall()
        if all_jobs: update_index(JOB_INDEX_FILE, all_jobs)
        if all_engineers: update_index(ENGINEER_INDEX_FILE, all_engineers)
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