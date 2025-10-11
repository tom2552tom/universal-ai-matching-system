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

# Faissインデックスファイルのパス
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
    try:
        return SentenceTransformer(MODEL_NAME)
    except Exception as e:
        st.error(f"埋め込みモデル '{MODEL_NAME}' の読み込みに失敗しました: {e}")
        return None

# --- 3. データベース接続 ---

def get_db_connection():
    """PostgreSQLデータベースへの接続を取得します。"""
    try:
        conn_string = st.secrets["DATABASE_URL"]
        conn = psycopg2.connect(conn_string)
        return conn
    except Exception as e:
        st.error(f"データベース接続エラー: {e}")
        st.info("Supabaseの接続情報がStreamlitのSecretsに正しく設定されているか確認してください。")
        st.stop()

# --- 4. データベース初期化・スキーマ管理 ---

def init_database():
    """PostgreSQLデータベースとテーブルを初期化する。"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                
                def column_exists(table, column):
                    cursor.execute("""
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
                    """, (table, column))
                    return cursor.fetchone() is not None

                # --- テーブル作成 ---
                cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id SERIAL PRIMARY KEY, project_name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT, is_hidden INTEGER DEFAULT 0, assigned_user_id INTEGER)')
                cursor.execute('CREATE TABLE IF NOT EXISTS engineers (id SERIAL PRIMARY KEY, name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT, is_hidden INTEGER DEFAULT 0, assigned_user_id INTEGER)')
                cursor.execute('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS matching_results (
                        id SERIAL PRIMARY KEY,
                        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
                        engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
                        score REAL,
                        created_at TEXT,
                        is_hidden INTEGER DEFAULT 0,
                        grade TEXT,
                        positive_points TEXT,
                        concern_points TEXT,
                        proposal_text TEXT,
                        status TEXT DEFAULT '新規',
                        UNIQUE (job_id, engineer_id)
                    )
                ''')

                # --- 初回ユーザー追加 ---
                cursor.execute("SELECT COUNT(*) FROM users")
                if cursor.fetchone()[0] == 0:
                    print("初回起動のため、テストユーザーを追加します...")
                    users_to_add = [
                        ('熊崎', 'k@e.com'), ('岩本', 'i@e.com'), ('小関', 'o@e.com'),
                        ('内山', 'u@e.com'), ('島田', 's@e.com'), ('長谷川', 'h@e.com'),
                        ('北島', 'k@e.com'), ('岩崎', 'i@e.com'), ('根岸', 'n@e.com'),
                        ('添田', 's@e.com'), ('山浦', 'y@e.com'), ('福田', 'f@e.com')
                    ]
                    cursor.executemany("INSERT INTO users (username, email) VALUES (%s, %s)", users_to_add)
                    print(f" -> {len(users_to_add)}名のテストユーザーを追加しました。")
                
                # --- カラム追加 (下位互換性のため) ---
                if not column_exists('jobs', 'assigned_user_id'): cursor.execute("ALTER TABLE jobs ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
                if not column_exists('jobs', 'is_hidden'): cursor.execute("ALTER TABLE jobs ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
                if not column_exists('engineers', 'assigned_user_id'): cursor.execute("ALTER TABLE engineers ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
                if not column_exists('engineers', 'is_hidden'): cursor.execute("ALTER TABLE engineers ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
                if not column_exists('matching_results', 'status'): cursor.execute("ALTER TABLE matching_results ADD COLUMN status TEXT DEFAULT '新規'")

            conn.commit()
            print("Database initialized and schema verified for PostgreSQL successfully.")
    except Exception as e:
        print(f"❌ データベース初期化中にエラーが発生しました: {e}")

# --- 5. LLM & AI関連 ---

def _build_meta_info_string(item_type, item_data):
    """メタ情報文字列を生成する共通ヘルパー関数"""
    if item_type == 'job':
        meta_fields = [
            ["国籍要件", "nationality_requirement"], ["開始時期", "start_date"], ["勤務地", "location"],
            ["単価", "unit_price"], ["必須スキル", "required_skills"]
        ]
    elif item_type == 'engineer':
        meta_fields = [
            ["国籍", "nationality"], ["稼働可能日", "availability_date"], ["希望勤務地", "desired_location"],
            ["希望単価", "desired_salary"], ["主要スキル", "main_skills"]
        ]
    else:
        return "\n---\n"
    meta_parts = [f"[{name}: {item_data.get(key, '不明')}]" for name, key in meta_fields]
    return " ".join(meta_parts) + "\n---\n"

def split_text_with_llm(text_content):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as f:
            prompt = f.read().replace('{text_content}', text_content)
    except FileNotFoundError:
        st.error("エラー: `prompt.txt` が見つかりません。")
        return None
    
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    
    try:
        response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        raw_text = response.text
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        if start_index != -1 and end_index != -1 and start_index < end_index:
            return json.loads(raw_text[start_index : end_index + 1])
        st.error("LLMの応答から有効なJSON形式を抽出できませんでした。"); st.code(raw_text)
        return None
    except Exception as e:
        st.error(f"LLMによる構造化に失敗しました: {e}")
        return None

@st.cache_data
def get_match_summary_with_llm(_job_doc, _engineer_doc):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    prompt = f"""
あなたは、経験豊富で非常に優秀なIT人材紹介のエージェントです。
あなたの仕事は、提示された「案件情報」と「技術者情報」を深く比較分析し、単なるキーワードの一致ではなく、**具体的な理由に基づいた**客観的なマッチング評価を行うことです。
# 絶対的なルール
- **キーワードの羅列は絶対に禁止します。** `positive_points` と `concern_points` には、必ず**具体的な理由を説明する短い文章**を記述してください。
- 各ポイントは、なぜそれがポジティブなのか、なぜそれが懸念点なのかが明確にわかるように記述してください。
- 最終的な総合評価 `summary` は、S, A, B, C, Dのいずれかの文字列を必ず返してください。
- ポジティブな点や懸念点が一つもない場合でも、その旨を正直に記載するか、空のリスト `[]` を返してください。
# 良い例と悪い例
- **悪い例:** `{{"positive_points": ["Java, Spring Boot, AWS"]}}`
- **良い例:** `{{"positive_points": ["案件で必須となっているJavaとSpring Bootでの開発経験が5年以上あり、即戦力として期待できる。", "AWS環境でのインフラ構築経験が、プロジェクトの要件と合致している。"]}}`
# 指示
以下の2つの情報を分析し、上記のルールに従ってポジティブな点と懸念点をリストアップしてください。最終的に、総合評価（summary）をS, A, B, C, Dの5段階で判定してください。
- S: 完璧なマッチ、即戦力として強く推薦
- A: 非常に良いマッチ、多くの要件を満たしている
- B: 良いマッチ、主要な要件は満たしている
- C: 検討の余地あり、いくつかの懸念点がある
- D: ミスマッチ、推薦は難しい
# JSON出力形式
{{
  "summary": "S, A, B, C, Dのいずれか",
  "positive_points": ["（ここに具体的な理由を説明する文章を記述）"],
  "concern_points": ["（ここに具体的な理由を説明する文章を記述）"]
}}
---
# 案件情報
{_job_doc}
---
# 技術者情報
{_engineer_doc}
---
"""
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        raw_text = response.text
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        if start_index != -1 and end_index != -1 and start_index < end_index:
            return json.loads(raw_text[start_index : end_index + 1])
        st.error("評価の分析中にLLMが有効なJSONを返しませんでした。"); st.code(raw_text)
        return None
    except Exception as e:
        st.error(f"根拠の分析中にエラー: {e}")
        return None

def generate_proposal_reply_with_llm(job_summary, engineer_summary, engineer_name, project_name):
    if not all([job_summary, engineer_summary, engineer_name, project_name]):
        return "情報が不足しているため、提案メールを生成できませんでした。"
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    prompt = f"""
あなたは、クライアントに優秀な技術者を提案する、経験豊富なIT営業担当者です。
以下の案件情報と技術者情報をもとに、クライアントの心に響く、丁寧で説得力のある提案メールの文面を作成してください。
# 役割: 優秀なIT営業担当者
# 指示
- 最初に、提案する技術者名と案件名を記載した件名を作成してください (例: 件名: 【〇〇様のご提案】〇〇プロジェクトの件)。
- 技術者のスキルや経験が、案件のどの要件に具体的にマッチしているかを明確に示してください。
- ポジティブな点（適合スキル）を強調し、技術者の魅力を最大限に伝えてください。
- 懸念点（スキルミスマッチや経験不足）がある場合は、正直に触れつつも、学習意欲や類似経験、ポテンシャルなどでどのようにカバーできるかを前向きに説明してください。
- 全体として、プロフェッショナルかつ丁寧なビジネスメールのトーンを維持してください。
- 最後に、ぜひ一度、オンラインでの面談の機会を設けていただけますようお願いする一文で締めくくってください。
- 出力は、件名と本文を含んだメール形式のテキストのみとしてください。余計な解説は不要です。
# 案件情報: {job_summary}
# 技術者情報: {engineer_summary}
# 提案する技術者の名前: {engineer_name}
# 案件名: {project_name}
---
それでは、上記の指示に基づいて、最適な提案メールを作成してください。
"""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating proposal reply with LLM: {e}")
        return f"提案メールの生成中にエラーが発生しました: {e}"

# --- 6. Faiss (ベクトル検索) 関連 ---

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
    valid_similarities = [s for s, i in zip(similarities[0], ids[0]) if i != -1]
    return valid_similarities, valid_ids

# --- 7. データ処理 & マッチング実行 ---

def get_records_by_ids(table_name, ids):
    if not ids: return []
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            # IN句のプレースホルダーはタプルにする
            query = f"SELECT * FROM {table_name} WHERE id IN %s"
            cursor.execute(query, (tuple(ids),))
            results = cursor.fetchall()
            results_map = {res['id']: res for res in results}
            return [results_map[id] for id in ids if id in results_map]

def run_matching_for_item(item_data, item_type, cursor, now_str):
    if item_type == 'job':
        query_text, index_path, candidate_table = item_data['document'], ENGINEER_INDEX_FILE, 'engineers'
        source_name = item_data.get('project_name', f"案件ID:{item_data['id']}")
    else:
        query_text, index_path, candidate_table = item_data['document'], JOB_INDEX_FILE, 'jobs'
        source_name = item_data.get('name', f"技術者ID:{item_data['id']}")
    
    similarities, ids = search(query_text, index_path, top_k=TOP_K_CANDIDATES)
    if not ids:
        print(f"▶ 『{source_name}』(ID:{item_data['id']}, {item_type}) の類似候補は見つかりませんでした。")
        return

    candidate_records = get_records_by_ids(candidate_table, ids)
    candidate_map = {record['id']: record for record in candidate_records}
    print(f"▶ 『{source_name}』(ID:{item_data['id']}, {item_type}) との類似候補 {len(ids)}件を評価します。")

    for sim, candidate_id in zip(similarities, ids):
        score = float(sim) * 100
        if score < MIN_SCORE_THRESHOLD: continue
        candidate_record = candidate_map.get(candidate_id)
        if not candidate_record: continue

        candidate_name = candidate_record.get('project_name' if candidate_table == 'jobs' else 'name', f"ID:{candidate_id}")
        
        job_doc, engineer_doc, job_id, engineer_id = (item_data['document'], candidate_record['document'], item_data['id'], candidate_id) if item_type == 'job' else (candidate_record['document'], item_data['document'], candidate_id, item_data['id'])
        
        llm_result = get_match_summary_with_llm(job_doc, engineer_doc)
        
        if llm_result and 'summary' in llm_result:
            grade = llm_result.get('summary')
            if grade in ['S', 'A', 'B', 'C']:
                cursor.execute(
                    'INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade) VALUES (%s, %s, %s, %s, %s)',
                    (job_id, engineer_id, score, now_str, grade)
                )
                print(f"  - 候補: 『{candidate_name}』(ID:{candidate_id}) -> 評価: {grade} (スコア: {score:.2f}) ... ✅ DB保存")
            else:
                print(f"  - 候補: 『{candidate_name}』(ID:{candidate_id}) -> 評価: {grade} (スコア: {score:.2f}) ... ❌ スキップ")
        else:
            print(f"  - 候補: 『{candidate_name}』(ID:{candidate_id}) -> LLM評価失敗のためスキップ")

def process_single_content(source_data: dict):
    if not source_data:
        print("処理するデータが空です。")
        return False
    
    attachments = source_data.get('attachments', [])
    valid_attachments_content = [f"\n\n--- 添付ファイル: {att['filename']} ---\n{att['content']}" for att in attachments if att.get('content') and not att['content'].startswith("[")]
    full_text_for_llm = source_data.get('body', '') + "".join(valid_attachments_content)
    if not full_text_for_llm.strip():
        print("解析対象のテキストがありません。")
        return False
    
    parsed_data = split_text_with_llm(full_text_for_llm)
    if not parsed_data: return False
    
    new_jobs_data = parsed_data.get("jobs", [])
    new_engineers_data = parsed_data.get("engineers", [])
    if not new_jobs_data and not new_engineers_data:
        print("LLMはテキストから案件情報または技術者情報を抽出できませんでした。")
        return False

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            source_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
            newly_added_jobs, newly_added_engineers = [], []

            for item_data in new_jobs_data:
                doc = item_data.get("document") or full_text_for_llm
                project_name = item_data.get("project_name", "名称未定の案件")
                meta_info = _build_meta_info_string('job', item_data)
                full_document = meta_info + doc
                cursor.execute('INSERT INTO jobs (project_name, document, source_data_json, created_at) VALUES (%s, %s, %s, %s) RETURNING id', (project_name, full_document, source_json_str, now_str))
                item_data['id'] = cursor.fetchone()[0]
                item_data['document'] = full_document
                newly_added_jobs.append(item_data)
            
            for item_data in new_engineers_data:
                doc = item_data.get("document") or full_text_for_llm
                engineer_name = item_data.get("name", "名称不明の技術者")
                meta_info = _build_meta_info_string('engineer', item_data)
                full_document = meta_info + doc
                cursor.execute('INSERT INTO engineers (name, document, source_data_json, created_at) VALUES (%s, %s, %s, %s) RETURNING id', (engineer_name, full_document, source_json_str, now_str))
                item_data['id'] = cursor.fetchone()[0]
                item_data['document'] = full_document
                newly_added_engineers.append(item_data)

            print("ベクトルインデックスを更新し、マッチング処理を開始します...")
            cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0')
            all_active_jobs = cursor.fetchall()
            cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0')
            all_active_engineers = cursor.fetchall()
            if all_active_jobs: update_index(JOB_INDEX_FILE, all_active_jobs)
            if all_active_engineers: update_index(ENGINEER_INDEX_FILE, all_active_engineers)

            for new_job in newly_added_jobs: run_matching_for_item(new_job, 'job', cursor, now_str)
            for new_engineer in newly_added_engineers: run_matching_for_item(new_engineer, 'engineer', cursor, now_str)
        conn.commit()
    return True

# --- 8. メール取得・処理 ---

def extract_text_from_pdf(file_bytes):
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
        return text.strip() or "[PDFテキスト抽出失敗: 内容が空または画像PDF]"
    except Exception as e: return f"[PDFテキスト抽出エラー: {e}]"

def extract_text_from_docx(file_bytes):
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text.strip() or "[DOCXテキスト抽出失敗: 内容が空]"
    except Exception as e: return f"[DOCXテキスト抽出エラー: {e}]"

def get_email_contents(msg):
    body_text, attachments = "", []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if 'text/plain' in content_type and 'attachment' not in content_disposition:
                charset = part.get_content_charset() or 'utf-8'
                try: body_text += part.get_payload(decode=True).decode(charset, 'ignore')
                except Exception: body_text += part.get_payload(decode=True).decode('utf-8', 'ignore')
            if 'attachment' in content_disposition:
                raw_filename = part.get_filename()
                if raw_filename:
                    filename = "".join([s.decode(c or 'utf-8', 'ignore') if isinstance(s, bytes) else s for s, c in decode_header(raw_filename)])
                    print(f"📄 添付ファイル '{filename}' を発見しました。")
                    file_bytes = part.get_payload(decode=True)
                    lower_filename = filename.lower()
                    content = ""
                    if lower_filename.endswith(".pdf"): content = extract_text_from_pdf(file_bytes)
                    elif lower_filename.endswith(".docx"): content = extract_text_from_docx(file_bytes)
                    elif lower_filename.endswith(".txt"): content = file_bytes.decode('utf-8', 'ignore')
                    else: print(f"ℹ️ 添付ファイル '{filename}' は未対応形式のためスキップ。")
                    if content: attachments.append({"filename": filename, "content": content})
    else:
        charset = msg.get_content_charset() or 'utf-8'
        try: body_text = msg.get_payload(decode=True).decode(charset, 'ignore')
        except Exception: body_text = msg.get_payload(decode=True).decode('utf-8', 'ignore')
    return {"body": body_text.strip(), "attachments": attachments}

def fetch_and_process_emails():
    log_stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(log_stream):
            try:
                SERVER, USER, PASSWORD = st.secrets["EMAIL_SERVER"], st.secrets["EMAIL_USER"], st.secrets["EMAIL_PASSWORD"]
            except KeyError as e:
                print(f"メールサーバーの接続情報がSecretsに設定されていません: {e}")
                return False, log_stream.getvalue()
            
            with imaplib.IMAP4_SSL(SERVER) as mail:
                mail.login(USER, PASSWORD)
                mail.select('inbox')
                _, messages = mail.search(None, 'UNSEEN')
                email_ids = messages[0].split()
                if not email_ids:
                    print("処理対象の未読メールは見つかりませんでした。")
                    return True, log_stream.getvalue()

                total_processed_count = 0
                latest_ids = email_ids[::-1][:10]
                print(f"最新の未読メール {len(latest_ids)}件をチェックします。")
                for i, email_id in enumerate(latest_ids):
                    _, msg_data = mail.fetch(email_id, '(RFC822)')
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            source_data = get_email_contents(msg)
                            if source_data['body'] or source_data['attachments']:
                                print(f"✅ メールID {email_id.decode()} を処理します...")
                                if process_single_content(source_data):
                                    total_processed_count += 1
                                    mail.store(email_id, '+FLAGS', '\\Seen')
                            else:
                                print(f"✖️ メールID {email_id.decode()} は内容がないためスキップします。")
                    print(f"({i+1}/{len(latest_ids)}) チェック完了")
        
        if total_processed_count > 0:
            st.success(f"{total_processed_count} 件のメールからデータを抽出し、保存しました。")
            st.balloons()
        else:
            st.info("新しい未読メールをチェックしましたが、処理対象のデータは見つかりませんでした。")
        return True, log_stream.getvalue()
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
        st.error(f"予期せぬエラーが発生しました: {e}")
        return False, log_stream.getvalue()

# --- 9. データ更新・操作 (CRUD) ---

def _update_single_field(table, field, value, record_id):
    """汎用的な単一フィールド更新関数"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # SQLインジェクションを防ぐため、テーブル名とフィールド名はプログラム側で固定
                # 動的にする場合は、ホワイトリストで厳密に検証する必要がある
                query = f"UPDATE {table} SET {field} = %s WHERE id = %s"
                cursor.execute(query, (value, record_id))
            conn.commit()
        return True
    except Exception as e:
        print(f"DB更新エラー ({table}.{field}): {e}")
        return False

