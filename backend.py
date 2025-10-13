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
import re # スキル抽出のために re モジュールをインポート
import json


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
            # 具体例
            ## 入力テキスト:
            氏名: 山田 太郎
            年齢: 35歳
            得意技術: Java, Spring
            自己PR: Webアプリ開発が得意です。
            ## 出力JSON:
            {{"engineers": [{{"name": "山田 太郎", "document": "35歳の山田太郎氏。Java, Springを用いたWebアプリ開発が得意。", "main_skills": "Java, Spring"}}]}}
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

# ▼▼▼【ここが修正箇所】▼▼▼
def split_text_with_llm(text_content):
    """【二段階処理】1. 文書を分類し、2. 分類結果に応じて専用プロンプトで情報抽出を行う。"""
    classification_prompt = f"""
        あなたはテキスト分類の専門家です。以下のテキストが「案件情報」「技術者情報」「その他」のどれに最も当てはまるか判断し、指定された単語一つだけで回答してください。
        # 判断基準
        - 「スキルシート」「職務経歴書」「氏名」「年齢」といった単語が含まれていれば「技術者情報」の可能性が高い。
        - 「募集」「必須スキル」「歓迎スキル」「求める人物像」といった単語が含まれていれば「案件情報」の可能性が高い。
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
        
        # ▼▼▼【ここからがJSON抽出・修復ロジックです】▼▼▼
        json_str = None
        try:
            # 1. ```json ... ``` 形式のコードブロックを探す
            match = re.search(r'```json\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                # 2. コードブロックがない場合、最も大きな波括弧のペアを探す
                start_index = raw_text.find('{')
                end_index = raw_text.rfind('}')
                if start_index != -1 and end_index != -1 and start_index < end_index:
                    json_str = raw_text[start_index : end_index + 1]
                else:
                    st.error("LLMの応答から有効なJSON構造を抽出できませんでした。")
                    st.code(raw_text, language='text')
                    return None
            
            # 抽出した文字列をパース
            parsed_json = json.loads(json_str)

        except json.JSONDecodeError as e:
            # パースに失敗した場合、修復を試みる
            print(f"WARN: JSONのパースに失敗。修復を試みます。エラー: {e}")
            
            repaired_text = json_str or raw_text
            # 文字列内の不正な改行を置換
            repaired_text = re.sub(r'(?<!\\)\n', r'\\n', repaired_text)
            
            try:
                # 修復したテキストで再度パースを試みる
                print("INFO: 修復後のJSONで再パースを試みます。")
                parsed_json = json.loads(repaired_text)
            except json.JSONDecodeError as final_e:
                st.error(f"JSONの修復後もパースに失敗しました: {final_e}")
                st.write("修復を試みたJSON文字列:")
                st.code(repaired_text, language='json')
                return None
        # ▲▲▲【JSON抽出・修復ロジックここまで】▲▲▲

        if "技術者情報" in doc_type: parsed_json["jobs"] = []
        elif "案件情報" in doc_type: parsed_json["engineers"] = []
        return parsed_json
        
    except Exception as e:
        st.error(f"LLMによる構造化処理中に予期せぬエラーが発生しました: {e}");
        try: st.code(response.text, language='text')
        except NameError: st.text("レスポンスの取得にも失敗しました。")
        return None
    

@st.cache_data
def get_match_summary_with_llm(job_doc, engineer_doc):
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
    # ▼▼▼ 変更点 1: プロンプトの強化 ▼▼▼
    prompt = f"""
        あなたは、経験豊富なIT人材紹介のエージェントです。
        あなたの仕事は、提示された「案件情報」と「技術者情報」を比較し、客観的かつ具体的なマッチング評価を行うことです。
        
        # 絶対的なルール
        - 出力は、必ず指定されたJSON形式の文字列のみとしてください。解説や ```json ``` のような囲みは絶対に含めないでください。
        - JSON内のすべての文字列は、必ずダブルクォーテーション `"` で囲ってください。
        - 文字列の途中で改行しないでください。改行が必要な場合は `\\n` を使用してください。
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
    # ▲▲▲ 変更点 1 ここまで ▲▲▲

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


