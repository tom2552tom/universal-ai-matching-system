import streamlit as st
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

JOB_INDEX_FILE = "backend_job_index.faiss"
ENGINEER_INDEX_FILE = "backend_engineer_index.faiss"
MODEL_NAME = 'intfloat/multilingual-e5-large'
TOP_K_CANDIDATES = 500
MIN_SCORE_THRESHOLD = 70.0

# --- 2. キャッシュされる関数 ---
@st.cache_data
def load_app_config():
    config_file_path = "config.toml"
    if not os.path.exists(config_file_path):
        st.warning(f"設定ファイル '{config_file_path}' が見つかりません。デフォルト値を使用します。")
        return {}
    try:
        with open(config_file_path, "r", encoding="utf-8") as f:
            return toml.load(f)
    except Exception as e:
        st.error(f"設定ファイルの読み込み中にエラーが発生しました: {e}")
        return {}

@st.cache_resource
def load_embedding_model():
    try: return SentenceTransformer(MODEL_NAME)
    except Exception as e:
        st.error(f"埋め込みモデル '{MODEL_NAME}' の読み込みに失敗しました: {e}")
        return None

# --- 3. データベース接続 ---
def get_db_connection():
    try:
        conn_string = st.secrets["DATABASE_URL"]
        return psycopg2.connect(conn_string)
    except Exception as e:
        st.error(f"データベース接続エラー: {e}")
        st.info("Supabaseの接続情報がStreamlitのSecretsに正しく設定されているか確認してください。")
        st.stop()

