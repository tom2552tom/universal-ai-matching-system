import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import faiss
from sentence_transformers import SentenceTransformer
import numpy as np
import os
import google.generativeai as genai
import json
from datetime import datetime
import imaplib
import email
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
import io
import contextlib
import toml
import fitz
import docx

# --- 1. 初期設定と定数 (変更なし) ---
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

# --- 関数定義 ---
@st.cache_data
def load_app_config():
    try:
        with open("config.toml", "r", encoding="utf-8") as f:
            return toml.load(f)
    except FileNotFoundError:
        return {"app": {"title": "Universal AI Agent (Default)"}, "messages": {"sales_staff_notice": ""}}
    except Exception as e:
        print(f"❌ 設定ファイルの読み込み中にエラーが発生しました: {e}")
        return {"app": {"title": "Universal AI Agent (Error)"}, "messages": {"sales_staff_notice": ""}}

@st.cache_resource
def load_embedding_model():
    try:
        return SentenceTransformer(MODEL_NAME)
    except Exception as e:
        st.error(f"埋め込みモデル '{MODEL_NAME}' の読み込みに失敗しました: {e}"); return None

def get_db_connection():
    try:
        db_url = st.secrets["DATABASE_URL"]
        return psycopg2.connect(db_url, cursor_factory=DictCursor)
    except KeyError:
        st.error("`secrets.toml` に `DATABASE_URL` が設定されていません。"); st.stop()
    except psycopg2.OperationalError as e:
        st.error(f"データベースへの接続に失敗しました: {e}"); st.stop()
    except Exception as e:
        st.error(f"データベース接続中に予期せぬエラーが発生しました: {e}"); st.stop()