def _extract_skills_from_document(document: str, item_type: str) -> set:
    """
    documentのメタ情報からスキルセットを抽出するヘルパー関数。
    """
    if not document:
        return set()

    # 案件の場合は「必須スキル」、技術者の場合は「主要スキル」をターゲットにする
    key = "必須スキル" if item_type == 'job' else "主要スキル"
    
    # [キー: 値] の形式でメタ情報を正規表現で検索
    match = re.search(rf"\[{key}:\s*([^\]]+)\]", document)
    if not match:
        return set()

    # 抽出したスキル文字列を整形
    skills_str = match.group(1).strip()
    if not skills_str or skills_str.lower() in ['不明', 'none']:
        return set()
    
    # カンマや全角スペースで区切り、各スキルを小文字化・空白除去してセットに格納
    skills = {skill.strip().lower() for skill in re.split(r'[,、，\s]+', skills_str) if skill.strip()}
    return skills

# backend.py の run_matching_for_item 関数を修正

def run_matching_for_item(item_data, item_type, conn, now_str):
    # ▼▼▼【この関数全体を置き換えてください】▼▼▼
    with conn.cursor() as cursor:
        # 1. 検索対象のインデックス、テーブル、名称を決定
        if item_type == 'job':
            query_text, index_path = item_data['document'], ENGINEER_INDEX_FILE
            target_table_name = 'engineers'
            source_name = item_data.get('project_name', f"案件ID:{item_data['id']}")
        else:
            query_text, index_path = item_data['document'], JOB_INDEX_FILE
            target_table_name = 'jobs'
            source_name = item_data.get('name', f"技術者ID:{item_data['id']}")

        search_limit = TOP_K_CANDIDATES * 2

        # 2. Faissによる類似度検索を実行
        similarities, ids = search(query_text, index_path, top_k=search_limit)
        if not ids:
            st.write(f"▶ 『{source_name}』(ID:{item_data['id']}, {item_type}) の類似候補は見つかりませんでした。")
            return

        # 3. 検索結果の候補データをDBから一括取得
        candidate_records = get_records_by_ids(target_table_name, ids)
        candidate_map = {record['id']: record for record in candidate_records}

        # ▼▼▼ 変更点 1: 最初のログメッセージを修正 ▼▼▼
        st.write(f"▶ 『{source_name}』(ID:{item_data['id']}, {item_type}) の類似候補 **{len(ids)}件** を発見。スキルセットでフィルタリングします...")
        # ▲▲▲ 変更点 1 ここまで ▲▲▲

        source_skills = _extract_skills_from_document(item_data['document'], item_type)
        if not source_skills:
            st.write(f"  - 検索元『{source_name}』のスキル情報が抽出できなかったため、事前フィルタリングはスキップします。")

        # ステップA: スキルフィルタリングを行い、有効な候補リストを作成する
        valid_candidates = []
        for sim, candidate_id in zip(similarities, ids):
            if len(valid_candidates) >= TOP_K_CANDIDATES:
                break

            candidate_record = candidate_map.get(candidate_id)
            if not candidate_record:
                continue
            
            candidate_name = candidate_record.get('project_name') or candidate_record.get('name') or f"ID:{candidate_id}"

            if source_skills:
                candidate_item_type = 'engineer' if item_type == 'job' else 'job'
                candidate_skills = _extract_skills_from_document(candidate_record['document'], candidate_item_type)
                
                if not source_skills.intersection(candidate_skills):
                    # このログは詳細すぎる場合はコメントアウトしても良い
                    # st.write(f"  - 候補: 『{candidate_name}』 -> スキル不一致のため事前除外。")
                    continue
            
            valid_candidates.append({
                'sim': sim,
                'id': candidate_id,
                'record': candidate_record,
                'name': candidate_name
            })
        
        # ▼▼▼ 変更点 2: フィルタリング後の結果ログを修正 ▼▼▼
        if not valid_candidates:
            st.write(f"✅ スキルが一致する有効な候補は見つかりませんでした。処理を終了します。")
            return

        st.write(f"✅ スキルが一致した有効な候補 **{len(valid_candidates)}件** に絞り込みました。AI評価を開始します...")
        # ▲▲▲ 変更点 2 ここまで ▲▲▲

        # ステップB: 有効な候補リストに対してAI評価とDB保存を行う
        for candidate_info in valid_candidates:
            score = float(candidate_info['sim']) * 100

            if score < MIN_SCORE_THRESHOLD:
                continue

            # 5. LLM評価のための案件・技術者情報を準備
            if item_type == 'job':
                job_doc, engineer_doc = item_data['document'], candidate_info['record']['document']
                job_id, engineer_id = item_data['id'], candidate_info['id']
            else:
                job_doc, engineer_doc = candidate_info['record']['document'], item_data['document']
                job_id, engineer_id = candidate_info['id'], item_data['id']

            # 6. LLMによるマッチング評価を実行
            llm_result = get_match_summary_with_llm(job_doc, engineer_doc)

            # 7. LLMの評価結果に基づいてDBへの保存を判断
            if llm_result and 'summary' in llm_result:
                grade = llm_result.get('summary')
                positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
                concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)

                if grade in ['S', 'A', 'B']:
                    try:
                        cursor.execute(
                            'INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade, positive_points, concern_points) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (job_id, engineer_id) DO NOTHING',
                            (job_id, engineer_id, score, now_str, grade, positive_points, concern_points)
                        )
                        st.write(f"  - 候補: 『{candidate_info['name']}』 -> マッチング評価: **{grade}** (スコア: {score:.2f}) ... ✅ DBに保存")
                    except Exception as e:
                        st.write(f"  - DB保存中にエラー: {e}")
                else:
                    st.write(f"  - 候補: 『{candidate_info['name']}』 -> マッチング評価: **{grade}** (スコア: {score:.2f}) ... ❌ スキップ")
            else:
                st.write(f"  - 候補: 『{candidate_info['name']}』 -> LLM評価失敗のためスキップ")