# --- 4. データベース初期化・スキーマ管理 ---
def init_database():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                def column_exists(table, column):
                    cursor.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s AND column_name = %s", (table, column))
                    return cursor.fetchone() is not None
                cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id SERIAL PRIMARY KEY, project_name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT, is_hidden INTEGER DEFAULT 0, assigned_user_id INTEGER)')
                cursor.execute('CREATE TABLE IF NOT EXISTS engineers (id SERIAL PRIMARY KEY, name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT, is_hidden INTEGER DEFAULT 0, assigned_user_id INTEGER)')
                cursor.execute('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS matching_results (
                        id SERIAL PRIMARY KEY, job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE, engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
                        score REAL, created_at TEXT, is_hidden INTEGER DEFAULT 0, grade TEXT, positive_points TEXT, concern_points TEXT, proposal_text TEXT,
                        status TEXT DEFAULT '新規', UNIQUE (job_id, engineer_id)
                    )''')
                cursor.execute("SELECT COUNT(*) FROM users")
                if cursor.fetchone()[0] == 0:
                    users_to_add = [('熊崎', 'k@e.com'), ('岩本', 'i@e.com'), ('小関', 'o@e.com'), ('内山', 'u@e.com'), ('島田', 's@e.com'), ('長谷川', 'h@e.com'), ('北島', 'k@e.com'), ('岩崎', 'i@e.com'), ('根岸', 'n@e.com'), ('添田', 's@e.com'), ('山浦', 'y@e.com'), ('福田', 'f@e.com')]
                    cursor.executemany("INSERT INTO users (username, email) VALUES (%s, %s)", users_to_add)
                if not column_exists('jobs', 'assigned_user_id'): cursor.execute("ALTER TABLE jobs ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
                if not column_exists('jobs', 'is_hidden'): cursor.execute("ALTER TABLE jobs ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
                if not column_exists('engineers', 'assigned_user_id'): cursor.execute("ALTER TABLE engineers ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
                if not column_exists('engineers', 'is_hidden'): cursor.execute("ALTER TABLE engineers ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
                if not column_exists('matching_results', 'status'): cursor.execute("ALTER TABLE matching_results ADD COLUMN status TEXT DEFAULT '新規'")
            conn.commit()
            print("Database initialized and schema verified for PostgreSQL successfully.")
    except Exception as e: print(f"❌ データベース初期化中にエラーが発生しました: {e}")

# --- 5. LLM & AI関連 ---
def _build_meta_info_string(item_type, item_data):
    fields = []
    if item_type == 'job':
        fields = [["国籍要件", "nationality_requirement"], ["開始時期", "start_date"], ["勤務地", "location"], ["単価", "unit_price"], ["必須スキル", "required_skills"]]
    elif item_type == 'engineer':
        fields = [["国籍", "nationality"], ["稼働可能日", "availability_date"], ["希望勤務地", "desired_location"], ["希望単価", "desired_salary"], ["主要スキル", "main_skills"]]
    if not fields: return "\n---\n"
    meta_parts = [f"[{name}: {item_data.get(key, '不明')}]" for name, key in fields]
    return " ".join(meta_parts) + "\n---\n"

def split_text_with_llm(text_content):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as f: prompt = f.read().replace('{text_content}', text_content)
    except FileNotFoundError: return None
    config = {"response_mime_type": "application/json"}
    safety = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        response = model.generate_content(prompt, generation_config=config, safety_settings=safety)
        raw_text = response.text
        start, end = raw_text.find('{'), raw_text.rfind('}')
        if -1 < start < end: return json.loads(raw_text[start : end + 1])
        return None
    except Exception as e:
        print(f"LLMによる構造化に失敗: {e}")
        return None

@st.cache_data
def get_match_summary_with_llm(_job_doc, _engineer_doc):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    prompt = f"""... (プロンプト内容は変更なし) ...""" # 長いので省略
    config = {"response_mime_type": "application/json"}
    safety = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        response = model.generate_content(prompt, generation_config=config, safety_settings=safety)
        raw_text = response.text
        start, end = raw_text.find('{'), raw_text.rfind('}')
        if -1 < start < end: return json.loads(raw_text[start : end + 1])
        return None
    except Exception as e:
        print(f"根拠の分析中にエラー: {e}")
        return None

def generate_proposal_reply_with_llm(job_summary, engineer_summary, engineer_name, project_name):
    if not all([job_summary, engineer_summary, engineer_name, project_name]): return "情報不足"
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    prompt = f"""... (プロンプト内容は変更なし) ...""" # 長いので省略
    try: return model.generate_content(prompt).text
    except Exception as e: return f"提案メール生成エラー: {e}"

# --- 6. Faiss (ベクトル検索) 関連 ---
def update_index(index_path, items):
    model = load_embedding_model()
    if not model or not items: return
    dim = model.get_sentence_embedding_dimension()
    index = faiss.IndexIDMap(faiss.IndexFlatIP(dim))
    ids = np.array([item['id'] for item in items], dtype=np.int64)
    bodies = [str(item['document']).split('\n---\n', 1)[-1] for item in items]
    embeddings = model.encode(["passage: " + body for body in bodies], normalize_embeddings=True)
    index.add_with_ids(embeddings, ids)
    faiss.write_index(index, index_path)

def search(query_text, index_path, top_k=5):
    model = load_embedding_model()
    if not model or not os.path.exists(index_path): return [], []
    index = faiss.read_index(index_path)
    if index.ntotal == 0: return [], []
    query_body = query_text.split('\n---\n', 1)[-1]
    query_vector = model.encode(["query: " + query_body], normalize_embeddings=True)
    sim, ids = index.search(query_vector, min(top_k, index.ntotal))
    valid_ids = [int(i) for i in ids[0] if i != -1]
    valid_sim = [s for s, i in zip(sim[0], ids[0]) if i != -1]
    return valid_sim, valid_ids

# --- 7. データ処理 & マッチング実行 ---
def get_records_by_ids(table_name, ids):
    if not ids: return []
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            query = f"SELECT * FROM {table_name} WHERE id IN %s"
            cursor.execute(query, (tuple(ids),))
            results = cursor.fetchall()
            return {res['id']: res for res in results}

# ▼▼▼【ここからが修正箇所】▼▼▼
def run_matching_for_item(item_data, item_type, cursor, now_str):
    if item_type == 'job':
        query_text, index_path, candidate_table = item_data['document'], ENGINEER_INDEX_FILE, 'engineers'
        source_name = item_data.get('project_name', f"案件ID:{item_data['id']}")
    else:
        query_text, index_path, candidate_table = item_data['document'], JOB_INDEX_FILE, 'jobs'
        source_name = item_data.get('name', f"技術者ID:{item_data['id']}")
    
    similarities, ids = search(query_text, index_path, top_k=TOP_K_CANDIDATES)
    if not ids:
        print(f"▶ 『{source_name}』の類似候補なし")
        return

    candidate_map = get_records_by_ids(candidate_table, ids)
    print(f"▶ 『{source_name}』の類似候補 {len(ids)}件を評価")

    for sim, candidate_id in zip(similarities, ids):
        score = float(sim) * 100
        if score < MIN_SCORE_THRESHOLD: continue
        
        candidate_record = candidate_map.get(candidate_id)
        if not candidate_record: continue

        # .get() を使って安全に名前を取得
        candidate_name = candidate_record.get('project_name' if candidate_table == 'jobs' else 'name') or f"ID:{candidate_id}"
        
        job_doc, eng_doc, job_id, eng_id = (item_data['document'], candidate_record['document'], item_data['id'], candidate_id) if item_type == 'job' else (candidate_record['document'], item_data['document'], candidate_id, item_data['id'])
        
        llm_result = get_match_summary_with_llm(job_doc, eng_doc)
        
        if llm_result and 'summary' in llm_result:
            grade = llm_result.get('summary')
            if grade in ['S', 'A', 'B', 'C']:
                cursor.execute('INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (job_id, engineer_id) DO NOTHING', (job_id, eng_id, score, now_str, grade))
                print(f"  - 候補: 『{candidate_name}』 -> 評価: {grade} ... ✅ DB保存")
            else:
                print(f"  - 候補: 『{candidate_name}』 -> 評価: {grade} ... ❌ スキップ")
        else:
            print(f"  - 候補: 『{candidate_name}』 -> LLM評価失敗")
# ▲▲▲【修正箇所ここまで】▲▲▲

def process_single_content(source_data: dict):
    if not source_data: return False
    attachments = source_data.get('attachments', [])
    valid_attachments = [f"\n\n--- 添付ファイル: {a['filename']} ---\n{a['content']}" for a in attachments if a.get('content') and not a['content'].startswith("[")]
    full_text = source_data.get('body', '') + "".join(valid_attachments)
    if not full_text.strip(): return False
    
    parsed = split_text_with_llm(full_text)
    if not parsed: return False
    
    new_jobs = parsed.get("jobs", [])
    new_engineers = parsed.get("engineers", [])
    if not new_jobs and not new_engineers: return False

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            source_json = json.dumps(source_data, ensure_ascii=False, indent=2)
            added_jobs, added_engineers = [], []

            for item in new_jobs:
                doc = item.get("document") or full_text
                name = item.get("project_name", "名称未定の案件")
                meta = _build_meta_info_string('job', item)
                full_doc = meta + doc
                cursor.execute('INSERT INTO jobs (project_name, document, source_data_json, created_at) VALUES (%s, %s, %s, %s) RETURNING id', (name, full_doc, source_json, now))
                item['id'] = cursor.fetchone()[0]
                item['document'] = full_doc
                added_jobs.append(item)
            
            for item in new_engineers:
                doc = item.get("document") or full_text
                name = item.get("name", "名称不明の技術者")
                meta = _build_meta_info_string('engineer', item)
                full_doc = meta + doc
                cursor.execute('INSERT INTO engineers (name, document, source_data_json, created_at) VALUES (%s, %s, %s, %s) RETURNING id', (name, full_doc, source_json, now))
                item['id'] = cursor.fetchone()[0]
                item['document'] = full_doc
                added_engineers.append(item)

            print("インデックス更新とマッチング開始...")
            cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0')
            jobs = cursor.fetchall()
            cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0')
            engineers = cursor.fetchall()
            if jobs: update_index(JOB_INDEX_FILE, jobs)
            if engineers: update_index(ENGINEER_INDEX_FILE, engineers)

            for job in added_jobs: run_matching_for_item(job, 'job', cursor, now)
            for eng in added_engineers: run_matching_for_item(eng, 'engineer', cursor, now)
        conn.commit()
    return True

# --- 8. メール取得・処理 ---
def get_email_contents(msg):
    body, attachments = "", []
    if msg.is_multipart():
        for part in msg.walk():
            ctype, cdisp = part.get_content_type(), str(part.get("Content-Disposition"))
            if 'text/plain' in ctype and 'attachment' not in cdisp:
                charset = part.get_content_charset() or 'utf-8'
                try: body += part.get_payload(decode=True).decode(charset, 'ignore')
                except Exception: body += part.get_payload(decode=True).decode('utf-8', 'ignore')
            if 'attachment' in cdisp:
                fname_raw = part.get_filename()
                if fname_raw:
                    fname = "".join([s.decode(c or 'utf-8', 'ignore') if isinstance(s, bytes) else s for s, c in decode_header(fname_raw)])
                    print(f"📄 添付発見: {fname}")
                    fbytes = part.get_payload(decode=True)
                    content = ""
                    if fname.lower().endswith(".pdf"): content = extract_text_from_pdf(fbytes)
                    elif fname.lower().endswith(".docx"): content = extract_text_from_docx(fbytes)
                    elif fname.lower().endswith(".txt"): content = fbytes.decode('utf-8', 'ignore')
                    if content: attachments.append({"filename": fname, "content": content})
    else:
        charset = msg.get_content_charset() or 'utf-8'
        try: body = msg.get_payload(decode=True).decode(charset, 'ignore')
        except Exception: body = msg.get_payload(decode=True).decode('utf-8', 'ignore')
    return {"body": body.strip(), "attachments": attachments}

def fetch_and_process_emails():
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            secrets = st.secrets
            SERVER, USER, PWD = secrets["EMAIL_SERVER"], secrets["EMAIL_USER"], secrets["EMAIL_PASSWORD"]
            with imaplib.IMAP4_SSL(SERVER) as mail:
                mail.login(USER, PWD)
                mail.select('inbox')
                _, msgs = mail.search(None, 'UNSEEN')
                ids = msgs[0].split()
                if not ids:
                    print("新規未読メールなし")
                    return True, log.getvalue()
                
                count, total = 0, len(ids)
                print(f"最新の未読メール {total}件をチェック")
                for eid in reversed(ids[:10]):
                    _, data = mail.fetch(eid, '(RFC822)')
                    for part in data:
                        if isinstance(part, tuple):
                            msg = email.message_from_bytes(part[1])
                            source = get_email_contents(msg)
                            if source['body'] or source['attachments']:
                                if process_single_content(source):
                                    count += 1
                                    mail.store(eid, '+FLAGS', '\\Seen')
        if count > 0: st.success(f"{count} 件のメールからデータを抽出・保存しました。"); st.balloons()
        else: st.info("新しいメールをチェックしましたが、処理対象はありませんでした。")
        return True, log.getvalue()
    except Exception as e:
        st.error(f"予期せぬエラー: {e}")
        return False, log.getvalue()

# --- 9. データ更新・操作 (CRUD) ---
def _update_single_field(table, field, value, record_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = f"UPDATE {table} SET {field} = %s WHERE id = %s"
                cursor.execute(query, (value, record_id))
            conn.commit()
        return True
    except Exception as e:
        print(f"DB更新エラー ({table}.{field}): {e}")
        return False

def update_job_source_json(job_id, json_str): return _update_single_field('jobs', 'source_data_json', json_str, job_id)
def update_engineer_source_json(eng_id, json_str): return _update_single_field('engineers', 'source_data_json', json_str, eng_id)
def update_engineer_name(eng_id, name): return _update_single_field('engineers', 'name', name.strip(), eng_id) if name and name.strip() else False
def assign_user_to_job(job_id, user_id): return _update_single_field('jobs', 'assigned_user_id', user_id, job_id)
def assign_user_to_engineer(eng_id, user_id): return _update_single_field('engineers', 'assigned_user_id', user_id, eng_id)
def set_job_visibility(job_id, hidden): return _update_single_field('jobs', 'is_hidden', hidden, job_id)
def set_engineer_visibility(eng_id, hidden): return _update_single_field('engineers', 'is_hidden', hidden, eng_id)
def hide_match(res_id): return _update_single_field('matching_results', 'is_hidden', 1, res_id)
def save_match_grade(match_id, grade): return _update_single_field('matching_results', 'grade', grade, match_id) if grade else False
def update_match_status(match_id, status): return _update_single_field('matching_results', 'status', status, match_id) if match_id and status else False

def get_all_users():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT id, username FROM users ORDER BY id")
            return cursor.fetchall()

def get_matching_result_details(result_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT * FROM matching_results WHERE id = %s", (result_id,))
            match = cursor.fetchone()
            if not match: return None
            cursor.execute("SELECT j.*, u.username as assignee_name FROM jobs j LEFT JOIN users u ON j.assigned_user_id = u.id WHERE j.id = %s", (match['job_id'],))
            job = cursor.fetchone()
            cursor.execute("SELECT e.*, u.username as assignee_name FROM engineers e LEFT JOIN users u ON e.assigned_user_id = u.id WHERE e.id = %s", (match['engineer_id'],))
            eng = cursor.fetchone()
            return {"match_result": match, "job_data": job, "engineer_data": eng}

# --- 10. 再評価・再マッチング ---
def re_evaluate_and_match_single_item(item_type, item_id):
    table = 'jobs' if item_type == 'job' else 'engineers'
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (item_id,))
            record = cursor.fetchone()
            if not record: return False
            
            source = json.loads(record['source_data_json'])
            full_text = source.get('body', '')
            
            parsed = split_text_with_llm(full_text)
            if not parsed or not parsed.get(f"{table}s"): return False

            item_data = parsed[f"{table}s"][0]
            doc = item_data.get("document") or full_text
            meta = _build_meta_info_string(item_type, item_data)
            new_doc = meta + doc
            
            if item_type == 'job':
                name = item_data.get('project_name', record['project_name'])
                cursor.execute("UPDATE jobs SET document = %s, project_name = %s WHERE id = %s", (new_doc, name, item_id))
            else:
                name = item_data.get('name', record['name'])
                cursor.execute("UPDATE engineers SET document = %s, name = %s WHERE id = %s", (new_doc, name, item_id))

            cursor.execute(f"DELETE FROM matching_results WHERE {item_type}_id = %s", (item_id,))
            print(f"既存のマッチング結果をクリア (ID:{item_id})")

            print("インデックス更新と再マッチング開始...")
            cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0')
            jobs = cursor.fetchall()
            cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0')
            engineers = cursor.fetchall()
            if jobs: update_index(JOB_INDEX_FILE, jobs)
            if engineers: update_index(ENGINEER_INDEX_FILE, engineers)

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data = {'id': item_id, 'document': new_doc}
            if item_type == 'job': data['project_name'] = name
            else: data['name'] = name
            run_matching_for_item(data, item_type, cursor, now)
        conn.commit()
    return True

def re_evaluate_and_match_single_engineer(eng_id): return re_evaluate_and_match_single_item('engineer', eng_id)
def re_evaluate_and_match_single_job(job_id): return re_evaluate_and_match_single_item('job', job_id)