def init_database():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id SERIAL PRIMARY KEY, project_name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT, assigned_user_id INTEGER, is_hidden INTEGER NOT NULL DEFAULT 0, received_at TIMESTAMP WITH TIME ZONE)')
            cursor.execute('CREATE TABLE IF NOT EXISTS engineers (id SERIAL PRIMARY KEY, name TEXT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT, assigned_user_id INTEGER, is_hidden INTEGER NOT NULL DEFAULT 0, received_at TIMESTAMP WITH TIME ZONE)')
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);")
            cursor.execute('''CREATE TABLE IF NOT EXISTS matching_results (id SERIAL PRIMARY KEY, job_id INTEGER NOT NULL, engineer_id INTEGER NOT NULL, score REAL NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, is_hidden INTEGER DEFAULT 0, grade TEXT, positive_points TEXT, concern_points TEXT, proposal_text TEXT, status TEXT DEFAULT '新規', FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE, FOREIGN KEY (engineer_id) REFERENCES engineers (id) ON DELETE CASCADE, UNIQUE (job_id, engineer_id))''')
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                print("初回起動のため、テストユーザーを追加します...")
                users_to_add = [('熊崎', 'yamada@example.com'), ('岩本', 'suzuki@example.com'), ('小関', 'sato@example.com'), ('内山', 'sato@example.com'), ('島田', 'sato@example.com'), ('長谷川', 'sato@example.com'), ('北島', 'sato@example.com'), ('岩崎', 'sato@example.com'), ('根岸', 'sato@example.com'), ('添田', 'sato@example.com'), ('山浦', 'sato@example.com'), ('福田', 'sato@example.com')]
                cursor.executemany("INSERT INTO users (username, email) VALUES (%s, %s)", users_to_add)
                print(" -> テストユーザーを追加しました。")
            def get_columns(table_name):
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s", (table_name,))
                return [row['column_name'] for row in cursor.fetchall()]
            job_columns = get_columns('jobs')
            if 'assigned_user_id' not in job_columns: cursor.execute("ALTER TABLE jobs ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
            if 'is_hidden' not in job_columns: cursor.execute("ALTER TABLE jobs ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
            if 'received_at' not in job_columns: cursor.execute("ALTER TABLE jobs ADD COLUMN received_at TIMESTAMP WITH TIME ZONE")
            engineer_columns = get_columns('engineers')
            if 'assigned_user_id' not in engineer_columns: cursor.execute("ALTER TABLE engineers ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)")
            if 'is_hidden' not in engineer_columns: cursor.execute("ALTER TABLE engineers ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
            if 'received_at' not in engineer_columns: cursor.execute("ALTER TABLE engineers ADD COLUMN received_at TIMESTAMP WITH TIME ZONE")
            match_columns = get_columns('matching_results')
            if 'positive_points' not in match_columns: cursor.execute("ALTER TABLE matching_results ADD COLUMN positive_points TEXT")
            if 'concern_points' not in match_columns: cursor.execute("ALTER TABLE matching_results ADD COLUMN concern_points TEXT")
            if 'status' not in match_columns: cursor.execute("ALTER TABLE matching_results ADD COLUMN status TEXT DEFAULT '新規'")
        conn.commit()
        print("Database initialized and schema verified successfully for PostgreSQL.")
    except (Exception, psycopg2.Error) as e:
        print(f"❌ データベース初期化中にエラーが発生しました: {e}"); conn.rollback()
    finally:
        if conn: conn.close()

def get_extraction_prompt(doc_type, text_content):
    if doc_type == 'engineer':
        return f"""
            あなたは、IT人材の「スキルシート」や「職務経歴書」を読み解く専門家です。
            あなたの仕事は、与えられたテキストから**単一の技術者情報**を抽出し、指定されたJSON形式で整理することです。
            # 絶対的なルール
            - 出力は、指定されたJSON形式の文字列のみとし、前後に解説や```json ```のようなコードブロックの囲みを含めないでください。
            # 指示
            - テキスト全体は、一人の技術者の情報です。複数の業務経歴が含まれていても、それらはすべてこの一人の技術者の経歴として要約してください。
            - `document`フィールドには、技術者のスキル、経験、自己PRなどを総合的に要約した、検索しやすい自然な文章を作成してください。
            - `document`の文章の先頭には、必ず技術者名を含めてください。例：「実務経験15年のTK氏。Java(SpringBoot)を主軸に...」
            # JSON出力形式
            {{"engineers": [{{"name": "技術者の氏名を抽出", "document": "技術者のスキルや経歴の詳細を、検索しやすいように要約", "nationality": "国籍を抽出", "availability_date": "稼働可能日を抽出", "desired_location": "希望勤務地を抽出", "desired_salary": "希望単価を抽出", "main_skills": "主要なスキルをカンマ区切りで抽出"}}]}}
            # 本番: 以下のスキルシートから情報を抽出してください
            ---
            {text_content}
        """
    elif doc_type == 'job':
        return f"""
            あなたは、IT業界の「案件定義書」を読み解く専門家です。
            あなたの仕事は、与えられたテキストから**案件情報**を抽出し、指定されたJSON形式で整理することです。
            テキスト内に複数の案件情報が含まれている場合は、それぞれを個別のオブジェクトとしてリストにしてください。
            # 絶対的なルール
            - 出力は、指定されたJSON形式の文字列のみとし、前後に解説や```json ```のようなコードブロックの囲みを含めないでください。
            # 指示
            - `document`フィールドには、案件のスキルや業務内容の詳細を、後で検索しやすいように自然な文章で要約してください。
            - `document`の文章の先頭には、必ずプロジェクト名を含めてください。例：「社内SEプロジェクトの増員案件。設計、テスト...」
            # JSON出力形式
            {{"jobs": [{{"project_name": "案件名を抽出", "document": "案件のスキルや業務内容の詳細を、検索しやすいように要約", "nationality_requirement": "国籍要件を抽出", "start_date": "開始時期を抽出", "location": "勤務地を抽出", "unit_price": "単価や予算を抽出", "required_skills": "必須スキルや歓迎スキルをカンマ区切りで抽出"}}]}}
            # 本番: 以下の案件情報から情報を抽出してください
            ---
            {text_content}
        """
    return ""

def split_text_with_llm(text_content):
    classification_prompt = f"""
        あなたはテキスト分類の専門家です。以下のテキストが「案件情報」「技術者情報」「その他」のどれに最も当てはまるか判断し、指定された単語一つだけで回答してください。
        # 判断基準
        - 「スキルシート」「職務経歴書」「氏名」「年齢」といった単語が含まれていれば「技術者情報」の可能性が高い。
        - 「募集」「必須スキル」「歓迎スキル」「求める人物像」といった単語が含まれていれば「案件情報」の可能性が高い。
        - 上記のどちらでもない場合は「その他」と判断してください。
        # 回答形式
        - `案件情報`
        - `技術者情報`
        - `その他`
        # 分析対象テキスト
        ---
        {text_content[:2000]}
        ---
    """
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        st.write("📄 文書タイプを分類中...")
        response = model.generate_content(classification_prompt)
        doc_type = response.text.strip()
        st.write(f"✅ AIによる分類結果: **{doc_type}**")
    except Exception as e:
        st.error(f"文書の分類中にエラーが発生しました: {e}"); return None

    if "技術者情報" in doc_type:
        extraction_prompt = get_extraction_prompt('engineer', text_content)
    elif "案件情報" in doc_type:
        extraction_prompt = get_extraction_prompt('job', text_content)
    else:
        st.warning("このテキストは案件情報または技術者情報として分類されませんでした。処理をスキップします。"); return None

    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        with st.spinner("AIが情報を構造化中..."):
            response = model.generate_content(extraction_prompt, generation_config=generation_config, safety_settings=safety_settings)
        raw_text = response.text
        start_index = raw_text.find('{'); end_index = raw_text.rfind('}')
        if start_index != -1 and end_index != -1 and start_index < end_index:
            json_str = raw_text[start_index : end_index + 1]
            parsed_json = json.loads(json_str)
            if "技術者情報" in doc_type: parsed_json["jobs"] = []
            elif "案件情報" in doc_type: parsed_json["engineers"] = []
            return parsed_json
        else:
            st.error(f"LLMによる構造化に失敗しました。"); st.code(raw_text, language='text'); return None
    except json.JSONDecodeError as e:
        st.error(f"LLMによる構造化に失敗しました: {e}"); st.code(raw_text, language='text'); return None
    except Exception as e:
        st.error(f"LLMによる構造化に失敗しました: {e}");
        try: st.code(response.text, language='text')
        except NameError: st.text("レスポンスの取得にも失敗しました。")
        return None

@st.cache_data
def get_match_summary_with_llm(job_doc, engineer_doc):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    prompt = f"""
        あなたは、経験豊富なIT人材紹介のエージェントです。
        あなたの仕事は、提示された「案件情報」と「技術者情報」を比較し、客観的かつ具体的なマッチング評価を行うことです。
        # 絶対的なルール
        - `summary`は最も重要な項目です。絶対に省略せず、必ずS, A, B, C, Dのいずれかの文字列を返してください。
        # 指示
        以下の2つの情報を分析し、ポジティブな点と懸念点をリストアップしてください。最終的に、総合評価（summary）をS, A, B, C, Dの5段階で判定してください。
        - S: 完璧なマッチ, A: 非常に良いマッチ, B: 良いマッチ, C: 検討の余地あり, D: ミスマッチ
        # JSON出力形式
        {{"summary": "S, A, B, C, Dのいずれか", "positive_points": ["スキル面での合致点"], "concern_points": ["スキル面での懸念点"]}}
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
        start_index = raw_text.find('{'); end_index = raw_text.rfind('}')
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
        with conn.cursor() as cursor:
            query = f"SELECT * FROM {table_name} WHERE id = ANY(%s)"
            cursor.execute(query, (ids,))
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
        st.write(f"▶ 『{source_name}』(ID:{item_data['id']}) の類似候補は見つかりませんでした。"); return
    candidate_records = get_records_by_ids(candidate_table, ids)
    candidate_map = {record['id']: record for record in candidate_records}
    st.write(f"▶ 『{source_name}』(ID:{item_data['id']}) との類似候補 {len(ids)}件を評価します。")
    for sim, candidate_id in zip(similarities, ids):
        score = float(sim) * 100
        if score < MIN_SCORE_THRESHOLD: continue
        candidate_record = candidate_map.get(candidate_id)
        if not candidate_record: continue
        candidate_name = candidate_record.get('project_name') or candidate_record.get('name') or f"ID:{candidate_id}"
        job_doc, engineer_doc = (item_data['document'], candidate_record['document']) if item_type == 'job' else (candidate_record['document'], item_data['document'])
        job_id, engineer_id = (item_data['id'], candidate_record['id']) if item_type == 'job' else (candidate_record['id'], item_data['id'])
        llm_result = get_match_summary_with_llm(job_doc, engineer_doc)
        if llm_result and 'summary' in llm_result:
            grade = llm_result.get('summary')
            if grade in ['S', 'A', 'B']:
                cursor.execute('INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (job_id, engineer_id) DO NOTHING', (job_id, engineer_id, score, now_str, grade))
                st.write(f"  - 候補: 『{candidate_name}』 -> 評価: {grade} (スコア: {score:.2f}) ... ✅ DBに保存")
            else:
                st.write(f"  - 候補: 『{candidate_name}』 -> 評価: {grade} (スコア: {score:.2f}) ... ❌ スキップ")
        else:
            st.write(f"  - 候補: 『{candidate_name}』 -> LLM評価失敗のためスキップ")

# ▼▼▼【ここが修正箇所】▼▼▼
def process_single_content(source_data: dict):
    if not source_data: st.warning("処理するデータが空です。"); return False
    valid_attachments_content = [f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content') and not att.get('content', '').startswith("[") and not att.get('content', '').endswith("]")]
    if valid_attachments_content: st.write(f"ℹ️ {len(valid_attachments_content)}件の添付ファイルの内容を解析に含めます。")
    full_text_for_llm = source_data.get('body', '') + "".join(valid_attachments_content)
    if not full_text_for_llm.strip(): st.warning("解析対象のテキストがありません。"); return False
    
    parsed_data = split_text_with_llm(full_text_for_llm)
    if not parsed_data: return False
    
    new_jobs_data, new_engineers_data = parsed_data.get("jobs", []), parsed_data.get("engineers", [])
    if not new_jobs_data and not new_engineers_data: st.warning("LLMはテキストから案件情報または技術者情報を抽出できませんでした。"); return False
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # --- JSON保存用の処理 ---
            # 1. 元データからdatetimeオブジェクトを取得
            received_at_dt = source_data.get('received_at')
            
            # 2. JSON保存用にデータをコピー
            json_data_to_store = source_data.copy()
            
            # 3. datetimeオブジェクトを文字列に変換（JSONシリアライズのため）
            if isinstance(json_data_to_store.get('received_at'), datetime):
                json_data_to_store['received_at'] = json_data_to_store['received_at'].isoformat()
            
            # 4. 大きなデータ（本文と添付ファイル）を削除
            json_data_to_store.pop('body', None)
            json_data_to_store.pop('attachments', None)
            
            # 5. JSON文字列を作成
            source_json_str = json.dumps(json_data_to_store, ensure_ascii=False, indent=2)
            
            # --- DB登録処理 ---
            newly_added_jobs, newly_added_engineers = [], []
            
            for item_data in new_jobs_data:
                doc = item_data.get("document") or full_text_for_llm
                project_name = item_data.get("project_name", "名称未定の案件")
                meta_info = _build_meta_info_string('job', item_data)
                full_document = meta_info + doc
                # DBにはdatetimeオブジェクト(received_at_dt)を渡す
                cursor.execute('INSERT INTO jobs (project_name, document, source_data_json, created_at, received_at) VALUES (%s, %s, %s, %s, %s) RETURNING id', 
                               (project_name, full_document, source_json_str, now_str, received_at_dt))
                item_data['id'] = cursor.fetchone()[0]; item_data['document'] = full_document; newly_added_jobs.append(item_data)
            
            for item_data in new_engineers_data:
                doc = item_data.get("document") or full_text_for_llm
                engineer_name = item_data.get("name", "名称不明の技術者")
                meta_info = _build_meta_info_string('engineer', item_data)
                full_document = meta_info + doc
                # DBにはdatetimeオブジェクト(received_at_dt)を渡す
                cursor.execute('INSERT INTO engineers (name, document, source_data_json, created_at, received_at) VALUES (%s, %s, %s, %s, %s) RETURNING id', 
                               (engineer_name, full_document, source_json_str, now_str, received_at_dt))
                item_data['id'] = cursor.fetchone()[0]; item_data['document'] = full_document; newly_added_engineers.append(item_data)
            
            st.write("ベクトルインデックスを更新し、マッチング処理を開始します...")
            cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0'); all_active_jobs = cursor.fetchall()
            cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0'); all_active_engineers = cursor.fetchall()
            
            if all_active_jobs: update_index(JOB_INDEX_FILE, all_active_jobs)
            if all_active_engineers: update_index(ENGINEER_INDEX_FILE, all_active_engineers)
            
            for new_job in newly_added_jobs: run_matching_for_item(new_job, 'job', cursor, now_str)
            for new_engineer in newly_added_engineers: run_matching_for_item(new_engineer, 'engineer', cursor, now_str)
        conn.commit()
    return True
# ▲▲▲【修正ここまで】▲▲▲

def get_email_contents(msg) -> dict:
    subject = str(make_header(decode_header(msg["subject"]))) if msg["subject"] else ""
    from_ = str(make_header(decode_header(msg["from"]))) if msg["from"] else ""
    received_at = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None

    body_text, attachments = "", []
    if msg.is_multipart():
        for part in msg.walk():
            content_type, content_disposition = part.get_content_type(), str(part.get("Content-Disposition"))
            if 'text/plain' in content_type and 'attachment' not in content_disposition:
                charset = part.get_content_charset()
                try: body_text += part.get_payload(decode=True).decode(charset or 'utf-8', errors='ignore')
                except Exception: body_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
            if 'attachment' in content_disposition and (raw_filename := part.get_filename()):
                filename = str(make_header(decode_header(raw_filename)))
                st.write(f"📄 添付ファイル '{filename}' を発見しました。")
                file_bytes, lower_filename = part.get_payload(decode=True), filename.lower()
                if lower_filename.endswith(".pdf"): attachments.append({"filename": filename, "content": extract_text_from_pdf(file_bytes)})
                elif lower_filename.endswith(".docx"): attachments.append({"filename": filename, "content": extract_text_from_docx(file_bytes)})
                elif lower_filename.endswith(".txt"): attachments.append({"filename": filename, "content": file_bytes.decode('utf-8', errors='ignore')})
                else: st.write(f"ℹ️ 添付ファイル '{filename}' は未対応の形式のため、スキップします。")
    else:
        charset = msg.get_content_charset()
        try: body_text = msg.get_payload(decode=True).decode(charset or 'utf-8', errors='ignore')
        except Exception: body_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    
    return {"subject": subject, "from": from_, "received_at": received_at, "body": body_text.strip(), "attachments": attachments}

def fetch_and_process_emails():
    log_stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(log_stream):
            try: SERVER, USER, PASSWORD = st.secrets["EMAIL_SERVER"], st.secrets["EMAIL_USER"], st.secrets["EMAIL_PASSWORD"]
            except KeyError as e: st.error(f"メールサーバーの接続情報がSecretsに設定されていません: {e}"); return False, log_stream.getvalue()
            try: mail = imaplib.IMAP4_SSL(SERVER); mail.login(USER, PASSWORD); mail.select('inbox')
            except Exception as e: st.error(f"メールサーバーへの接続またはログインに失敗しました: {e}"); return False, log_stream.getvalue()
            total_processed_count, checked_count = 0, 0
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
                                        st.write("---")
                                        st.write(f"✅ メールID {email_id.decode()} を処理します。")
                                        received_at_str = source_data['received_at'].strftime('%Y-%m-%d %H:%M:%S') if source_data.get('received_at') else '取得不可'
                                        st.write(f"   受信日時: {received_at_str}")
                                        st.write(f"   差出人: {source_data.get('from', '取得不可')}")
                                        st.write(f"   件名: {source_data.get('subject', '取得不可')}")
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

# --- 残りの関数 (変更なし) ---
def hide_match(result_id):
    if not result_id: st.warning("IDが指定されていません。"); return False
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE matching_results SET is_hidden = 1 WHERE id = %s', (result_id,))
                if cursor.rowcount > 0: st.toast(f"マッチング結果 (ID: {result_id}) を非表示にしました。"); conn.commit(); return True
                else: st.warning(f"マッチング結果 (ID: {result_id}) が見つかりませんでした。"); return False
    except (Exception, psycopg2.Error) as e: st.error(f"DB更新エラー: {e}"); return False

def get_all_users():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, username FROM users ORDER BY id"); return cursor.fetchall()

def assign_user_to_job(job_id, user_id):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur: cur.execute("UPDATE jobs SET assigned_user_id = %s WHERE id = %s", (user_id, job_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e: print(f"担当者割り当てエラー: {e}"); conn.rollback(); return False

def set_job_visibility(job_id, is_hidden):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur: cur.execute("UPDATE jobs SET is_hidden = %s WHERE id = %s", (is_hidden, job_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e: print(f"表示状態の更新エラー: {e}"); conn.rollback(); return False

def assign_user_to_engineer(engineer_id, user_id):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur: cur.execute("UPDATE engineers SET assigned_user_id = %s WHERE id = %s", (user_id, engineer_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e: print(f"技術者への担当者割り当てエラー: {e}"); conn.rollback(); return False

def set_engineer_visibility(engineer_id, is_hidden):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur: cur.execute("UPDATE engineers SET is_hidden = %s WHERE id = %s", (is_hidden, engineer_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e: print(f"技術者の表示状態の更新エラー: {e}"); conn.rollback(); return False

def update_engineer_source_json(engineer_id, new_json_str):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur: cur.execute("UPDATE engineers SET source_data_json = %s WHERE id = %s", (new_json_str, engineer_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e: print(f"技術者のJSONデータ更新エラー: {e}"); conn.rollback(); return False

def generate_proposal_reply_with_llm(job_summary, engineer_summary, engineer_name, project_name):
    if not all([job_summary, engineer_summary, engineer_name, project_name]): return "情報が不足しているため、提案メールを生成できませんでした。"
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
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating proposal reply with LLM: {e}"); return f"提案メールの生成中にエラーが発生しました: {e}"

def save_match_grade(match_id, grade):
    if not grade: return False
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor: cursor.execute("UPDATE matching_results SET grade = %s WHERE id = %s", (grade, match_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e: print(f"Error saving match grade for match_id {match_id}: {e}"); conn.rollback(); return False

def get_evaluation_html(grade, font_size='2.5em'):
    if not grade: return ""
    color_map = {'S': '#00b894', 'A': '#28a745', 'B': '#17a2b8', 'C': '#ffc107', 'D': '#fd7e14', 'E': '#dc3545'}
    color = color_map.get(grade.upper(), '#6c757d') 
    style = f"color: {color}; font-size: {font_size}; font-weight: bold; text-align: center; line-height: 1; padding-top: 10px;"
    html_code = f"<div style='text-align: center; margin-bottom: 5px;'><span style='{style}'>{grade.upper()}</span></div><div style='text-align: center; font-size: 0.8em; color: #888;'>判定</div>"
    return html_code

def get_matching_result_details(result_id):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM matching_results WHERE id = %s", (result_id,))
                match_result = cursor.fetchone()
                if not match_result: return None
                cursor.execute("SELECT j.*, u.username as assignee_name FROM jobs j LEFT JOIN users u ON j.assigned_user_id = u.id WHERE j.id = %s", (match_result['job_id'],))
                job_data = cursor.fetchone()
                cursor.execute("SELECT e.*, u.username as assignee_name FROM engineers e LEFT JOIN users u ON e.assigned_user_id = u.id WHERE e.id = %s", (match_result['engineer_id'],))
                engineer_data = cursor.fetchone()
                return {"match_result": dict(match_result), "job_data": dict(job_data) if job_data else None, "engineer_data": dict(engineer_data) if engineer_data else None}
        except (Exception, psycopg2.Error) as e:
            print(f"マッチング詳細取得エラー: {e}"); return None

def re_evaluate_and_match_single_engineer(engineer_id):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM engineers WHERE id = %s", (engineer_id,))
                engineer_record = cursor.fetchone()
                if not engineer_record:
                    st.error(f"技術者ID:{engineer_id} が見つかりませんでした。"); return False
                source_data = json.loads(engineer_record['source_data_json'])
                full_text_for_llm = source_data.get('body', '') + "".join([f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content') and not att.get('content', '').startswith("[") and not att.get('content', '').endswith("]")])
                parsed_data = split_text_with_llm(full_text_for_llm)
                if not parsed_data or not parsed_data.get("engineers"):
                    st.error("LLMによる再評価で、技術者情報の抽出に失敗しました。"); return False
                item_data = parsed_data["engineers"][0]
                doc = item_data.get("document") or full_text_for_llm
                meta_info = _build_meta_info_string('engineer', item_data)
                new_full_document = meta_info + doc
                cursor.execute("UPDATE engineers SET document = %s WHERE id = %s", (new_full_document, engineer_id))
                cursor.execute("DELETE FROM matching_results WHERE engineer_id = %s", (engineer_id,))
                st.write(f"技術者ID:{engineer_id} の既存マッチング結果をクリアしました。")
                st.write("ベクトルインデックスを更新し、再マッチング処理を開始します...")
                cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0'); all_jobs = cursor.fetchall()
                cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0'); all_engineers = cursor.fetchall()
                if all_jobs: update_index(JOB_INDEX_FILE, all_jobs)
                if all_engineers: update_index(ENGINEER_INDEX_FILE, all_engineers)
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                engineer_data_for_matching = {'id': engineer_id, 'document': new_full_document, 'name': engineer_record['name']}
                run_matching_for_item(engineer_data_for_matching, 'engineer', cursor, now_str)
            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            conn.rollback(); st.error(f"再評価・再マッチング中にエラーが発生しました: {e}"); return False

def update_engineer_name(engineer_id, new_name):
    if not new_name or not new_name.strip(): return False
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor: cursor.execute("UPDATE engineers SET name = %s WHERE id = %s", (new_name.strip(), engineer_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e:
            print(f"技術者氏名の更新エラー: {e}"); conn.rollback(); return False

def _build_meta_info_string(item_type, item_data):
    meta_fields = []
    if item_type == 'job':
        meta_fields = [["国籍要件", "nationality_requirement"], ["開始時期", "start_date"], ["勤務地", "location"], ["単価", "unit_price"], ["必須スキル", "required_skills"]]
    elif item_type == 'engineer':
        meta_fields = [["国籍", "nationality"], ["稼働可能日", "availability_date"], ["希望勤務地", "desired_location"], ["希望単価", "desired_salary"], ["主要スキル", "main_skills"]]
    if not meta_fields: return "\n---\n"
    meta_parts = [f"[{display_name}: {item_data.get(key, '不明')}]" for display_name, key in meta_fields]
    return " ".join(meta_parts) + "\n---\n"

def update_match_status(match_id, new_status):
    if not match_id or not new_status: return False
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor: cursor.execute("UPDATE matching_results SET status = %s WHERE id = %s", (new_status, match_id))
            conn.commit(); return True
        except (Exception, psycopg2.Error) as e:
            print(f"ステータスの更新エラー: {e}"); conn.rollback(); return False