# backend.py

def process_single_content(source_data: dict, progress_bar, base_progress: float, progress_per_email: float):
    """
    単一のメールコンテンツを処理し、進捗バーを更新する。
    
    Args:
        source_data (dict): メールから抽出されたデータ。
        progress_bar: Streamlitのプログレスバーオブジェクト。
        base_progress (float): このメール処理開始前の進捗値。
        progress_per_email (float): このメール1件あたりの進捗の重み。
    """
    if not source_data: 
        st.warning("処理するデータが空です。")
        return False

    # ステップ1: コンテンツ解析 (LLM) - このメール処理の50%を占めると仮定
    valid_attachments_content = [f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content') and not att.get('content', '').startswith("[") and not att.get('content', '').endswith("]")]
    if valid_attachments_content: 
        st.write(f"ℹ️ {len(valid_attachments_content)}件の添付ファイルの内容を解析に含めます。")
    full_text_for_llm = source_data.get('body', '') + "".join(valid_attachments_content)
    if not full_text_for_llm.strip(): 
        st.warning("解析対象のテキストがありません。")
        return False
    
    # split_text_with_llm は内部でスピナーやログを表示する
    parsed_data = split_text_with_llm(full_text_for_llm)
    
    # 進捗バーを更新 (コンテンツ解析完了)
    # このメールに割り当てられた進捗のうち、50%が完了したとみなす
    current_progress = base_progress + (progress_per_email * 0.5)
    progress_bar.progress(current_progress, text="コンテンツ解析完了")

    if not parsed_data: 
        return False
    
    new_jobs_data, new_engineers_data = parsed_data.get("jobs", []), parsed_data.get("engineers", [])
    if not new_jobs_data and not new_engineers_data: 
        st.warning("LLMはテキストから案件情報または技術者情報を抽出できませんでした。")
        return False
    
    # ステップ2: マッチング処理 - このメール処理の残りの50%
    st.write("ベクトルインデックスを更新し、マッチング処理を開始します...")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            received_at_dt = source_data.get('received_at')
            json_data_to_store = source_data.copy()
            if isinstance(json_data_to_store.get('received_at'), datetime):
                json_data_to_store['received_at'] = json_data_to_store['received_at'].isoformat()
            source_json_str = json.dumps(json_data_to_store, ensure_ascii=False, indent=2)

            newly_added_jobs, newly_added_engineers = [], []
            
            for item_data in new_jobs_data:
                doc = item_data.get("document") or full_text_for_llm
                project_name = item_data.get("project_name", "名称未定の案件")
                meta_info = _build_meta_info_string('job', item_data)
                full_document = meta_info + doc
                cursor.execute('INSERT INTO jobs (project_name, document, source_data_json, created_at, received_at) VALUES (%s, %s, %s, %s, %s) RETURNING id', (project_name, full_document, source_json_str, now_str, received_at_dt))
                item_data['id'] = cursor.fetchone()[0]
                item_data['document'] = full_document
                newly_added_jobs.append(item_data)
            
            for item_data in new_engineers_data:
                doc = item_data.get("document") or full_text_for_llm
                engineer_name = item_data.get("name", "名称不明の技術者")
                meta_info = _build_meta_info_string('engineer', item_data)
                full_document = meta_info + doc
                cursor.execute('INSERT INTO engineers (name, document, source_data_json, created_at, received_at) VALUES (%s, %s, %s, %s, %s) RETURNING id', (engineer_name, full_document, source_json_str, now_str, received_at_dt))
                item_data['id'] = cursor.fetchone()[0]
                item_data['document'] = full_document
                newly_added_engineers.append(item_data)
            
            # インデックス更新
            cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0'); all_active_jobs = cursor.fetchall()
            cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0'); all_active_engineers = cursor.fetchall()
            if all_active_jobs: update_index(JOB_INDEX_FILE, all_active_jobs)
            if all_active_engineers: update_index(ENGINEER_INDEX_FILE, all_active_engineers)
            
            # 再マッチング (run_matching_for_item は内部でログを出力する)
            for new_job in newly_added_jobs:
                run_matching_for_item(new_job, 'job', conn, now_str)
            for new_engineer in newly_added_engineers:
                run_matching_for_item(new_engineer, 'engineer', conn, now_str)
        conn.commit()

    # 進捗バーを更新 (このメールの処理が100%完了)
    current_progress = base_progress + progress_per_email
    progress_bar.progress(current_progress, text="マッチング処理完了")
    
    return True





def extract_text_from_pdf(file_bytes):
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
        return text if text.strip() else "[PDFテキスト抽出失敗: 内容が空または画像PDF]"
    except Exception as e:
        return f"[PDFテキスト抽出エラー: {e}]"

def extract_text_from_docx(file_bytes):
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text if text.strip() else "[DOCXテキスト抽出失敗: 内容が空]"
    except Exception as e:
        return f"[DOCXテキスト抽出エラー: {e}]"

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




# backend.py

def fetch_and_process_emails():
    try:
        # プログレスバーの初期化と重み付け定義
        progress_bar = st.progress(0, text="処理を開始します...")
        
        WEIGHT_CONNECT = 0.05  # サーバー接続に5%
        WEIGHT_FETCH_IDS = 0.05 # メールIDリスト取得に5%
        WEIGHT_LOOP = 0.90     # メールごとのループ処理全体で90%

        # メールサーバー接続
        try:
            SERVER, USER, PASSWORD = st.secrets["EMAIL_SERVER"], st.secrets["EMAIL_USER"], st.secrets["EMAIL_PASSWORD"]
        except KeyError as e:
            st.error(f"メールサーバーの接続情報がSecretsに設定されていません: {e}")
            return False, ""
        
        try:
            mail = imaplib.IMAP4_SSL(SERVER)
            mail.login(USER, PASSWORD)
            mail.select('inbox')
            progress_bar.progress(WEIGHT_CONNECT, text="メールサーバー接続完了")
        except Exception as e:
            st.error(f"メールサーバーへの接続またはログインに失敗しました: {e}")
            return False, ""
        
        total_processed_count, checked_count = 0, 0
        try:
            with st.status("最新の未読メールを取得・処理中...", expanded=True) as status:
                _, messages = mail.search(None, 'UNSEEN')
                email_ids = messages[0].split()
                
                progress_bar.progress(WEIGHT_CONNECT + WEIGHT_FETCH_IDS, text="未読メールIDリスト取得完了")
                
                if not email_ids:
                    st.write("処理対象の未読メールは見つかりませんでした。")
                else:
                    latest_ids = email_ids[::-1][:10]
                    checked_count = len(latest_ids)
                    st.write(f"最新の未読メール {checked_count}件をチェックします。")

                    # メール1件あたりの進捗の割合を計算
                    progress_per_email = WEIGHT_LOOP / checked_count if checked_count > 0 else 0
                    
                    for i, email_id in enumerate(latest_ids):
                        # このループ開始時点でのベースとなる進捗
                        base_progress_for_this_email = (WEIGHT_CONNECT + WEIGHT_FETCH_IDS) + (i * progress_per_email)
                        
                        # メール内容取得の進捗
                        progress_bar.progress(base_progress_for_this_email, text=f"メール({i+1}/{checked_count})の内容を取得中...")
                        
                        _, msg_data = mail.fetch(email_id, '(RFC822)')
                        for response_part in msg_data:
                            if isinstance(response_part, tuple):
                                msg = email.message_from_bytes(response_part[1])
                                source_data = get_email_contents(msg)
                                
                                # メール内容取得完了後の進捗 (メール1件の処理の20%を割り当て)
                                fetch_complete_progress = base_progress_for_this_email + (progress_per_email * 0.2)
                                progress_bar.progress(fetch_complete_progress, text=f"メール({i+1}/{checked_count})の内容取得完了")

                                if source_data['body'] or source_data['attachments']:
                                    st.write("---")
                                    st.write(f"✅ メールID {email_id.decode()} を処理します。")
                                    received_at_str = source_data['received_at'].strftime('%Y-%m-%d %H:%M:%S') if source_data.get('received_at') else '取得不可'
                                    st.write(f"   受信日時: {received_at_str}")
                                    st.write(f"   差出人: {source_data.get('from', '取得不可')}")
                                    st.write(f"   件名: {source_data.get('subject', '取得不可')}")
                                    
                                    # process_single_content に進捗管理情報を渡す
                                    # 残りの80%の進捗をこの関数に委ねる
                                    if process_single_content(source_data, progress_bar, fetch_complete_progress, progress_per_email * 0.8):
                                        total_processed_count += 1
                                        mail.store(email_id, '+FLAGS', '\\Seen')
                                else:
                                    st.write(f"✖️ メールID {email_id.decode()} は本文も添付ファイルも無いため、スキップします。")
                                    # スキップした場合でも、このメールの進捗は完了したことにする
                                    final_progress_for_this_email = base_progress_for_this_email + progress_per_email
                                    progress_bar.progress(final_progress_for_this_email, text=f"メール({i+1}/{checked_count}) スキップ完了")
                        
                        st.write(f"({i+1}/{checked_count}) チェック完了")
                
                status.update(label="メールチェック完了", state="complete")
        finally:
            mail.close()
            mail.logout()
    
        # 最終的にプログレスバーを100%にする
        progress_bar.progress(1.0, text="全処理完了！")
        
        # 処理完了後のメッセージ
        if checked_count > 0:
            if total_processed_count > 0:
                st.success(f"チェックした {checked_count} 件のメールのうち、{total_processed_count} 件からデータを抽出し、保存しました。")
                st.balloons()
            else:
                st.warning(f"メールを {checked_count} 件チェックしましたが、データベースに保存できる情報は見つかりませんでした。")
        else:
            st.info("処理対象となる新しい未読メールはありませんでした。")
            
        return True, "" # ログストリームは使わないので空文字列を返す
    except Exception as e:
        st.error(f"予期せぬエラーが発生しました: {e}")
        return False, ""





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


def re_evaluate_existing_matches_for_engineer(engineer_id):
    """
    【パターンA】
    指定された技術者の既存のマッチング結果すべてに対して、AI評価のみを再実行し、DBを更新する。
    新しいマッチングは行わない。
    """
    if not engineer_id:
        st.error("技術者IDが指定されていません。")
        return False

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. 技術者の最新ドキュメントを取得
            cursor.execute("SELECT document FROM engineers WHERE id = %s", (engineer_id,))
            engineer_record = cursor.fetchone()
            if not engineer_record:
                st.error(f"技術者ID:{engineer_id} が見つかりませんでした。")
                return False
            engineer_doc = engineer_record['document']

            # 2. この技術者に関連する、表示中のマッチング結果を取得
            cursor.execute(
                """
                SELECT r.id as match_id, j.id as job_id, j.document as job_document, j.project_name
                FROM matching_results r
                JOIN jobs j ON r.job_id = j.id
                WHERE r.engineer_id = %s AND r.is_hidden = 0 AND j.is_hidden = 0
                """,
                (engineer_id,)
            )
            existing_matches = cursor.fetchall()

            if not existing_matches:
                st.info("この技術者には再評価対象のマッチング結果がありません。")
                return True # 処理対象がないので成功とみなす

            st.write(f"{len(existing_matches)}件の既存マッチングに対して再評価を実行します。")
            
            # 3. 各マッチングに対してAI評価を再実行
            success_count = 0
            for match in existing_matches:
                st.write(f"  - 案件『{match['project_name']}』とのマッチングを再評価中...")
                
                # AI評価を呼び出し
                llm_result = get_match_summary_with_llm(match['job_document'], engineer_doc)
                
                # DBを更新
                if update_match_evaluation(match['match_id'], llm_result):
                    st.write(f"    -> 新しい評価: **{llm_result.get('summary')}** ... ✅ 更新完了")
                    success_count += 1
                else:
                    st.write(f"    -> 評価または更新に失敗しました。")
        
        # この関数はDBの変更を伴わないので、conn.commit()は不要 (update_match_evaluation内で完結)
        return success_count == len(existing_matches)

    except (Exception, psycopg2.Error) as e:
        st.error(f"再評価処理中にエラーが発生しました: {e}")
        return False
    finally:
        if conn:
            conn.close()



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


def delete_job(job_id):
    """
    指定された案件IDのレコードを jobs テーブルから削除する。
    ON DELETE CASCADE 制約により、関連する matching_results のレコードも自動的に削除される。
    
    Args:
        job_id (int): 削除対象の案件ID。
        
    Returns:
        bool: 削除が成功した場合はTrue、失敗した場合はFalse。
    """
    if not job_id:
        print("削除対象の案件IDが指定されていません。")
        return False
        
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                # 案件自体を削除する (ON DELETE CASCADE により関連データも削除される)
                cursor.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
                deleted_rows = cursor.rowcount
                print(f"Deleted {deleted_rows} job record with id {job_id}.")
            
            conn.commit()
            
            # 案件が1件以上削除されたら成功とみなす
            return deleted_rows > 0
            
        except (Exception, psycopg2.Error) as e:
            print(f"案件削除中にデータベースエラーが発生しました: {e}")
            conn.rollback() # エラーが発生した場合は変更を元に戻す
            return False
        

# backend.py の末尾あたりに追加

def delete_engineer(engineer_id):
    """
    指定された技術者IDのレコードを engineers テーブルから削除する。
    ON DELETE CASCADE 制約により、関連する matching_results のレコードも自動的に削除される。
    
    Args:
        engineer_id (int): 削除対象の技術者ID。
        
    Returns:
        bool: 削除が成功した場合はTrue、失敗した場合はFalse。
    """
    if not engineer_id:
        print("削除対象の技術者IDが指定されていません。")
        return False
        
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                # 技術者自体を削除する (ON DELETE CASCADE により関連データも削除される)
                cursor.execute("DELETE FROM engineers WHERE id = %s", (engineer_id,))
                deleted_rows = cursor.rowcount
                print(f"Deleted {deleted_rows} engineer record with id {engineer_id}.")
            
            conn.commit()
            
            # 技術者が1件以上削除されたら成功とみなす
            return deleted_rows > 0
            
        except (Exception, psycopg2.Error) as e:
            print(f"技術者削除中にデータベースエラーが発生しました: {e}")
            conn.rollback() # エラーが発生した場合は変更を元に戻す
            return False

def update_job_source_json(job_id, new_json_str):
    """
    案件のsource_data_jsonを更新する。
    """
    if not job_id or not new_json_str:
        return False
        
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE jobs SET source_data_json = %s WHERE id = %s", (new_json_str, job_id))
            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            print(f"案件のJSONデータ更新エラー: {e}")
            conn.rollback()
            return False
        

def update_match_evaluation(match_id, llm_result):
    """
    指定されたマッチングIDの評価結果を更新するヘルパー関数。
    """
    if not llm_result or 'summary' not in llm_result:
        return False
        
    grade = llm_result.get('summary')
    positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
    concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)
    
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE matching_results SET grade = %s, positive_points = %s, concern_points = %s WHERE id = %s",
                    (grade, positive_points, concern_points, match_id)
                )
            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            print(f"マッチング評価の更新エラー (ID: {match_id}): {e}")
            conn.rollback()
            return False