def update_job_source_json(job_id, new_json_str):
    return _update_single_field('jobs', 'source_data_json', new_json_str, job_id)

def update_engineer_source_json(engineer_id, new_json_str):
    return _update_single_field('engineers', 'source_data_json', new_json_str, engineer_id)

def update_engineer_name(engineer_id, new_name):
    return _update_single_field('engineers', 'name', new_name.strip(), engineer_id) if new_name and new_name.strip() else False

def assign_user_to_job(job_id, user_id):
    return _update_single_field('jobs', 'assigned_user_id', user_id, job_id)

def assign_user_to_engineer(engineer_id, user_id):
    return _update_single_field('engineers', 'assigned_user_id', user_id, engineer_id)

def set_job_visibility(job_id, is_hidden):
    return _update_single_field('jobs', 'is_hidden', is_hidden, job_id)

def set_engineer_visibility(engineer_id, is_hidden):
    return _update_single_field('engineers', 'is_hidden', is_hidden, engineer_id)

def hide_match(result_id):
    return _update_single_field('matching_results', 'is_hidden', 1, result_id)

def save_match_grade(match_id, grade):
    return _update_single_field('matching_results', 'grade', grade, match_id) if grade else False

def update_match_status(match_id, new_status):
    return _update_single_field('matching_results', 'status', new_status, match_id) if match_id and new_status else False