def re_evaluate_and_match_single_engineer(engineer_id):
    """
    【クリア＆再マッチング】
    指定された技術者のdocumentを最新化し、既存のマッチングをクリア後、
    再度すべての案件とマッチングを実行する。
    """
    if not engineer_id:
        st.error("技術者IDが指定されていません。")
        return False

    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                # 1. 技術者の最新のsource_data_jsonを取得
                cursor.execute("SELECT source_data_json, name FROM engineers WHERE id = %s", (engineer_id,))
                engineer_record = cursor.fetchone()
                if not engineer_record or not engineer_record['source_data_json']:
                    st.error(f"技術者ID:{engineer_id} の元情報が見つかりませんでした。")
                    return False
                
                st.write("📄 元情報から最新のドキュメントを生成します...")
                source_data = json.loads(engineer_record['source_data_json'])
                full_text_for_llm = source_data.get('body', '') + "".join([f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content') and not att.get('content', '').startswith("[") and not att.get('content', '').endswith("]")])
                
                # 2. split_text_with_llmでdocumentを再生成
                parsed_data = split_text_with_llm(full_text_for_llm)
                if not parsed_data or not parsed_data.get("engineers"):
                    st.error("LLMによる情報抽出（再評価）に失敗しました。")
                    return False
                
                item_data = parsed_data["engineers"][0]
                doc = item_data.get("document") or full_text_for_llm
                meta_info = _build_meta_info_string('engineer', item_data)
                new_full_document = meta_info + doc
                
                # 3. engineersテーブルのdocumentを更新
                cursor.execute("UPDATE engineers SET document = %s WHERE id = %s", (new_full_document, engineer_id))
                st.write("✅ 技術者のAI要約情報を更新しました。")

                # 4. 既存のマッチング結果を削除
                # ON DELETE CASCADEが設定されていれば不要だが、安全のため明示的に実行
                cursor.execute("DELETE FROM matching_results WHERE engineer_id = %s", (engineer_id,))
                st.write(f"🗑️ 技術者ID:{engineer_id} の既存マッチング結果をクリアしました。")

                # 5. インデックスを再構築
                st.write("🔄 ベクトルインデックスを更新し、再マッチング処理を開始します...")
                cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0'); all_active_jobs = cursor.fetchall()
                cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0'); all_active_engineers = cursor.fetchall()
                if all_active_jobs: update_index(JOB_INDEX_FILE, all_active_jobs)
                if all_active_engineers: update_index(ENGINEER_INDEX_FILE, all_active_engineers)
                
                # 6. 再マッチングを実行
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                engineer_data_for_matching = {
                    'id': engineer_id, 
                    'document': new_full_document, 
                    'name': engineer_record['name']
                }
                run_matching_for_item(engineer_data_for_matching, 'engineer', conn, now_str) # cursorではなくconnを渡す

            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            conn.rollback()
            st.error(f"再評価・再マッチング中にエラーが発生しました: {e}")
            return False
        

def save_proposal_text(match_id, text):
    """
    指定されたマッチングIDに対して、生成された提案メールのテキストを保存します。
    """
    if not match_id or text is None:
        return False
        
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE matching_results SET proposal_text = %s WHERE id = %s",
                    (text, match_id)
                )
            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            print(f"Error saving proposal text for match_id {match_id}: {e}")
            conn.rollback()
            return False
        