def get_all_users():
    """全てのユーザー情報を取得する。"""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT id, username FROM users ORDER BY id")
            return cursor.fetchall()

def get_matching_result_details(result_id):
    """指定されたマッチング結果IDの詳細情報を取得する。"""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT * FROM matching_results WHERE id = %s", (result_id,))
            match_result = cursor.fetchone()
            if not match_result: return None
            
            job_query = "SELECT j.*, u.username as assignee_name FROM jobs j LEFT JOIN users u ON j.assigned_user_id = u.id WHERE j.id = %s"
            cursor.execute(job_query, (match_result['job_id'],))
            job_data = cursor.fetchone()

            engineer_query = "SELECT e.*, u.username as assignee_name FROM engineers e LEFT JOIN users u ON e.assigned_user_id = u.id WHERE e.id = %s"
            cursor.execute(engineer_query, (match_result['engineer_id'],))
            engineer_data = cursor.fetchone()

            return {
                "match_result": match_result,
                "job_data": job_data,
                "engineer_data": engineer_data,
            }

# --- 10. 再評価・再マッチング ---

def re_evaluate_and_match_single_item(item_type, item_id):
    """案件または技術者の単一アイテムを再評価・再マッチングする共通関数"""
    table_name = 'jobs' if item_type == 'job' else 'engineers'
    
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(f"SELECT * FROM {table_name} WHERE id = %s", (item_id,))
            record = cursor.fetchone()
            if not record:
                print(f"ID:{item_id} の {item_type} が見つかりませんでした。")
                return False

            source_data = json.loads(record['source_data_json'])
            full_text_for_llm = source_data.get('body', '')
            
            parsed_data = split_text_with_llm(full_text_for_llm)
            if not parsed_data or not parsed_data.get(f"{table_name}s"): # 'jobs' or 'engineers'
                print(f"LLMによる再評価で、{item_type}情報の抽出に失敗しました。")
                return False

            item_data = parsed_data[f"{table_name}s"][0]
            doc = item_data.get("document") or full_text_for_llm
            meta_info = _build_meta_info_string(item_type, item_data)
            new_full_document = meta_info + doc
            
            if item_type == 'job':
                new_name = item_data.get('project_name', record['project_name'])
                cursor.execute("UPDATE jobs SET document = %s, project_name = %s WHERE id = %s", (new_full_document, new_name, item_id))
            else:
                new_name = item_data.get('name', record['name'])
                cursor.execute("UPDATE engineers SET document = %s, name = %s WHERE id = %s", (new_full_document, new_name, item_id))

            delete_query = f"DELETE FROM matching_results WHERE {item_type}_id = %s"
            cursor.execute(delete_query, (item_id,))
            print(f"{item_type} ID:{item_id} の既存マッチング結果をクリアしました。")

            print("ベクトルインデックスを更新し、再マッチング処理を開始します...")
            cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0')
            all_active_jobs = cursor.fetchall()
            cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0')
            all_active_engineers = cursor.fetchall()
            if all_active_jobs: update_index(JOB_INDEX_FILE, all_active_jobs)
            if all_active_engineers: update_index(ENGINEER_INDEX_FILE, all_active_engineers)

            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data_for_matching = {'id': item_id, 'document': new_full_document}
            if item_type == 'job': data_for_matching['project_name'] = new_name
            else: data_for_matching['name'] = new_name
            
            run_matching_for_item(data_for_matching, item_type, cursor, now_str)
        conn.commit()
    return True

def re_evaluate_and_match_single_engineer(engineer_id):
    return re_evaluate_and_match_single_item('engineer', engineer_id)

def re_evaluate_and_match_single_job(job_id):
    return re_evaluate_and_match_single_item('job', job_id)
