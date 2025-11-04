import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import faiss
from sentence_transformers import SentenceTransformer
import numpy as np
import os
import google.generativeai as genai
import json

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
import pandas as pd

from datetime import datetime, date, time, timedelta
import pytz # ★★★ タイムゾーンを扱うために追加 ★★★



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
#@st.cache_data
def load_app_config():
    try:
        with open("config.toml", "r", encoding="utf-8") as f:
            return toml.load(f)
    except FileNotFoundError:
        return {
                "app": {"title": "Universal AI Agent (Default)"}, "messages": {"sales_staff_notice": ""},
                "email_processing": {"fetch_limit": 10} # デフォルト値にも追加
                }
    
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


# backend.py

def split_text_with_llm(text_content: str) -> (dict | None, list):
    """
    【UI用・修正版】
    文書を分類し、情報抽出を行う。進捗を st.write で表示し、
    最終的に (結果, ログリスト) のタプルを返す。
    """
    logs = []

    conn = get_db_connection() # この関数はUIから呼ばれる前提
    if not conn:
        logs.append("❌ DB接続エラーにより、処理を中断しました。")
        return None, logs
    
    with conn.cursor() as cur:
            # --- 1. 文書タイプの分類 ---
            # ★★★ AIアクティビティログを記録 (分類) ★★★
            cur.execute("INSERT INTO ai_activity_log (activity_type) VALUES ('classification')")
            conn.commit()


    # この関数内で発生したログを収集するためのリスト
    # UI表示とは別に、呼び出し元に返す
    logs_for_caller = []
    
    # --- 1. 文書タイプの分類 ---
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
        
        # UIに直接進捗を表示
        st.write("📄 文書タイプを分類中...")
        logs_for_caller.append("📄 文書タイプを分類中...") # 呼び出し元用のログにも追加

        response = model.generate_content(classification_prompt)
        doc_type = response.text.strip()

        st.write(f"✅ AIによる分類結果: **{doc_type}**")
        logs_for_caller.append(f"✅ AIによる分類結果: **{doc_type}**")

    except Exception as e:
        st.error(f"文書の分類中にエラーが発生しました: {e}")
        logs_for_caller.append(f"❌ 文書の分類中にエラーが発生しました: {e}")
        return None, logs_for_caller # ★ 修正: 必ずタプルを返す

    # --- 2. 抽出プロンプトの選択 ---
    if "技術者情報" in doc_type:
        extraction_prompt = get_extraction_prompt('engineer', text_content)
    elif "案件情報" in doc_type:
        extraction_prompt = get_extraction_prompt('job', text_content)
    else:
        st.warning("このテキストは案件情報または技術者情報として分類されませんでした。処理をスキップします。")
        logs_for_caller.append("⚠️ このテキストは案件情報または技術者情報として分類されませんでした。")
        return None, logs_for_caller # ★ 修正: 必ずタプルを返す

    # --- 3. 構造化処理 ---
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    
    try:
        with st.spinner("AIが情報を構造化中..."):
            logs_for_caller.append("🤖 AIが情報を構造化中...")
            response = model.generate_content(extraction_prompt, generation_config=generation_config, safety_settings=safety_settings)
        
        raw_text = response.text
        
        # --- 4. JSONの抽出・修復 ---
        parsed_json = None
        start_index = raw_text.find('{')
        if start_index == -1:
            st.error("LLM応答からJSON開始文字'{'が見つかりません。")
            logs_for_caller.append("❌ LLM応答からJSON開始文字'{'が見つかりません。")
            return None, logs_for_caller

        brace_counter, end_index = 0, -1
        for i in range(start_index, len(raw_text)):
            char = raw_text[i]
            if char == '{': brace_counter += 1
            elif char == '}': brace_counter -= 1
            if brace_counter == 0:
                end_index = i
                break
        
        if end_index == -1:
            st.error("LLM応答のJSON構造が壊れています（括弧の対応が取れません）。")
            logs_for_caller.append("❌ LLM応答のJSON構造が壊れています（括弧の対応が取れません）。")
            return None, logs_for_caller

        json_str = raw_text[start_index : end_index + 1]
        try:
            parsed_json = json.loads(json_str)
            logs_for_caller.append("✅ JSONのパースに成功しました。")
        except json.JSONDecodeError as e:
            logs_for_caller.append(f"⚠️ JSONパース失敗。修復試行... (エラー: {e})")
            repaired_text = re.sub(r',\s*([\}\]])', r'\1', re.sub(r'(?<!\\)\n', r'\\n', json_str))
            try:
                parsed_json = json.loads(repaired_text)
                logs_for_caller.append("✅ JSONの修復と再パースに成功しました。")
            except json.JSONDecodeError as final_e:
                st.error(f"JSON修復後もパース失敗: {final_e}")
                logs_for_caller.append(f"❌ JSON修復後もパース失敗: {final_e}")
                return None, logs_for_caller

        # --- 5. 成功時の戻り値 ---
        if "技術者情報" in doc_type:
            if "jobs" not in parsed_json: parsed_json["jobs"] = []
        elif "案件情報" in doc_type:
            if "engineers" not in parsed_json: parsed_json["engineers"] = []

        # ★ 修正: 成功時も必ず「辞書オブジェクト」とログのタプルを返す
        return parsed_json, logs_for_caller

    except Exception as e:
        st.error(f"LLMによる構造化処理中に予期せぬエラーが発生しました: {e}")
        logs_for_caller.append(f"❌ LLMによる構造化処理中に予期せぬエラーが発生しました: {e}")
        try: st.code(response.text, language='text')
        except NameError: st.text("レスポンスの取得にも失敗しました。")
        
        # ★ 修正: 例外発生時も必ずタプルを返す
        return None, logs_for_caller





#@st.cache_data
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

        # ★★★【ここからが修正の核】★★★
        # 1. 最初の '{' を探す
        start_index = raw_text.find('{')
        if start_index == -1:
            print(f"ERROR: get_match_summary_with_llm - No JSON object found in response: {raw_text}")
            return None

        # 2. '{' と '}' の対応を数えて、最初の完全なJSONオブジェクトの終わりを見つける
        brace_counter = 0
        end_index = -1
        for i in range(start_index, len(raw_text)):
            char = raw_text[i]
            if char == '{':
                brace_counter += 1
            elif char == '}':
                brace_counter -= 1
            
            # brace_counterが0になった最初の地点がJSONの終わり
            if brace_counter == 0:
                end_index = i
                break
        
        if end_index == -1:
            print(f"ERROR: get_match_summary_with_llm - Incomplete JSON object in response: {raw_text}")
            return None

        json_str = raw_text[start_index : end_index + 1]
        # ★★★【修正ここまで】★★★

        # パースと修復のロジックは前回と同じ
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"WARN: Initial JSON parse failed: {e}. Attempting to repair...")
            repaired_str = re.sub(r',\s*([\}\]])', r'\1', json_str)
            repaired_str = re.sub(r'(?<!\\)\n', r'\\n', repaired_str)
            try:
                print("INFO: Retrying parse with repaired JSON string.")
                return json.loads(repaired_str)
            except json.JSONDecodeError as final_e:
                print(f"ERROR: JSON repair failed. Final parse error: {final_e}")
                print(f"Original JSON string: {json_str}")
                return None

    except Exception as e:
        print(f"ERROR: get_match_summary_with_llm - Exception during LLM call: {e}")
        return None
    
    

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

# backend.py の run_matching_for_item 関数をこちらに置き換えてください

def run_matching_for_item(item_data, item_type, conn, now_str):
    # ▼▼▼【この関数全体を置き換えてください】▼▼▼
    with conn.cursor() as cursor:
        # 1. 検索対象のインデックス、テーブル、名称を決定
        if item_type == 'job':
            query_text, index_path = item_data['document'], ENGINEER_INDEX_FILE
            target_table_name = 'engineers'
            source_name = item_data.get('project_name', f"案件ID:{item_data['id']}")
        else: # item_type == 'engineer'
            query_text, index_path = item_data['document'], JOB_INDEX_FILE
            target_table_name = 'jobs'
            source_name = item_data.get('name', f"技術者ID:{item_data['id']}")

        # TOP_K_CANDIDATESはAI評価の上限数なので、ベクトル検索時は少し多めに取得する
        search_limit = TOP_K_CANDIDATES * 2

        # 2. Faissによる類似度検索を実行
        similarities, ids = search(query_text, index_path, top_k=search_limit)
        if not ids:
            st.write(f"▶ 『{source_name}』(ID:{item_data['id']}) の類似候補は見つかりませんでした。")
            return

        # 3. 検索結果の候補データをDBから一括取得
        candidate_records = get_records_by_ids(target_table_name, ids)
        candidate_map = {record['id']: record for record in candidate_records}

        st.write(f"▶ 『{source_name}』(ID:{item_data['id']}) の類似候補 **{len(ids)}件** を発見。")
        
        # ▼▼▼【ここからがスキルフィルタリングの修正箇所です】▼▼▼

        # --- スキルフィルタリングを一時的に無効化 ---
        st.info("ℹ️ 現在、スキルによる事前フィルタリングは無効化されています。すべての類似候補をAI評価の対象とします。")
        
        valid_candidates = []
        for sim, candidate_id in zip(similarities, ids):
            # AI評価の対象を TOP_K_CANDIDATES 件に絞る
            if len(valid_candidates) >= TOP_K_CANDIDATES:
                break
            
            candidate_record = candidate_map.get(candidate_id)
            if not candidate_record: continue
            
            valid_candidates.append({
                'sim': sim,
                'id': candidate_id,
                'record': candidate_record,
                'name': candidate_record.get('project_name') or candidate_record.get('name') or f"ID:{candidate_id}"
            })
        
        # --- 将来的に再度有効化するための元コード（コメントアウト） ---
        #
        # source_skills = _extract_skills_from_document(item_data['document'], item_type)
        # if not source_skills:
        #     st.write(f"  - 検索元『{source_name}』のスキル情報が抽出できず、フィルタリングはスキップします。")
        #     for sim, candidate_id in zip(similarities, ids):
        #         if len(valid_candidates) >= TOP_K_CANDIDATES: break
        #         candidate_record = candidate_map.get(candidate_id)
        #         if not candidate_record: continue
        #         valid_candidates.append({
        #             'sim': sim, 'id': candidate_id, 'record': candidate_record,
        #             'name': candidate_record.get('project_name') or candidate_record.get('name') or f"ID:{candidate_id}"
        #         })
        # else:
        #     SKILL_MATCH_RATIO_THRESHOLD = 0.5  # 例: 50%
        #     st.write(f"  - スキルフィルタリング条件: 一致率が {SKILL_MATCH_RATIO_THRESHOLD*100:.0f}% 以上の候補を対象とします。")
        #     for sim, candidate_id in zip(similarities, ids):
        #         if len(valid_candidates) >= TOP_K_CANDIDATES: break
        #         candidate_record = candidate_map.get(candidate_id)
        #         if not candidate_record: continue
        #         candidate_item_type = 'engineer' if item_type == 'job' else 'job'
        #         candidate_skills = _extract_skills_from_document(candidate_record['document'], candidate_item_type)
        #         intersection_count = len(source_skills.intersection(candidate_skills))
        #         match_ratio = intersection_count / len(source_skills) if len(source_skills) > 0 else 0
        #         if match_ratio >= SKILL_MATCH_RATIO_THRESHOLD:
        #             valid_candidates.append({
        #                 'sim': sim, 'id': candidate_id, 'record': candidate_record,
        #                 'name': candidate_record.get('project_name') or candidate_record.get('name') or f"ID:{candidate_id}"
        #             })
        
        # ▲▲▲【スキルフィルタリングの修正ここまで】▲▲▲

        if not valid_candidates:
            st.write(f"✅ 類似候補は見つかりましたが、有効なレコードがありませんでした。処理を終了します。")
            return

        st.write(f"✅ AI評価対象の候補を **{len(valid_candidates)}件** に絞り込みました。AI評価を開始します...")

        # 5. 有効な候補リストに対してAI評価とDB保存を行う
        for candidate_info in valid_candidates:
            score = float(candidate_info['sim']) * 100
            if score < MIN_SCORE_THRESHOLD: continue

            if item_type == 'job':
                job_doc, engineer_doc = item_data['document'], candidate_info['record']['document']
                job_id, engineer_id = item_data['id'], candidate_info['id']
            else:
                job_doc, engineer_doc = candidate_info['record']['document'], item_data['document']
                job_id, engineer_id = candidate_info['id'], item_data['id']

            llm_result = get_match_summary_with_llm(job_doc, engineer_doc)

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



def process_single_content(source_data: dict, progress_bar, base_progress: float, progress_per_email: float):
    """
    単一のメールコンテンツを処理し、進捗バーを更新する。
    メールからの情報抽出とDBへの登録のみを行い、マッチング処理は行わない。
    
    Args:
        source_data (dict): メールから抽出されたデータ。
        progress_bar: Streamlitのプログレスバーオブジェクト。
        base_progress (float): このメール処理開始前の進捗値。
        progress_per_email (float): このメール1件あたりの進捗の重み。
    """
    if not source_data: 
        st.warning("処理するデータが空です。")
        return False

    # ステップ1: コンテンツ解析 (LLM) - このメール処理の大部分を占めると仮定
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
    # このメールに割り当てられた進捗のうち、60%が完了したとみなす
    current_progress = base_progress + (progress_per_email * 0.6)
    progress_bar.progress(current_progress, text="コンテンツ解析完了")

    if not parsed_data: 
        return False
    
    new_jobs_data, new_engineers_data = parsed_data.get("jobs", []), parsed_data.get("engineers", [])
    if not new_jobs_data and not new_engineers_data: 
        st.warning("LLMはテキストから案件情報または技術者情報を抽出できませんでした。")
        return False
    
    # ステップ2: 抽出された情報のDBへの保存
    st.write("抽出された情報をデータベースに保存します...")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            received_at_dt = source_data.get('received_at')
            json_data_to_store = source_data.copy()
            if isinstance(json_data_to_store.get('received_at'), datetime):
                json_data_to_store['received_at'] = json_data_to_store['received_at'].isoformat()
            source_json_str = json.dumps(json_data_to_store, ensure_ascii=False, indent=2)

            newly_added_items_count = 0
            
            for item_data in new_jobs_data:
                doc = item_data.get("document") or full_text_for_llm
                project_name = item_data.get("project_name", "名称未定の案件")
                meta_info = _build_meta_info_string('job', item_data)
                full_document = meta_info + doc
                cursor.execute('INSERT INTO jobs (project_name, document, source_data_json, created_at, received_at) VALUES (%s, %s, %s, %s, %s) RETURNING id', (project_name, full_document, source_json_str, now_str, received_at_dt))
                item_id = cursor.fetchone()[0]
                st.write(f"✅ 新しい案件を登録しました: 『{project_name}』 (ID: {item_id})")
                newly_added_items_count += 1
            
            for item_data in new_engineers_data:
                doc = item_data.get("document") or full_text_for_llm
                engineer_name = item_data.get("name", "名称不明の技術者")
                meta_info = _build_meta_info_string('engineer', item_data)
                full_document = meta_info + doc
                cursor.execute('INSERT INTO engineers (name, document, source_data_json, created_at, received_at) VALUES (%s, %s, %s, %s, %s) RETURNING id', (engineer_name, full_document, source_json_str, now_str, received_at_dt))
                item_id = cursor.fetchone()[0]
                st.write(f"✅ 新しい技術者を登録しました: 『{engineer_name}』 (ID: {item_id})")
                newly_added_items_count += 1
            
            # 【削除】インデックス更新の処理 (マッチング処理がないため不要)
            # cursor.execute('SELECT id, document FROM jobs WHERE is_hidden = 0'); all_active_jobs = cursor.fetchall()
            # cursor.execute('SELECT id, document FROM engineers WHERE is_hidden = 0'); all_active_engineers = cursor.fetchall()
            # if all_active_jobs: update_index(JOB_INDEX_FILE, all_active_jobs)
            # if all_active_engineers: update_index(ENGINEER_INDEX_FILE, all_active_engineers)
            
            # 【削除】再マッチングの処理 (マッチング処理がないため不要)
            # for new_job in newly_added_jobs:
            #     run_matching_for_item(new_job, 'job', conn, now_str)
            # for new_engineer in newly_added_engineers:
            #     run_matching_for_item(new_engineer, 'engineer', conn, now_str)
        conn.commit()

    # 進捗バーを更新 (このメールの処理が100%完了)
    # マッチング処理がなくなったので、進捗の重み付けを調整
    current_progress = base_progress + progress_per_email
    progress_bar.progress(current_progress, text="情報保存完了！")
    
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

def extract_text_from_excel(file_bytes: bytes) -> str:
    """
    Excelファイル（.xlsx, .xls）のバイトデータを受け取り、
    すべてのシートの内容をテキスト形式で結合して返す。
    """
    try:
        # バイトデータを pandas が読み込める形式に変換
        excel_file = io.BytesIO(file_bytes)
        
        # Excelファイル内の全シート名を取得
        xls = pd.ExcelFile(excel_file)
        sheet_names = xls.sheet_names
        
        all_text_parts = []
        
        # 各シートをループで処理
        for sheet_name in sheet_names:
            # シートをDataFrameとして読み込む
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            
            # DataFrameが空でないことを確認
            if not df.empty:
                # シートの内容を文字列に変換（CSV形式に似せる）
                # 各セルをタブ区切り、各行を改行で結合する
                sheet_text = df.to_string(header=False, index=False, na_rep='')
                
                # シート名と内容を結合してリストに追加
                all_text_parts.append(f"\n--- シート: {sheet_name} ---\n{sheet_text}")

        if not all_text_parts:
            return "[Excelテキスト抽出失敗: ファイル内に解析可能なデータがありません]"
            
        # 全シートのテキストを結合して返す
        return "".join(all_text_parts)

    except Exception as e:
        # pandas が読み込めない形式や破損ファイルなどのエラーをキャッチ
        return f"[Excelテキスト抽出エラー: {e}]"
    

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

                #if lower_filename.endswith(".pdf"): attachments.append({"filename": filename, "content": extract_text_from_pdf(file_bytes)})
                #elif lower_filename.endswith(".docx"): attachments.append({"filename": filename, "content": extract_text_from_docx(file_bytes)})
                #elif lower_filename.endswith(".txt"): attachments.append({"filename": filename, "content": file_bytes.decode('utf-8', errors='ignore')})
                #else: st.write(f"ℹ️ 添付ファイル '{filename}' は未対応の形式のため、スキップします。")

                # ▼▼▼【ここからが修正・追加箇所】▼▼▼
                if lower_filename.endswith(".pdf"):
                    attachments.append({"filename": filename, "content": extract_text_from_pdf(file_bytes)})
                
                elif lower_filename.endswith(".docx"):
                    attachments.append({"filename": filename, "content": extract_text_from_docx(file_bytes)})

                elif lower_filename.endswith((".xlsx", ".xls")): # .xlsx と .xls の両方に対応
                    attachments.append({"filename": filename, "content": extract_text_from_excel(file_bytes)})

                elif lower_filename.endswith(".txt"):
                    attachments.append({"filename": filename, "content": file_bytes.decode('utf-8', errors='ignore')})
                
                else:
                    st.write(f"ℹ️ 添付ファイル '{filename}' は未対応の形式のため、スキップします。")
                
                # ▲▲▲【修正・追加ここまで】▲▲▲


    else:
        charset = msg.get_content_charset()
        try: body_text = msg.get_payload(decode=True).decode(charset or 'utf-8', errors='ignore')
        except Exception: body_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    
    return {"subject": subject, "from": from_, "received_at": received_at, "body": body_text.strip(), "attachments": attachments}




# backend.py

def fetch_and_process_emails():
    try:
        # 1. 設定ファイルから読み込み件数を取得
        config = load_app_config()
        # .get() を使って安全に値を取得し、取得できない場合はデフォルトで10を設定
        FETCH_LIMIT = config.get("email_processing", {}).get("fetch_limit", 10)

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
                    latest_ids = email_ids[::-1][:FETCH_LIMIT]
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
    """
    【エラーハンドリング強化・完成版】
    提案メールを生成する。DB接続の確立もこの関数内で行う。
    """
    if not all([job_summary, engineer_summary, engineer_name, project_name]):
        return "情報が不足しているため、提案メールを生成できませんでした。"

    # ▼▼▼【ここからが修正の核】▼▼▼
    
    # --- 1. AIアクティビティログを先に記録する ---
    # この処理は独立して実行し、万が一失敗してもメール生成は続行する
    try:
        # この関数内でDB接続を確立する
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # タイムゾーン対応のため、created_atも明示的に指定する
                cur.execute("INSERT INTO ai_activity_log (activity_type, created_at) VALUES ('proposal_generation', NOW())")
            conn.commit()
    except Exception as db_err:
        # ログ記録の失敗はコンソールに出力するのみで、ユーザーには影響を与えない
        print(f"Warning: Failed to record 'proposal_generation' activity log: {db_err}")

    # --- 2. AIに問い合わせてメール本文を生成する ---
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
        # モデル名はご自身の環境に合わせて調整してください
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite') 
        response = model.generate_content(prompt)
        
        # 応答が空でないことを確認
        if not response.text or not response.text.strip():
            return "AIが応答を生成できませんでした。お手数ですが、再度お試しください。"
            
        return response.text
        
    except Exception as e:
        print(f"Error generating proposal reply with LLM: {e}")
        # ユーザーに表示する、より具体的なエラーメッセージ
        return f"提案メールの生成中にAIとの通信エラーが発生しました: {e}"
    





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

    # SQL文を修正し、status_updated_at カラムに NOW() を設定する
    sql = """
        UPDATE matching_results 
        SET 
            status = %s, 
            status_updated_at = NOW() 
        WHERE id = %s;
    """
    # ★★★【修正ここまで】★★★

    
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor: 
                cursor.execute(sql, (new_status, match_id))
            #cursor.execute("UPDATE matching_results SET status = %s WHERE id = %s", (new_status, match_id))
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




def re_evaluate_and_match_single_engineer(engineer_id, target_rank='B', target_count=5):
    """
    【新しい仕様】
    指定された技術者の情報を最新化し、既存のマッチングをクリア後、
    案件を最新順に処理し、目標ランク以上のマッチングが目標件数に達したら処理を終了する。
    """
    if not engineer_id:
        st.error("技術者IDが指定されていません。")
        return False

    # ランクの順序を定義 (Sが最も高い)
    rank_order = ['S', 'A', 'B', 'C', 'D']
    try:
        # 目標ランク以上のランクのリストを作成
        valid_ranks = rank_order[:rank_order.index(target_rank) + 1]
    except ValueError:
        st.error(f"無効な目標ランクが指定されました: {target_rank}")
        return False

    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                # 1. 技術者の最新ドキュメントを生成

                st.write("📄 元情報から技術者の最新ドキュメントを生成します...")
                cursor.execute("SELECT source_data_json, name FROM engineers WHERE id = %s", (engineer_id,))
                engineer_record = cursor.fetchone()
                if not engineer_record or not engineer_record['source_data_json']:
                    st.error(f"技術者ID:{engineer_id} の元情報が見つかりませんでした。")
                    return False
                
                source_data = json.loads(engineer_record['source_data_json'])
                full_text_for_llm = source_data.get('body', '') + "".join([f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content') and not att.get('content', '').startswith("[") and not att.get('content', '').endswith("]")])
                
                parsed_data = split_text_with_llm(full_text_for_llm)
                if not parsed_data or not parsed_data.get("engineers"):
                    st.error("LLMによる情報抽出（再評価）に失敗しました。")
                    return False
                
                item_data = parsed_data["engineers"][0]
                doc = item_data.get("document") or full_text_for_llm
                meta_info = _build_meta_info_string('engineer', item_data)
                new_full_document = meta_info + doc
                engineer_doc = new_full_document

                # ▼▼▼【技術者希望単価を抽出】▼▼▼
                engineer_price_str = item_data.get("desired_salary")
                engineer_price = _extract_price_from_string(engineer_price_str)
                if engineer_price:
                    st.write(f"  - 技術者の希望単価を **{engineer_price}万円** として認識しました。")
                else:
                    st.warning("  - 技術者の希望単価が抽出できなかったため、単価フィルタリングはスキップされます。")
                # ▲▲▲【技術者希望単価の抽出ここまで】▲▲▲

                
                # 2. engineersテーブルのdocumentを更新
                cursor.execute("UPDATE engineers SET document = %s WHERE id = %s", (engineer_doc, engineer_id))
                st.write("✅ 技術者のAI要約情報を更新しました。")

                # 3. 既存のマッチング結果を削除
                cursor.execute("DELETE FROM matching_results WHERE engineer_id = %s", (engineer_id,))
                st.write(f"🗑️ 技術者ID:{engineer_id} の既存マッチング結果をクリアしました。")

                # 4. マッチング対象の全案件を最新順に取得
                st.write("🔄 最新の案件から順にマッチング処理を開始します...")
                #cursor.execute("SELECT id, document, project_name FROM jobs WHERE is_hidden = 0 ORDER BY created_at DESC")
                cursor.execute("SELECT id, document, project_name, source_data_json FROM jobs WHERE is_hidden = 0 ORDER BY created_at DESC")

                all_active_jobs = cursor.fetchall()
                if not all_active_jobs:
                    st.warning("マッチング対象の案件がありません。")
                    conn.commit()
                    return True

                st.write(f"  - 対象案件数: {len(all_active_jobs)}件")
                st.write(f"  - 終了条件: 「**{target_rank}**」ランク以上のマッチングが **{target_count}** 件見つかった時点")

                # 5. ループでマッチング処理を実行
                found_count = 0
                processed_count = 0
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                for job in all_active_jobs:
                    processed_count += 1

                    # ▼▼▼【単価フィルタリングロジック】▼▼▼
                    try:
                        job_source_data = json.loads(job['source_data_json'])
                        job_price_str = job_source_data.get("unit_price")
                        job_price = _extract_price_from_string(job_price_str)
                    except (json.JSONDecodeError, TypeError):
                        job_price = None

                    if job_price is not None and engineer_price is not None:
                        if engineer_price > job_price + 5:
                            st.write(f"  ({processed_count}/{len(all_active_jobs)}) 案件『{job['project_name']}』 -> 単価不一致のためスキップ (案件:{job_price}万, 技術者:{engineer_price}万)")
                            continue
                    # ▲▲▲【単価フィルタリングここまで】▲▲▲

                    st.write(f"  ({processed_count}/{len(all_active_jobs)}) 案件『{job['project_name']}』とマッチング中...")
                    
                    # LLMによるマッチング評価を実行
                    llm_result = get_match_summary_with_llm(job['document'], engineer_doc)

                    if llm_result and 'summary' in llm_result:
                        grade = llm_result.get('summary')
                        positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
                        concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)
                        
                        # 類似度スコアはベクトル検索を行わないため、ダミー値（例: 0）を入れるか、NULL許容にする必要があります。
                        # ここでは score を 0 とします。
                        score = 0.0

                        # DBに保存（ランクに関わらず一旦すべて保存する方が後々の分析に役立つ場合もあるが、今回はヒットしたものだけ保存）
                        if grade in valid_ranks:
                            try:
                                cursor.execute(
                                    'INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade, positive_points, concern_points) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                                    (job['id'], engineer_id, score, now_str, grade, positive_points, concern_points)
                                )
                                st.success(f"    -> マッチング評価: **{grade}** ... ✅ ヒット！DBに保存しました。")
                                found_count += 1
                            except Exception as e:
                                st.error(f"    -> DB保存中にエラー: {e}")
                        else:
                            st.write(f"    -> マッチング評価: **{grade}** ... スキップ")
                    else:
                        st.warning(f"    -> LLM評価失敗のためスキップ")

                    # 終了条件をチェック
                    if found_count >= target_count:
                        st.success(f"🎉 目標の {target_count} 件に到達したため、処理を終了します。")
                        break
                
                if found_count < target_count:
                    st.info(f"すべての案件とのマッチングが完了しました。(ヒット数: {found_count}件)")

            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            conn.rollback()
            st.error(f"再評価・再マッチング中にエラーが発生しました: {e}")
            st.exception(e) # 詳細なトレースバックを表示
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

# backend.py の get_dashboard_data 関数をこちらに置き換えてください

def get_dashboard_data():
    """ダッシュボード表示に必要なデータをDBから取得・集計する"""
    conn = get_db_connection()
    try:
        #@st.cache_data(ttl=300) # 5分間キャッシュ
        def fetch_data_from_db():
            # 【変更点1】 users テーブルも読み込む
            # 【変更点2】 SQLでJOINして担当者名(username)を取得する
            jobs_sql = """
                SELECT j.id, j.created_at, u.username as assignee_name
                FROM jobs j
                LEFT JOIN users u ON j.assigned_user_id = u.id
            """
            engineers_sql = """
                SELECT e.id, e.created_at, u.username as assignee_name
                FROM engineers e
                LEFT JOIN users u ON e.assigned_user_id = u.id
            """
            matches_sql = """
                SELECT m.id, m.created_at, m.grade, u_job.username as job_assignee, u_eng.username as engineer_assignee
                FROM matching_results m
                LEFT JOIN jobs j ON m.job_id = j.id
                LEFT JOIN engineers e ON m.engineer_id = e.id
                LEFT JOIN users u_job ON j.assigned_user_id = u_job.id
                LEFT JOIN users u_eng ON e.assigned_user_id = u_eng.id
            """
            jobs_df = pd.read_sql(jobs_sql, conn)
            engineers_df = pd.read_sql(engineers_sql, conn)
            matches_df = pd.read_sql(matches_sql, conn)
            
            return jobs_df, engineers_df, matches_df

        jobs_df, engineers_df, matches_df = fetch_data_from_db()

        # --- 1. サマリー指標 (変更なし) ---
        total_jobs = len(jobs_df)
        total_engineers = len(engineers_df)
        total_matches = len(matches_df)

        jobs_df['created_at'] = pd.to_datetime(jobs_df['created_at'], errors='coerce')
        engineers_df['created_at'] = pd.to_datetime(engineers_df['created_at'], errors='coerce')
        
        now = pd.Timestamp.now()
        jobs_this_month = len(jobs_df.dropna(subset=['created_at'])[jobs_df['created_at'].dt.month == now.month])
        engineers_this_month = len(engineers_df.dropna(subset=['created_at'])[engineers_df['created_at'].dt.month == now.month])

        summary_metrics = {
            "total_jobs": total_jobs,
            "total_engineers": total_engineers,
            "total_matches": total_matches,
            "jobs_this_month": jobs_this_month,
            "engineers_this_month": engineers_this_month,
        }

        # --- 2. AI評価ランクの割合 (変更なし) ---
        if not matches_df.empty:
            rank_counts = matches_df['grade'].value_counts().reindex(['S', 'A', 'B', 'C', 'D'], fill_value=0)
        else:
            rank_counts = pd.Series([0, 0, 0, 0, 0], index=['S', 'A', 'B', 'C', 'D'])

        # --- 3. 時系列データ (変更なし) ---
        matches_df['created_at'] = pd.to_datetime(matches_df['created_at'], errors='coerce')
        jobs_ts = jobs_df.dropna(subset=['created_at']).set_index('created_at')
        engineers_ts = engineers_df.dropna(subset=['created_at']).set_index('created_at')
        matches_ts = matches_df.dropna(subset=['created_at']).set_index('created_at')
        daily_jobs = jobs_ts.resample('D').size().rename('案件登録数')
        daily_engineers = engineers_ts.resample('D').size().rename('技術者登録数')
        daily_matches = matches_ts.resample('D').size().rename('マッチング生成数')
        time_series_df = pd.concat([daily_jobs, daily_engineers, daily_matches], axis=1).fillna(0).astype(int)
        
        # --- 4. 担当者別分析データ (★ここからが新しいコード) ---
        # 担当者が未割り当て(None)の場合を「未担当」に置き換える
        jobs_df['assignee_name'].fillna('未担当', inplace=True)
        engineers_df['assignee_name'].fillna('未担当', inplace=True)
        
        # 担当者ごとの担当件数を集計
        job_counts_by_assignee = jobs_df['assignee_name'].value_counts().rename('案件担当数')
        engineer_counts_by_assignee = engineers_df['assignee_name'].value_counts().rename('技術者担当数')
        assignee_counts_df = pd.concat([job_counts_by_assignee, engineer_counts_by_assignee], axis=1).fillna(0).astype(int)
        
        # 担当者ごとのマッチングランク分布を集計
        # 案件担当者と技術者担当者のどちらかが設定されていれば、その担当者の成果とみなす（coalesce的な処理）
        matches_df['responsible_person'] = matches_df['job_assignee'].fillna(matches_df['engineer_assignee']).fillna('未担当')
        match_rank_by_assignee = pd.crosstab(
            index=matches_df['responsible_person'],
            columns=matches_df['grade']
        )
        # S,A,B,C,Dカラムが必ず存在するようにreindex
        all_ranks = ['S', 'A', 'B', 'C', 'D']
        match_rank_by_assignee = match_rank_by_assignee.reindex(columns=all_ranks, fill_value=0)

        # 戻り値に担当者別データを追加
        return summary_metrics, rank_counts, time_series_df, assignee_counts_df, match_rank_by_assignee

    finally:
        if conn:
            conn.close()





def save_match_feedback(match_id, feedback_status, feedback_comment, user_id):
    """マッチング結果に対する担当者のフィードバックを保存する"""
    if not all([match_id, feedback_status, user_id]):
        st.error("必須項目が不足しているため、フィードバックを保存できません。")
        return False
    
    feedback_at = datetime.now()
    
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE matching_results 
                    SET feedback_status = %s, 
                        feedback_comment = %s, 
                        feedback_user_id = %s, 
                        feedback_at = %s
                    WHERE id = %s
                    """,
                    (feedback_status, feedback_comment, user_id, feedback_at, match_id)
                )
            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            st.error(f"フィードバックの保存中にエラーが発生しました: {e}")
            conn.rollback()
            return False
        

def get_matching_result_details(result_id):
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                # 【修正点】 usersテーブルをJOINしてフィードバック担当者名を取得
                sql = """
                    SELECT r.*, u.username as feedback_username
                    FROM matching_results r
                    LEFT JOIN users u ON r.feedback_user_id = u.id
                    WHERE r.id = %s
                """
                cursor.execute(sql, (result_id,))
                match_result = cursor.fetchone()
                
                if not match_result: return None
                
                cursor.execute("SELECT j.*, u.username as assignee_name FROM jobs j LEFT JOIN users u ON j.assigned_user_id = u.id WHERE j.id = %s", (match_result['job_id'],))
                job_data = cursor.fetchone()
                
                cursor.execute("SELECT e.*, u.username as assignee_name FROM engineers e LEFT JOIN users u ON e.assigned_user_id = u.id WHERE e.id = %s", (match_result['engineer_id'],))
                engineer_data = cursor.fetchone()
                
                return {"match_result": dict(match_result), "job_data": dict(job_data) if job_data else None, "engineer_data": dict(engineer_data) if engineer_data else None}
        except (Exception, psycopg2.Error) as e:
            print(f"マッチング詳細取得エラー: {e}"); return None
            


def save_internal_memo(match_id, memo_text):
    """マッチング結果に対する社内メモを保存・更新する"""
    if not match_id:
        st.error("マッチングIDが指定されていません。")
        return False
    
    # メモが空文字列の場合も許容するため、memo_textのチェックは緩めにする
    if memo_text is None:
        memo_text = "" # DBには空文字列として保存

    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE matching_results 
                    SET internal_memo = %s
                    WHERE id = %s
                    """,
                    (memo_text, match_id)
                )
            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            st.error(f"社内メモの保存中にエラーが発生しました: {e}")
            conn.rollback()
            return False


def delete_match(match_id):
    """指定されたマッチングIDの結果を matching_results テーブルから削除する"""
    if not match_id:
        print("削除対象のマッチングIDが指定されていません。")
        return False
    
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM matching_results WHERE id = %s", (match_id,))
                deleted_rows = cursor.rowcount
            
            conn.commit()
            
            # 1件以上削除されたら成功とみなす
            return deleted_rows > 0
            
        except (Exception, psycopg2.Error) as e:
            st.error(f"マッチング結果の削除中にデータベースエラーが発生しました: {e}")
            conn.rollback()
            return False




def re_evaluate_and_match_single_job(job_id, target_rank='B', target_count=5):
    """
    【新しい関数】
    指定された案件の情報を最新化し、既存のマッチングをクリア後、
    技術者を最新順に処理し、目標ランク以上のマッチングが目標件数に達したら処理を終了する。
    """
    if not job_id:
        st.error("案件IDが指定されていません。")
        return False

    rank_order = ['S', 'A', 'B', 'C', 'D']
    try:
        valid_ranks = rank_order[:rank_order.index(target_rank) + 1]
    except ValueError:
        st.error(f"無効な目標ランクが指定されました: {target_rank}")
        return False

    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                # 1. 案件の最新ドキュメントを生成
                st.write("📄 元情報から案件の最新ドキュメントを生成します...")
                cursor.execute("SELECT source_data_json, project_name FROM jobs WHERE id = %s", (job_id,))
                job_record = cursor.fetchone()
                if not job_record or not job_record['source_data_json']:
                    st.error(f"案件ID:{job_id} の元情報が見つかりませんでした。")
                    return False
                
                source_data = json.loads(job_record['source_data_json'])
                full_text_for_llm = source_data.get('body', '') + "".join([f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content') and not att.get('content', '').startswith("[") and not att.get('content', '').endswith("]")])
                
                parsed_data = split_text_with_llm(full_text_for_llm)
                if not parsed_data or not parsed_data.get("jobs"):
                    st.error("LLMによる情報抽出（再評価）に失敗しました。")
                    return False
                
                item_data = parsed_data["jobs"][0]
                doc = item_data.get("document") or full_text_for_llm
                meta_info = _build_meta_info_string('job', item_data)
                new_full_document = meta_info + doc
                job_doc = new_full_document

                # ▼▼▼【案件単価を抽出】▼▼▼
                job_price_str = item_data.get("unit_price")
                job_price = _extract_price_from_string(job_price_str)
                if job_price:
                    st.write(f"  - 案件単価を **{job_price}万円** として認識しました。")
                else:
                    st.warning("  - 案件の単価が抽出できなかったため、単価フィルタリングはスキップされます。")
                # ▲▲▲【案件単価の抽出ここまで】▲▲▲
                
                # 2. jobsテーブルのdocumentを更新
                cursor.execute("UPDATE jobs SET document = %s WHERE id = %s", (job_doc, job_id))
                st.write("✅ 案件のAI要約情報を更新しました。")

                # 3. 既存のマッチング結果を削除
                cursor.execute("DELETE FROM matching_results WHERE job_id = %s", (job_id,))
                st.write(f"🗑️ 案件ID:{job_id} の既存マッチング結果をクリアしました。")

                # 4. マッチング対象の全技術者を最新順に取得
                st.write("🔄 最新の技術者から順にマッチング処理を開始します...")
                cursor.execute("SELECT id, document, name, source_data_json FROM engineers WHERE is_hidden = 0 ORDER BY created_at DESC")
                all_active_engineers = cursor.fetchall()
                if not all_active_engineers:
                    st.warning("マッチング対象の技術者がいません。")
                    conn.commit()
                    return True

                st.write(f"  - 対象技術者数: {len(all_active_engineers)}名")
                st.write(f"  - 終了条件: 「**{target_rank}**」ランク以上のマッチングが **{target_count}** 件見つかった時点")

                # 5. ループでマッチング処理を実行
                found_count = 0
                processed_count = 0
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                for engineer in all_active_engineers:
                    processed_count += 1

                    # ▼▼▼【単価フィルタリングロジック】▼▼▼
                    try:
                        engineer_source_data = json.loads(engineer['source_data_json'])
                        engineer_price_str = engineer_source_data.get("desired_salary")
                        engineer_price = _extract_price_from_string(engineer_price_str)
                    except (json.JSONDecodeError, TypeError):
                        engineer_price = None

                    # 案件単価と技術者希望単価の両方が取得できた場合のみ比較
                    if job_price is not None and engineer_price is not None:
                        # 技術者の希望単価が案件単価を5万円以上上回る場合はスキップ
                        if engineer_price > job_price + 5:
                            st.write(f"  ({processed_count}/{len(all_active_engineers)}) 技術者『{engineer['name']}』 -> 単価不一致のためスキップ (案件:{job_price}万, 技術者:{engineer_price}万)")
                            continue # 次の技術者へ
                    # ▲▲▲【単価フィルタリングここまで】▲▲▲

                    st.write(f"  ({processed_count}/{len(all_active_engineers)}) 技術者『{engineer['name']}』とマッチング中...")
                    
                    llm_result = get_match_summary_with_llm(job_doc, engineer['document'])

                    if llm_result and 'summary' in llm_result:
                        grade = llm_result.get('summary')
                        positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
                        concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)
                        score = 0.0

                        if grade in valid_ranks:
                            try:
                                cursor.execute(
                                    'INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade, positive_points, concern_points) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                                    (job_id, engineer['id'], score, now_str, grade, positive_points, concern_points)
                                )
                                st.success(f"    -> マッチング評価: **{grade}** ... ✅ ヒット！DBに保存しました。")
                                found_count += 1
                            except Exception as e:
                                st.error(f"    -> DB保存中にエラー: {e}")
                        else:
                            st.write(f"    -> マッチング評価: **{grade}** ... スキップ")
                    else:
                        st.warning(f"    -> LLM評価失敗のためスキップ")

                    if found_count >= target_count:
                        st.success(f"🎉 目標の {target_count} 件に到達したため、処理を終了します。")
                        break
                
                if found_count < target_count:
                    st.info(f"すべての技術者とのマッチングが完了しました。(ヒット数: {found_count}件)")

            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            conn.rollback()
            st.error(f"再評価・再マッチング中にエラーが発生しました: {e}")
            st.exception(e)
            return False
        
        

def _extract_price_from_string(price_str: str) -> float | None:
    """
    "80万円", "75万～85万", "〜90" のような文字列から数値（万円単位）を抽出する。
    範囲の場合は下限値を返す。抽出できない場合は None を返す。
    """
    if not price_str or not isinstance(price_str, str):
        return None
    
    # 全角数字を半角に、全角マイナスを半角に変換
    price_str = price_str.translate(str.maketrans("０１２３４５６７８９－", "0123456789-"))
    
    # "万"や"円"などの文字を削除
    price_str = price_str.replace("万", "").replace("円", "").replace(",", "")
    
    # 数字（小数点含む）をすべて抽出
    numbers = re.findall(r'(\d+\.?\d*)', price_str)
    
    if numbers:
        # 抽出された数字の中から最小のものを返す（例: "75~85" -> 75）
        try:
            return min([float(n) for n in numbers])
        except (ValueError, TypeError):
            return None
    return None


# backend.py の get_filtered_item_ids 関数をこちらに置き換えてください

def get_filtered_item_ids(
    item_type: str, 
    keyword: str = "", 
    assigned_user_ids: list = None,
    has_matches_only: bool = False,
    auto_match_only: bool = False,
    sort_column: str = "登録日", 
    sort_order: str = "降順", 
    show_hidden: bool = False
) -> list:
    """
    【auto_match_only フィルター修正版】
    item_typeの単数形・複数形の不整合を解消。
    """
    if item_type not in ['jobs', 'engineers']: 
        return []

    table_name = 'jobs' if item_type == 'jobs' else 'engineers'
    name_column = "project_name" if table_name == "jobs" else "name"
    
    query = f"SELECT DISTINCT e.id FROM {table_name} e"
    joins = ""
    where_clauses = []
    params = []

    if not show_hidden:
        where_clauses.append("e.is_hidden = 0")

    if keyword:
        joins += " LEFT JOIN users u ON e.assigned_user_id = u.id"
        keywords_list = [k.strip() for k in keyword.split() if k.strip()]
        keyword_clauses = []
        for kw in keywords_list:
            keyword_clauses.append(f"(e.document ILIKE %s OR e.{name_column} ILIKE %s OR u.username ILIKE %s)")
            param = f'%{kw}%'
            params.extend([param, param, param])
        where_clauses.append(f"({' AND '.join(keyword_clauses)})")

    if assigned_user_ids:
        real_user_ids = [uid for uid in assigned_user_ids if uid != -1]
        include_unassigned = -1 in assigned_user_ids
        
        user_filter_parts = []
        if real_user_ids:
            user_filter_parts.append("e.assigned_user_id IN %s")
            params.append(tuple(real_user_ids))
        if include_unassigned:
            user_filter_parts.append("e.assigned_user_id IS NULL")
        
        if user_filter_parts:
            where_clauses.append(f"({' OR '.join(user_filter_parts)})")

    if has_matches_only:
        join_key = 'job_id' if item_type == 'jobs' else 'engineer_id'
        where_clauses.append(f"EXISTS (SELECT 1 FROM matching_results mr WHERE mr.{join_key} = e.id AND mr.is_hidden = 0)")

    # ★★★【ここからが修正の核】★★★
    if auto_match_only:
        # item_type ('jobs' or 'engineers') から末尾の 's' を取り除き、単数形 ('job' or 'engineer') にする
        singular_item_type = item_type.rstrip('s')
        
        where_clauses.append(f"""
            EXISTS (
                SELECT 1 FROM auto_matching_requests amr 
                WHERE amr.item_id = e.id 
                  AND amr.item_type = %s 
                  AND amr.is_active = TRUE
            )
        """)
        params.append(singular_item_type) # 単数形をパラメータとして渡す
    # ★★★【修正ここまで】★★★

    # --- クエリの最終組み立て ---
    final_query = query + joins
    if where_clauses:
        final_query = final_query.replace("SELECT DISTINCT e.id", "SELECT e.id") # DISTINCTは最後に追加
        final_query += " WHERE " + " AND ".join(where_clauses)
    
    # --- ソート順の決定 ---
    sort_joins = ""
    if sort_column == "担当者名" and "LEFT JOIN users u" not in final_query:
        sort_joins = " LEFT JOIN users u ON e.assigned_user_id = u.id"
    
    # JOINが発生する場合、結果が重複する可能性があるのでDISTINCTを付ける
    if joins or sort_joins:
        final_query = final_query.replace("SELECT e.id", "SELECT DISTINCT e.id")

    final_query += sort_joins

    sort_column_map = {"登録日": "e.id", "プロジェクト名": f"e.{name_column}", "氏名": f"e.{name_column}", "担当者名": "u.username"}
    order_by_column = sort_column_map.get(sort_column, "e.id")
    
    order_map = {"降順": "DESC", "昇順": "ASC"}
    order_by_direction = order_map.get(sort_order, "DESC")
    nulls_order = "NULLS LAST" if order_by_direction == "DESC" else "NULLS FIRST"
    
    final_query += f" ORDER BY {order_by_column} {order_by_direction} {nulls_order}"

    # --- DB実行 ---
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(final_query, tuple(params))
            return [item[0] for item in cursor.fetchall()]
    except Exception as e:
        print(f"IDリストの取得中にエラー: {e}")
        try:
            print("--- FAILED QUERY (get_filtered_item_ids) ---")
            print(cursor.mogrify(final_query, tuple(params)).decode('utf-8'))
            print("--------------------")
        except:
            pass
        return []
    finally:
        if conn:
            conn.close()




def get_items_by_ids(item_type: str, ids: list) -> list:
    """
    【修正版】
    IDリストに基づきレコードを取得。担当者名もJOINし、
    結果を「変更可能な」通常の辞書(dict)のリストとして返す。
    """
    if not ids or item_type not in ['jobs', 'engineers']:
        return []

    table_name = 'jobs' if item_type == 'jobs' else 'engineers'
    
    query = f"""
        SELECT 
            t.*, 
            u.username as assigned_username,
            fb_counts.feedback_count
        FROM {table_name} t
        LEFT JOIN users u ON t.assigned_user_id = u.id
        LEFT JOIN (
            SELECT 
                {'job_id' if item_type == 'jobs' else 'engineer_id'} as join_key, 
                COUNT(*) as feedback_count
            FROM matching_results
            WHERE feedback_status IS NOT NULL AND feedback_comment IS NOT NULL AND feedback_comment != ''
            GROUP BY join_key
        ) AS fb_counts ON t.id = fb_counts.join_key
        WHERE t.id = ANY(%s)
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, (ids,))
            
            # ▼▼▼【ここからが修正の核となる部分】▼▼▼
            
            # fetchall() の結果は DictRow のリスト
            results_from_db = cursor.fetchall()

            # DictRow を通常の dict に変換する
            dict_results = [dict(row) for row in results_from_db]
            
            # IDをキーにした辞書を作成して、元のIDリストの順序に並べ替える
            results_map = {res['id']: res for res in dict_results}
            return [results_map[id] for id in ids if id in results_map]

            # ▲▲▲【修正ここまで】▲▲▲

    except Exception as e:
        print(f"IDによるアイテム取得中にエラー: {e}")
        return []
    finally:
        if conn:
            conn.close()







def generate_ai_analysis_on_feedback(job_doc: str, engineer_doc: str, feedback_evaluation: str, feedback_comment: str) -> str:
    """
    案件・技術者情報と、それに対する人間のフィードバックを受け取り、
    AIがそのフィードバックから何を学習したかを分析・要約して返す。
    """
    if not all([job_doc, engineer_doc, feedback_evaluation, feedback_comment]):
        return "分析対象のフィードバック情報が不足しています。"

    # AIへの指示プロンプト
    prompt = f"""
        あなたは、IT人材のマッチング精度を日々改善している、学習するAIアシスタントです。
        あなたの仕事は、案件情報と技術者情報、そしてそれに対する人間の担当者からのフィードバックを分析し、そのフィードバックから何を学び、次にどう活かすかを簡潔に言語化することです。

        # 指示
        - 担当者からの評価とコメントの本質を捉えてください。
        - ポジティブな評価であれば、なぜそれが良かったのか、そのパターンをどう強化するかを記述してください。
        - ネガティブな評価であれば、なぜそれが悪かったのか、その間違いを今後どう避けるかを記述してください。
        - 「単価」「スキル」「経験年数」「勤務地」などの具体的な要素に言及してください。
        - あなた自身の言葉で、学習内容を宣言するように記述してください。

        # 分析対象データ
        ---
        ## 案件情報
        {job_doc}
        ---
        ## 技術者情報
        {engineer_doc}
        ---
        ## 担当者からのフィードバック
        - **評価:** {feedback_evaluation}
        - **コメント:** {feedback_comment}
        ---

        # 出力例
        - このフィードバックから、コアスキルが完全に一致する場合、単価に10万円程度の差があっても「良いマッチング」と評価されることを学習しました。今後は、スキルの一致度をより重視し、単価の条件を少し緩和して候補を提案します。
        - このフィードバックから、xxというスキルはyyという業務内容と関連性が低いと判断されていることを学びました。今後は、この組み合わせでのマッチングスコアを下方修正します。

        # あなたの分析結果を生成してください
    """

    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"フィードバックのAI分析中にエラー: {e}")
        return f"AIによる分析中にエラーが発生しました: {e}"

# ▲▲▲【新しい関数ここまで】▲▲▲


# backend.py

def find_candidates_on_demand(input_text: str, target_rank: str, target_count: int):
    """
    【最終完成版】
    キーワードでDBから候補IDを全件取得後、100件ずつのバッチで
    「動的インデックス生成」「ベクトル検索」「AI評価」を繰り返し、
    目標件数に達したら処理を打ち切る、効率的かつ高品質な実装。
    """
    # --- ステップ1: テキスト分類、キーワード抽出、候補IDの全件取得 ---
    yield "ステップ1/3: 入力情報から評価対象となる全候補をリストアップしています...\n"
    
    # 1a. テキスト分類と要約
    parsed_data, _ = split_text_with_llm(input_text)
    if not parsed_data:
        yield "❌ エラー: 入力情報から構造化データを抽出できませんでした。\n"; return
    
    source_doc_type, search_target_type, source_item = (None, None, None)
    if parsed_data.get("jobs") and parsed_data["jobs"]:
        source_doc_type, search_target_type, source_item = 'job', 'engineer', parsed_data['jobs'][0]
    elif parsed_data.get("engineers") and parsed_data["engineers"]:
        source_doc_type, search_target_type, source_item = 'engineer', 'job', parsed_data['engineers'][0]
    
    if not source_doc_type or not source_item:
        yield "❌ エラー: AIはテキストを構造化しましたが、中身が案件か技術者か判断できませんでした。\n"; return
    
    yield f"  > 入力は「{source_doc_type}」情報と判断。検索ターゲットは「{search_target_type}」です。\n"
    source_doc = _build_meta_info_string(source_doc_type, source_item) + source_item.get("document", "")

    # 1b. キーワード抽出
    yield "  > 検索の核となるキーワードをAIが抽出しています...\n"
    search_keywords = []
    try:
        keyword_extraction_prompt = f"""
            以下のテキストから、データベース検索に有効な技術要素、役職、スキル名を最大5つ、カンマ区切りの単語リストとして抜き出してください。
            バージョン情報や経験年数などの付随情報は含めず、単語のみを抽出してください。
            例:
            入力:「Laravel（v10）での開発経験があり、Vue.js（v3）も使えます。PM補佐の経験もあります。」
            出力: Laravel, Vue.js, PM
            入力テキスト: --- {input_text} ---
            出力:
        """
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        response = model.generate_content(keyword_extraction_prompt)
        keywords_from_ai = [kw.strip() for kw in response.text.strip().split(',') if kw.strip()]
        if not keywords_from_ai: raise ValueError("AIはキーワードを返しませんでした。")
        search_keywords = keywords_from_ai
    except Exception as e:
        yield f"  > ⚠️ キーワードのAI抽出に失敗({e})。代替キーワードで検索します。\n"
        fallback_keyword = source_item.get("project_name") or source_item.get("name")
        if fallback_keyword: search_keywords = [fallback_keyword.strip()]

    if not search_keywords:
        yield "  > ❌ 検索キーワードを特定できませんでした。処理を中断します。\n"; return
    yield f"  > 抽出されたキーワード: `{'`, `'.join(search_keywords)}`\n"

    # 1c. キーワードに一致する「IDのみ」をDBから全件取得
    target_table = search_target_type + 's'
    name_column = "project_name" if search_target_type == 'job' else "name"
    query = f"SELECT id FROM {target_table} WHERE is_hidden = 0 AND ("
    or_conditions = [f"(document ILIKE %s OR {name_column} ILIKE %s)" for _ in search_keywords]
    params = [f"%{kw}%" for kw in search_keywords for _ in (0, 1)]
    query += " OR ".join(or_conditions)
    query += ") ORDER BY id DESC"

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            all_candidate_ids = [item['id'] for item in cursor.fetchall()]
    finally:
        if conn: conn.close()

    if not all_candidate_ids:
        yield "✅ データベースを検索しましたが、キーワードに一致する候補は見つかりませんでした。\n"; return
    yield f"  > キーワード検索の結果、{len(all_candidate_ids)}件の評価対象候補をリストアップしました。\n"

    # --- ループの初期化 ---
    final_candidates = []
    DB_FETCH_BATCH_SIZE = 25
    rank_order = ['S', 'A', 'B', 'C', 'D']
    valid_ranks = rank_order[:rank_order.index(target_rank) + 1]
    embedding_model = load_embedding_model()
    if not embedding_model:
        yield "❌ エラー: 埋め込みモデルの読み込みに失敗しました。\n"; return
    query_vector = embedding_model.encode([source_doc], normalize_embeddings=True)

    # --- ステップ2: 目標件数に達するまで検索・評価ループを実行 ---
    yield f"\nステップ2/3: 候補者を{DB_FETCH_BATCH_SIZE}件ずつのグループに分けて、AI評価を開始します...\n"
    yield f"  > 目標: 「{target_rank}」ランク以上を {target_count}件 見つけるまで処理を続けます。\n"
    
    for page in range(0, len(all_candidate_ids), DB_FETCH_BATCH_SIZE):
        batch_ids = all_candidate_ids[page : page + DB_FETCH_BATCH_SIZE]
        if not batch_ids: break

        yield f"\n--- 検索サイクル {page//DB_FETCH_BATCH_SIZE + 1} (DBの {page+1}件目〜) ---\n"
        
        # 2a. このバッチで必要なデータをDBから取得
        candidate_records_for_indexing = get_items_by_ids(search_target_type + 's', batch_ids)
        if not candidate_records_for_indexing: continue
        
        # 2b. 動的インデックス生成とベクトル検索 (このバッチ内での処理)
        yield f"  > {len(candidate_records_for_indexing)}件の候補から、意味的に近いものを探しています...\n"
        dimension = embedding_model.get_sentence_embedding_dimension()
        index = faiss.IndexIDMap(faiss.IndexFlatIP(dimension))
        ids = np.array([item['id'] for item in candidate_records_for_indexing], dtype=np.int64)
        documents = [str(item['document']) for item in candidate_records_for_indexing]
        embeddings = embedding_model.encode(documents, normalize_embeddings=True, show_progress_bar=False)
        index.add_with_ids(embeddings, ids)
        
        _, result_ids = index.search(query_vector, len(documents))
        batch_sorted_ids = [int(i) for i in result_ids[0] if i != -1]
        if not batch_sorted_ids:
            yield "  > このバッチには類似する候補がありませんでした。次のサイクルに進みます。\n"; continue

        # 2c. AIによる再評価
        candidate_records_for_eval = get_items_by_ids(search_target_type + 's', batch_sorted_ids)
        for record in candidate_records_for_eval:
            candidate = dict(record)
            name = candidate.get('name') or candidate.get('project_name')
            
            skills_text = ""
            if search_target_type == 'engineer':
                match = re.search(r'\[主要スキル:\s*([^\]]+)\]', candidate.get('document', ''))
                if match: skills_text = match.group(1)
            elif search_target_type == 'job':
                match = re.search(r'\[必須スキル:\s*([^\]]+)\]', candidate.get('document', ''))
                if match: skills_text = match.group(1)
            
            yield {"type": "eval_progress", "message": f"「{name}」を評価中...", "skills": skills_text[:100] + "..." if len(skills_text) > 100 else skills_text}
            
            llm_result = get_match_summary_with_llm(source_doc, candidate['document'])

            if llm_result and llm_result.get('summary') in valid_ranks:
                candidate['grade'] = llm_result.get('summary')
                candidate['positive_points'] = llm_result.get('positive_points', [])
                candidate['concern_points'] = llm_result.get('concern_points', [])
                final_candidates.append(candidate)
                yield f"    -> ✅ ヒット！ (ランク: **{candidate['grade']}**) - 現在 {len(final_candidates)}/{target_count} 件\n"
            else:
                actual_grade = llm_result.get('summary') if llm_result else "評価失敗"
                yield f"    -> ｽｷｯﾌﾟ (ランク: **{actual_grade}**)\n"

            if len(final_candidates) >= target_count:
                yield f"\n🎉 目標の {target_count} 件に到達したため、全ての処理を終了します。\n"
                break
        
        if len(final_candidates) >= target_count:
            break
    
    if not final_candidates:
        yield "\nℹ️ 全ての候補者を評価しましたが、目標ランクに達する結果はありませんでした。\n"
    elif len(final_candidates) < target_count:
        yield "\nℹ️ 全ての候補者の評価が完了しました。\n"

    # --- ステップ3: 最終結果の表示 ---
    yield f"\nステップ3/3: 最終的な候補者リストを表示します。\n---\n### **最終候補者リスト**\n"
    if not final_candidates:
        yield f"評価の結果、指定された条件（{target_rank}ランク以上）に合致する候補者はいませんでした。\n"; return
    
    final_candidates.sort(key=lambda x: rank_order.index(x['grade']))

    for i, candidate in enumerate(final_candidates):
        name = candidate.get('name') or candidate.get('project_name')
        page_name = "技術者詳細" if search_target_type == 'engineer' else "案件詳細"
        link = f"/{page_name}?id={candidate['id']}" 
        
        yield f"#### **{i+1}. [{name} (ID: {candidate['id']})]({link}) - ランク: {candidate['grade']}**\n"
        if candidate.get('positive_points'):
            yield "**ポジティブな点:**\n"
            for point in candidate['positive_points']: yield f"- {point}\n"
        if candidate.get('concern_points'):
            yield "**懸念点:**\n"
            for point in candidate['concern_points']: yield f"- {point}\n"
        yield "\n"


# backend.py の get_all_candidate_ids_and_source_doc 関数をこちらに置き換えてください

def get_all_candidate_ids_and_source_doc(input_text: str) -> dict:
    """
    【修正版】
    入力テキストを解析し、キーワードで一次絞り込みを行った候補IDの全リストと、
    後続の処理で必要な情報を辞書で返す。
    """
    logs = []
    
    # --- 1a. テキスト分類と要約 ---
    logs.append("ステップ1/2: 入力情報を解析しています...")
    # split_text_with_llm はUI依存の可能性があるため、UI非依存版が望ましい
    # ここではそのまま使用するが、st.spinnerなどは呼び出し元で管理するのが理想
    with st.spinner("AIが入力テキストを分類・構造化中..."):
        parsed_data, llm_logs = split_text_with_llm(input_text)
    logs.extend(llm_logs)

    if not parsed_data:
        logs.append("❌ エラー: 入力情報から構造化データを抽出できませんでした。")
        return {"logs": logs}
    
    source_doc_type, search_target_type, source_item = (None, None, None)
    if parsed_data.get("jobs") and parsed_data["jobs"]:
        source_doc_type, search_target_type, source_item = 'job', 'engineer', parsed_data['jobs'][0]
    elif parsed_data.get("engineers") and parsed_data["engineers"]:
        source_doc_type, search_target_type, source_item = 'engineer', 'job', parsed_data['engineers'][0]
    
    if not source_doc_type or not source_item:
        logs.append("❌ エラー: テキストは構造化されましたが、案件か技術者か判断できませんでした。")
        return {"logs": logs}
        
    logs.append(f"  > 入力は「{source_doc_type}」情報と判断。検索ターゲットは「{search_target_type}」です。")
    source_doc = _build_meta_info_string(source_doc_type, source_item) + source_item.get("document", "")

    # --- 1b. キーワード抽出 ---
    logs.append("  > 検索キーワードをAIが抽出しています...")
    search_keywords = []
    try:
        keyword_extraction_prompt = f"""
            以下のテキストから、データベース検索に有効な技術要素、役職、スキル名を最大5つ、カンマ区切りの単語リストとして抜き出してください。
            バージョン情報や経験年数などの付随情報は含めず、単語のみを抽出してください。
            例:
            入力:「Laravel（v10）での開発経験があり、Vue.js（v3）も使えます。PM補佐の経験もあります。」
            出力: Laravel, Vue.js, PM
            入力テキスト: --- {input_text} ---
            出力:
        """
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        response = model.generate_content(keyword_extraction_prompt)
        keywords_from_ai = [kw.strip() for kw in response.text.strip().split(',') if kw.strip()]
        if not keywords_from_ai: raise ValueError("AI did not return keywords.")
        search_keywords = keywords_from_ai
    except Exception as e:
        logs.append(f"  > ⚠️ キーワード抽出失敗({e})。代替キーワードで検索します。")
        fallback_keyword = source_item.get("project_name") or source_item.get("name")
        if fallback_keyword:
            search_keywords = [fallback_keyword.strip()]

    if not search_keywords:
        logs.append("  > ❌ 検索キーワードを特定できず、処理を中断します。")
        # ★★★ 候補が0件であることを明示して返す ★★★
        return {"logs": logs, "all_candidate_ids": []}
        
    logs.append(f"  > 抽出キーワード: `{'`, `'.join(search_keywords)}`")

    # --- 1c. キーワードに一致する「IDのみ」をDBから全件取得 ---
    logs.append("ステップ2/2: キーワードに一致する候補をデータベースからリストアップしています...")
    target_table = search_target_type + 's'
    name_column = "project_name" if search_target_type == 'job' else "name"
    
    # ★★★ `params` をここで初期化する ★★★
    params = []
    
    query = f"SELECT id FROM {target_table} WHERE is_hidden = 0 AND ("
    or_conditions = []
    for kw in search_keywords:
        or_conditions.append(f"(document ILIKE %s OR {name_column} ILIKE %s)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    
    query += " OR ".join(or_conditions)
    query += ") ORDER BY id DESC"

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            all_candidate_ids = [item['id'] for item in cursor.fetchall()]
    except Exception as e:
        logs.append(f"❌ データベース検索中にエラーが発生しました: {e}")
        return {"logs": logs, "all_candidate_ids": []}
    finally:
        if conn: conn.close()

    if not all_candidate_ids:
        logs.append("✅ データベースを検索しましたが、キーワードに一致する候補は見つかりませんでした。")
        return {"logs": logs, "all_candidate_ids": []}
    
    return {
        "logs": logs,
        "all_candidate_ids": all_candidate_ids,
        "source_doc": source_doc,
        "search_target_type": search_target_type,
    }


# backend.py の evaluate_next_candidates 関数をこちらに置き換えてください
def evaluate_next_candidates(candidate_ids: list, source_doc: str, search_target_type: str, target_rank: str):
    """
    【修正版】
    ヒットした場合、Markdownではなく、フロントエンドで処理しやすいように
    構造化された辞書データを返す。
    """
    if not candidate_ids:
        return

    rank_order = ['S', 'A', 'B', 'C', 'D']
    try:
        valid_ranks = rank_order[:rank_order.index(target_rank) + 1]
    except ValueError:
        valid_ranks = []

    candidate_records = get_items_by_ids(search_target_type + 's', candidate_ids)

    for record in candidate_records:
        page_name = "技術者詳細" if search_target_type == 'engineer' else "案件詳細"
        candidate = dict(record)
        name = candidate.get('name') or candidate.get('project_name')
        
        # ... (前略: eval_progress, llm_start の yield) ...
        
        llm_result = get_match_summary_with_llm(source_doc, candidate['document'])

        if llm_result and llm_result.get('summary') in valid_ranks:
            # ★★★【ここからが修正の核】★★★
            # --- ヒットした場合 ---
            
            # 以前: Markdownを生成していた
            # 変更後: 必要な情報をすべて含んだ辞書を返す
            yield {
                "type": "hit_candidate",
                "data": {
                    "id": candidate['id'],
                    "name": name,
                    "grade": llm_result.get('summary'),
                    "positive_points": llm_result.get('positive_points', []),
                    "concern_points": llm_result.get('concern_points', []),
                    "page_name": page_name
                }
            }
            yield {"type": "pause"}
            # ★★★【修正ここまで】★★★

        else:
            # --- スキップした場合 (変更なし) ---
            actual_grade = llm_result.get('summary') if llm_result else "評価失敗"
            yield {
                "type": "skip_log",
                "message": f"候補「{name}」はスキップされました。(AI評価: {actual_grade})"
            }






def rematch_job_with_keyword_filtering(job_id, target_rank='B', target_count=5):
    """
    【案件詳細ページ専用】
    AIキーワード抽出による絞り込みを行い、最新の技術者から順にマッチング評価を実行する。
    処理の全ステップをログとしてyieldするジェネレータ。
    """
    if not job_id:
        yield "❌ 案件IDが指定されていません。"
        return

    rank_order = ['S', 'A', 'B', 'C', 'D']
    try:
        valid_ranks = rank_order[:rank_order.index(target_rank) + 1]
    except ValueError:
        yield f"❌ 無効な目標ランクが指定されました: {target_rank}"
        return

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # --- ステップ1: 案件情報の取得 ---
            yield "📄 対象案件の元情報を取得しています..."
            cursor.execute("SELECT source_data_json, document FROM jobs WHERE id = %s", (job_id,))
            job_record = cursor.fetchone()
            if not job_record or not job_record['source_data_json']:
                yield f"❌ 案件ID:{job_id} の元情報が見つかりませんでした。"
                return
            
            job_doc = job_record['document']
            source_data = json.loads(job_record['source_data_json'])
            original_text = source_data.get('body', '') + "".join([f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content')])

            # --- ステップ2: 検索キーワードの抽出 ---
            yield "🤖 検索の核となるキーワードをAIが抽出しています..."

            # ★★★ AIアクティビティログを記録 (キーワード抽出) ★★★
            try:
                cursor.execute("INSERT INTO ai_activity_log (activity_type) VALUES ('keyword_extraction')")
                # ここではまだコミットしない（トランザクションの一部とする）
            except Exception as log_err:
                yield f"  - ⚠️ AIアクティビティログの記録に失敗: {log_err}"

            search_keywords = []
            try:
                keyword_extraction_prompt = f"""
                    以下の案件情報テキストから、技術者を探す上で重要となる検索キーワードを最大10個、カンマ区切りの単語リストとして抜き出してください。
                    「必須」「歓迎」などの枕詞や、経験年数、単価などの付随情報は含めず、技術名や役職名などの単語のみを抽出してください。
                    入力テキスト: --- {original_text} ---
                    出力:
                """
                model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
                response = model.generate_content(keyword_extraction_prompt)
                search_keywords = [kw.strip() for kw in response.text.strip().split(',') if kw.strip()]
                if not search_keywords: raise ValueError("AI did not return keywords.")
                yield f"  > 抽出キーワード: `{', '.join(search_keywords)}`"
            except Exception as e:
                yield f"⚠️ キーワードのAI抽出に失敗({e})。全技術者を対象に処理を続行します。"

            # --- ステップ3: DB一次絞り込み (キーワードに一致する技術者IDを取得) ---
            yield "🔍 キーワードに一致する技術者候補をDBからリストアップしています..."

            # ★★★【ここからが修正の核】★★★
            CANDIDATE_LIMIT = 1000 # 評価対象の上限数を定義

            base_query = "SELECT id FROM engineers WHERE is_hidden = 0"
            where_clauses = []
            params = []

            if search_keywords:
                or_conditions = [f"(document ILIKE %s OR name ILIKE %s)" for _ in search_keywords]
                where_clauses.append(f"({ ' OR '.join(or_conditions) })")
                params.extend([f"%{kw}%" for kw in search_keywords for _ in (0, 1)])
            
            if where_clauses:
                base_query += " AND " + " AND ".join(where_clauses)
            
            # ORDER BYで最新順に並べ、LIMITで上限を設定
            final_query = f"{base_query} ORDER BY id DESC LIMIT {CANDIDATE_LIMIT}"
            
            cursor.execute(final_query, tuple(params))
            # ★★★【修正ここまで】★★★
            
            
            candidate_ids = [item['id'] for item in cursor.fetchall()]

            if not candidate_ids:
                yield "⚠️ キーワードに一致する技術者が見つかりませんでした。処理を終了します。"
                conn.commit()
                return
            yield f"  > **{len(candidate_ids)}名** の評価対象候補をリストアップしました。"
            
            # --- ステップ4: 既存マッチングのクリアと逐次評価 ---
            cursor.execute("DELETE FROM matching_results WHERE job_id = %s", (job_id,))
            yield f"🗑️ 案件ID:{job_id} の既存マッチング結果をクリアしました。"
            yield "🔄 絞り込んだ候補者リストに対して、順にマッチング処理を開始します..."

            candidate_records = get_items_by_ids_sync('engineers', candidate_ids) # 同期版で一括取得
            
            found_count = 0
            processed_count = 0
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            for engineer in candidate_records:
                processed_count += 1
                yield f"  `({processed_count}/{len(candidate_records)})` 技術者 **{engineer['name']}** とマッチング中..."
                
                # ★★★【ここからが修正の核】★★★
                # AI評価の実行前に、アクティビティログを記録する
                try:
                    cursor.execute(
                        "INSERT INTO ai_activity_log (activity_type) VALUES ('evaluation')"
                    )
                    # このINSERTはトランザクションの一部なので、ここではまだcommitしない
                except Exception as log_err:
                    yield f"  - ⚠️ AIアクティビティログの記録に失敗: {log_err}"
                # ★★★【修正ここまで】★★★

                llm_result = get_match_summary_with_llm(job_doc, engineer['document'])

                if llm_result and 'summary' in llm_result:
                    grade = llm_result.get('summary')
                    if grade in valid_ranks:
                        positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
                        concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)
                        score = 0.0
                        
                        try:
                            cursor.execute(
                                'INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade, positive_points, concern_points) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                                (job_id, engineer['id'], score, now_str, grade, positive_points, concern_points)
                            )
                            yield f"    -> **<span style='color: #28a745;'>✅ ヒット！</span>** 評価: **{grade}** ... DBに保存しました。"
                            found_count += 1
                        except Exception as db_err:
                            yield f"    -> <span style='color: #dc3545;'>❌ DB保存エラー</span>: {db_err}"
                    else:
                        yield f"    -> <span style='color: #ffc107;'>⏭️ スキップ</span> (評価: {grade})"
                else:
                    yield "    -> <span style='color: #dc3545;'>❌ LLM評価失敗</span>"

                if found_count >= target_count:
                    yield f"🎉 目標の {target_count} 件に到達したため、処理を終了します。"
                    break
            
            if found_count < target_count:
                yield f"ℹ️ すべての候補者の評価が完了しました。(ヒット数: {found_count}件)"

        conn.commit()
        yield "✅ すべての処理が正常に完了しました。"
    except Exception as e:
        conn.rollback()
        yield f"❌ 再評価・再マッチング中に予期せぬエラーが発生しました: {e}"
        import traceback
        yield f"```\n{traceback.format_exc()}\n```"

def get_items_by_ids_sync(item_type: str, ids: list, conn=None) -> list:
    """
    【SQL修正版】
    省略されていたSQLクエリを完全に実装する。
    DB接続オブジェクトを引数で受け取れるDIパターンに対応。
    """
    if not ids or item_type not in ['jobs', 'engineers']:
        return []

    should_close_conn = False
    if conn is None:
        conn = get_db_connection()
        if not conn: return []
        should_close_conn = True
    
    table_name = 'jobs' if item_type == 'jobs' else 'engineers'
    
    # ★★★【ここからが修正の核】★★★
    # 省略されていたクエリを完全に記述する
    query = f"""
        SELECT 
            t.*, 
            u.username as assigned_username,
            COALESCE(mc.match_count, 0) as match_count,
            CASE 
                WHEN amr.is_active = TRUE THEN TRUE
                ELSE FALSE
            END as auto_match_active
        FROM {table_name} t
        LEFT JOIN users u ON t.assigned_user_id = u.id
        LEFT JOIN (
            SELECT 
                {'job_id' if item_type == 'jobs' else 'engineer_id'} as item_id, 
                COUNT(*) as match_count
            FROM matching_results
            WHERE is_hidden = 0
            GROUP BY item_id
        ) AS mc ON t.id = mc.item_id
        LEFT JOIN auto_matching_requests amr 
            ON t.id = amr.item_id AND amr.item_type = %s
        WHERE t.id = ANY(%s)
    """
    # ★★★【修正ここまで】★★★

    BATCH_SIZE = 200
    results_map = {}
    
    try:
        with conn.cursor() as cursor:
            for i in range(0, len(ids), BATCH_SIZE):
                batch_ids = ids[i : i + BATCH_SIZE]
                if not batch_ids: continue
                
                # item_type をクエリのパラメータに追加
                cursor.execute(query, (item_type.rstrip('s'), batch_ids))
                
                batch_results = cursor.fetchall()
                for row in batch_results:
                    results_map[row['id']] = dict(row)
    except Exception as e:
        print(f"IDによるアイテム取得中にエラーが発生しました: {e}")
        return []
    finally:
        if should_close_conn and conn:
            conn.close()
    
    final_ordered_results = [results_map[id] for id in ids if id in results_map]
    return final_ordered_results



# 必要であれば、ストリーミング版も定義しておく
# (現時点では直接呼び出されていませんが、将来のために残しておくと良いでしょう)
def get_items_by_ids_stream(item_type: str, ids: list):
    """
    【ストリーミング版・ジェネレータ】
    大量のIDをバッチで取得し、その進捗をyieldで報告する。
    最終的に全レコードのリストをreturnで返す。
    """
    if not ids or item_type not in ['jobs', 'engineers']:
        return []

    table_name = 'jobs' if item_type == 'jobs' else 'engineers'
    BATCH_SIZE = 200
    results_map = {}
    total_ids = len(ids)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            for i in range(0, total_ids, BATCH_SIZE):
                batch_ids = ids[i : i + BATCH_SIZE]
                if not batch_ids:
                    continue
                
                processed_count = min(i + BATCH_SIZE, total_ids)
                yield f"  - DBから詳細データを取得中... ({processed_count} / {total_ids} 件)"
                
                query = f"""
                    SELECT ... 
                    WHERE t.id = ANY(%s)
                """ # (クエリ本体は sync 版と同じ)
                cursor.execute(query, (batch_ids,))
                
                batch_results = cursor.fetchall()
                for row in batch_results:
                    results_map[row['id']] = dict(row)
        
        yield f"  - ✅ 全 {total_ids} 件のデータ取得完了。"

    except Exception as e:
        yield f"❌ IDによるアイテム取得中にエラーが発生しました: {e}"
        return []
    finally:
        if conn:
            conn.close()

    final_ordered_results = [results_map[id] for id in ids if id in results_map]
    return final_ordered_results



# backend.py の末尾に、以下の新しい関数を追加してください
# backend.py の rematch_engineer_with_keyword_filtering 関数をこちらに置き換えてください

def rematch_engineer_with_keyword_filtering(engineer_id, target_rank='B', target_count=5):
    """
    【技術者詳細ページ専用・完成版】
    AIキーワード抽出→DB絞り込み→逐次評価を行うジェネレータ。
    DIパターンに対応し、st.secretsに依存しない。
    """
    if not engineer_id:
        yield "❌ 技術者IDが指定されていません。"
        return

    rank_order = ['S', 'A', 'B', 'C', 'D']
    try:
        valid_ranks = rank_order[:rank_order.index(target_rank) + 1]
    except ValueError:
        yield f"❌ 無効な目標ランクが指定されました: {target_rank}"
        return

    # ★★★ DIパターンのため、この関数はUIから直接呼び出されることを前提とし、
    # get_db_connection() を使う。バッチ処理からは呼ばない。
    conn = get_db_connection()
    if not conn:
        yield "❌ データベース接続に失敗しました。"
        return

    try:
        with conn.cursor() as cursor:
            # --- ステップ1: 技術者情報の取得 ---
            yield "📄 対象技術者の元情報を取得しています..."
            cursor.execute("SELECT source_data_json, document FROM engineers WHERE id = %s", (engineer_id,))
            engineer_record = cursor.fetchone()
            if not engineer_record or not engineer_record['source_data_json']:
                yield f"❌ 技術者ID:{engineer_id} の元情報が見つかりませんでした。"; return
            
            engineer_doc = engineer_record['document']
            source_data = json.loads(engineer_record['source_data_json'])
            original_text = source_data.get('body', '') + "".join([f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content')])

            # --- ステップ2: 検索キーワードの抽出 ---
            yield "🤖 検索の核となるキーワードをAIが抽出しています..."
            search_keywords = []
            try:
                # ▼▼▼【ここからが修正の核】▼▼▼
                keyword_extraction_prompt = f"""
                    以下の技術者情報テキストから、案件を探す上で重要となる検索キーワードを最大10個、カンマ区切りの単語リストとして抜き出してください。
                    「必須」「歓迎」などの枕詞や、経験年数、単価などの付随情報は含めず、技術名や役職名などの単語のみを抽出してください。
                    例:
                    入力:「Java(SpringBoot), PHP(CakePHP)でのバックエンド開発経験が豊富です。AWS上でのインフラ構築も対応可能です。」
                    出力: Java, SpringBoot, PHP, CakePHP, AWS

                    入力テキスト: ---
                    {original_text}
                    ---
                    出力:
                """
                # ▲▲▲【修正ここまで】▲▲▲

                
                model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
                response = model.generate_content(keyword_extraction_prompt)
                search_keywords = [kw.strip() for kw in response.text.strip().split(',') if kw.strip()]
                if not search_keywords: raise ValueError("AI did not return keywords.")
                yield f"  > 抽出キーワード: `{', '.join(search_keywords)}`"
            except Exception as e:
                yield f"⚠️ キーワードのAI抽出に失敗({e})。全案件を対象に処理を続行します。"

            # --- ステップ3: DB一次絞り込み ---
            yield "🔍 キーワードに一致する案件候補をDBからリストアップしています..."
            CANDIDATE_LIMIT = 1000
            base_query = "SELECT id FROM jobs WHERE is_hidden = 0"
            where_clauses = []
            params = []

            if search_keywords:
                or_conditions = [f"(document ILIKE %s OR project_name ILIKE %s)" for _ in search_keywords]
                where_clauses.append(f"({ ' OR '.join(or_conditions) })")
                # ★★★【ここが修正の核】★★★
                # ループの外でまとめてextendするのではなく、ループの中で都度追加する
                for kw in search_keywords:
                    param = f"%{kw}%"
                    params.extend([param, param])
                # ★★★【修正ここまで】★★★
            
            if where_clauses:
                base_query += " AND " + " AND ".join(where_clauses)
            
            final_query = f"{base_query} ORDER BY id DESC LIMIT {CANDIDATE_LIMIT}"
            cursor.execute(final_query, tuple(params))
            
            candidate_ids = [item['id'] for item in cursor.fetchall()]

            if not candidate_ids:
                yield "⚠️ キーワードに一致する案件が見つかりませんでした。"; conn.commit(); return
            yield f"  > DBから最新 **{len(candidate_ids)}件** (最大{CANDIDATE_LIMIT}件) の評価対象候補をリストアップしました。"
            
            # --- ステップ4: 既存マッチングのクリアと逐次評価 ---
            # このトランザクション内でDELETEを実行
            cursor.execute("DELETE FROM matching_results WHERE engineer_id = %s", (engineer_id,))
            yield f"🗑️ 技術者ID:{engineer_id} の既存マッチング結果をクリアしました。"
            
            yield "🔄 絞り込んだ候補案件リストに対して、順にマッチング処理を開始します..."

            # get_items_by_ids_sync に現在の接続オブジェクトを渡す
            candidate_records = get_items_by_ids_sync('jobs', candidate_ids, conn=conn)
            
            found_count, processed_count = 0, 0
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            for job in candidate_records:
                processed_count += 1
                yield f"  `({processed_count}/{len(candidate_records)})` 案件 **{job.get('project_name', 'N/A')}** とマッチング中..."
                
                # ★★★【ここからが修正の核】★★★
                # AI評価の実行前に、アクティビティログを記録する
                try:
                    cursor.execute(
                        "INSERT INTO ai_activity_log (activity_type) VALUES ('evaluation')"
                    )
                except Exception as log_err:
                    yield f"  - ⚠️ AIアクティビティログの記録に失敗: {log_err}"
                # ★★★【修正ここまで】★★★

                llm_result = get_match_summary_with_llm(job['document'], engineer_doc)
                if llm_result and 'summary' in llm_result:
                    grade = llm_result.get('summary')
                    if grade in valid_ranks:
                        try:
                            # create_or_update_match_record に現在の接続オブジェクトを渡す
                            create_or_update_match_record(job['id'], engineer_id, 0.0, grade, llm_result, conn=conn)
                            yield f"    -> **<span style='color: #28a745;'>✅ ヒット！</span>** 評価: **{grade}**"
                            found_count += 1
                        except Exception as db_err:
                            yield f"    -> <span style='color: #dc3545;'>❌ DB保存エラー</span>: {db_err}"
                else:
                    yield f"    -> <span style='color: #ffc107;'>⏭️ スキップ</span> (評価: {llm_result.get('summary', '失敗') if llm_result else '失敗'})"
                if found_count >= target_count:
                    yield f"🎉 目標の {target_count} 件に到達したため、処理を終了します。"; break
            
            if found_count < target_count:
                yield f"ℹ️ すべての候補案件の評価が完了しました。(ヒット数: {found_count}件)"

        conn.commit()
        yield "✅ すべての処理が正常に完了しました。"
    except Exception as e:
        conn.rollback()
        yield f"❌ 再評価・再マッチング中に予期せぬエラーが発生しました: {e}"
        import traceback; yield f"```\n{traceback.format_exc()}\n```"
    finally:
        if conn:
            conn.close()






def update_job_project_name(job_id: int, new_project_name: str) -> bool:
    """
    指定された案件IDの project_name を更新する。
    """
    # 新しい案件名が空文字列や空白のみの場合は更新しない
    if not new_project_name or not new_project_name.strip():
        print("新しい案件名が空のため、更新をスキップしました。")
        return False
        
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET project_name = %s WHERE id = %s",
                    (new_project_name.strip(), job_id)
                )
            conn.commit()
            return True
        except (Exception, psycopg2.Error) as e:
            print(f"案件名の更新中にエラーが発生しました: {e}")
            conn.rollback()
            return False



import smtplib
from email.mime.text import MIMEText
from email.header import Header

# backend.py の add_or_update_auto_match_request 関数をこちらに置き換えてください

def add_or_update_auto_match_request(item_id, item_type, target_rank, email, user_id):
    """
    【UPSERT修正版】
    自動マッチング依頼を登録または更新する。
    - 新規登録時: last_processed_id に現在の最新IDを設定。
    - 更新時: もし last_processed_id が NULL ならば、現在の最新IDで更新する。
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            # --- ステップ1: 現在の最新IDを取得 ---
            cur.execute("SELECT MAX(id) FROM jobs")
            current_max_job_id = (res := cur.fetchone()) and res['max'] or 0
            
            cur.execute("SELECT MAX(id) FROM engineers")
            current_max_engineer_id = (res := cur.fetchone()) and res['max'] or 0

            # --- ステップ2: 依頼をDBに登録/更新 (UPSERT) ---
            # ★★★【ここからが修正の核】★★★
            sql = """
                INSERT INTO auto_matching_requests (
                    item_id, item_type, target_rank, notification_email, created_by_user_id, 
                    is_active, last_processed_job_id, last_processed_engineer_id
                )
                VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s)
                ON CONFLICT (item_id, item_type) 
                DO UPDATE SET 
                    target_rank = EXCLUDED.target_rank,
                    notification_email = EXCLUDED.notification_email,
                    is_active = TRUE,
                    created_by_user_id = EXCLUDED.created_by_user_id,
                    -- 既存のレコードを更新する際に、もし last_processed_id が NULL ならば、
                    -- 現在の最新IDで更新する。既に値が入っていれば変更しない。
                    last_processed_job_id = COALESCE(auto_matching_requests.last_processed_job_id, EXCLUDED.last_processed_job_id),
                    last_processed_engineer_id = COALESCE(auto_matching_requests.last_processed_engineer_id, EXCLUDED.last_processed_engineer_id)
                RETURNING last_processed_job_id, last_processed_engineer_id;
            """
            cur.execute(sql, (
                item_id, item_type, target_rank, email, user_id, 
                current_max_job_id, current_max_engineer_id
            ))
            
            # 実際にDBに書き込まれた値を取得
            result = cur.fetchone()
            actual_last_job_id = result['last_processed_job_id'] if result else 'N/A'
            actual_last_eng_id = result['last_processed_engineer_id'] if result else 'N/A'
            # ★★★【修正ここまで】★★★
            
        conn.commit()
        # 実際にDBに書き込まれた値でログを出力
        print(f"✅ Successfully UPSERTED auto-match request for {item_type} ID: {item_id}.")
        print(f"   DB value for last_processed_job_id: {actual_last_job_id}")
        print(f"   DB value for last_processed_engineer_id: {actual_last_eng_id}")
        return True
        
    except (Exception, psycopg2.Error) as e:
        print(f"❌ Error in add_or_update_auto_match_request: {e}")
        conn.rollback()
        return False
        
    finally:
        if conn:
            conn.close()





def deactivate_auto_match_request(item_id: int, item_type: str) -> bool:
    """
    指定された item_id と item_type に一致する自動マッチング依頼を
    非アクティブ（is_active = FALSE）にする。
    """
    # 1. 実行するSQL文を定義
    sql = """
        UPDATE auto_matching_requests 
        SET is_active = FALSE 
        WHERE item_id = %s AND item_type = %s;
    """
    
    # 2. データベースに接続
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        # 3. カーソルを作成し、クエリを実行
        with conn.cursor() as cur:
            # ★★★【修正点1】★★★
            # SQL文が必要とする引数のみ（2つ）を渡す
            cur.execute(sql, (item_id, item_type))
            
        # 4. 変更をコミット
        conn.commit()
        
        print(f"✅ Deactivated auto-match request for {item_type} ID: {item_id}")
        return True
        
    except (Exception, psycopg2.Error) as e:
        # ★★★【修正点2】★★★
        # エラーメッセージをこの関数専用のものに修正
        print(f"❌ Error deactivating auto_match_request for {item_type} ID: {item_id}. Error: {e}")
        conn.rollback()
        return False
        
    finally:
        # 5. データベース接続を閉じる
        if conn:
            conn.close()


        

def get_auto_match_request(item_id: int, item_type: str) -> dict | None:
    """
    指定された item_id と item_type に一致する、アクティブな自動マッチング依頼を
    データベースから1件だけ取得して返す。
    存在しない場合は None を返す。
    """
    # 1. 取得したいレコードを特定するためのSQL文を定義
    #    WHERE句で条件を絞り込み、LIMIT 1 で確実に1行だけを取得するようにする
    sql = """
        SELECT * 
        FROM auto_matching_requests 
        WHERE item_id = %s AND item_type = %s AND is_active = TRUE
        LIMIT 1;
    """
    
    # 戻り値用の変数を None で初期化
    result_data = None

    # 2. データベースに接続
    conn = get_db_connection()
    if not conn:
        # 接続に失敗した場合は何もできないので None を返す
        return None
        
    try:
        # 3. カーソルを作成し、クエリを実行
        with conn.cursor() as cursor:
            cursor.execute(sql, (item_id, item_type))
            
            # 4. fetchone() で結果を1行だけ取得
            result_data = cursor.fetchone()
            
    except (Exception, psycopg2.Error) as e:
        print(f"Error in get_auto_match_request: {e}")
        # エラーが発生した場合も None を返す
        return None
    finally:
        # 5. データベース接続を閉じる
        if conn:
            conn.close()

    # 6. 取得したデータ（辞書 or None）を返す
    if result_data:
        # DictCursorが返すDictRowオブジェクトを、通常の辞書に変換して返すとより安全
        return dict(result_data)
    else:
        # レコードが見つからなかった場合は None を返す
        return None
    

import smtplib
from email.mime.text import MIMEText
from email.header import Header
import streamlit as st # st.secrets を使うためにインポートが必要

# --- メール通知機能 ---
def send_email_notification(recipient_email, subject, body):
    try:
        # st.secrets.セクション名.キー名 の形式でアクセス
        SMTP_SERVER = st.secrets.smtp.server
        SMTP_PORT = st.secrets.smtp.port
        SMTP_USER = st.secrets.smtp.user
        SMTP_PASSWORD = st.secrets.smtp.password
        FROM_EMAIL = st.secrets.smtp.from_email
        
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = FROM_EMAIL
        msg['To'] = recipient_email

        # smtplib.SMTP を使ってサーバーに接続
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            
            # サーバーに挨拶 (EHLO) を送り、STARTTLSをサポートしているか確認
            server.ehlo()
            # STARTTLSコマンドで暗号化通信を開始
            server.starttls()
            # 再度挨拶を送る
            server.ehlo()
            # ログイン
            server.login(SMTP_USER, SMTP_PASSWORD)
            # メッセージを送信
            server.send_message(msg)
        
        print(f"✅ Notification email sent to {recipient_email}")
        return True
        
    except KeyError as e:
        print(f"❌ Email sending failed: SMTP secret key '{e}' not found in [smtp] section.")
        return False
    except Exception as e:
        print(f"❌ Email sending failed: {e}")
        return False
    

def update_auto_match_last_processed_ids(request_id, last_job_id, last_engineer_id, conn=None):

    """自動マッチング依頼の、最後に処理したIDを更新する。"""
    updates = []
    params = []
    if last_job_id:
        updates.append("last_processed_job_id = %s")
        params.append(last_job_id)
    if last_engineer_id:
        updates.append("last_processed_engineer_id = %s")
        params.append(last_engineer_id)

    if not updates:
        return True # 更新対象がなければ何もしない

    params.append(request_id)
    sql = f"UPDATE auto_matching_requests SET {', '.join(updates)} WHERE id = %s"
    
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error updating last processed IDs: {e}")
            conn.rollback()
            return False
        

def create_or_update_match_record(job_id, engineer_id, score, grade, llm_result, conn=None):

    """
    matching_resultsテーブルにレコードを挿入または更新する（UPSERT）。
    成功した場合は、作成/更新されたレコードのIDを返す。
    """
    # llm_resultからポジティブ/懸念点をJSON文字列に変換
    positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
    concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # ON CONFLICT句を使ったUPSERT文
    sql = """
        INSERT INTO matching_results (
            job_id, engineer_id, score, created_at, grade, 
            positive_points, concern_points, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, '新規')
        ON CONFLICT (job_id, engineer_id) 
        DO UPDATE SET
            score = EXCLUDED.score,
            grade = EXCLUDED.grade,
            positive_points = EXCLUDED.positive_points,
            concern_points = EXCLUDED.concern_points,
            created_at = EXCLUDED.created_at, -- 更新日時も最新にする
            status = '新規' -- 再評価時はステータスをリセット
        RETURNING id;
    """
    
    conn = get_db_connection()
    if not conn:
        return None
        
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                job_id, engineer_id, score, now_str, grade, 
                positive_points, concern_points
            ))
            result = cur.fetchone()
        conn.commit()
        
        # RETURNINGで返されたIDを返す
        return result['id'] if result else None
        
    except (Exception, psycopg2.Error) as e:
        print(f"Error in create_or_update_match_record: {e}")
        conn.rollback()
        return None
        
    finally:
        if conn:
            conn.close()





def clear_matches_for_job(job_id: int, conn=None) -> bool:
    """指定された案件IDに紐づく全てのマッチング結果を削除する。"""
    if not job_id:
        return False
    
    should_close_conn = False
    if conn is None:
        conn = get_db_connection()
        if not conn: return False
        should_close_conn = True
        
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM matching_results WHERE job_id = %s", (job_id,))
            print(f"✅ Cleared {cur.rowcount} matches for job_id: {job_id}")
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Error clearing matches for job_id {job_id}: {e}")
        conn.rollback()
        return False
    finally:
        if should_close_conn and conn:
            conn.close()


def clear_matches_for_engineer(engineer_id: int, conn=None) -> bool:
    """指定された技術者IDに紐づく全てのマッチング結果を削除する。"""
    if not engineer_id:
        return False
    
    should_close_conn = False
    if conn is None:
        conn = get_db_connection()
        if not conn: return False
        should_close_conn = True
        
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM matching_results WHERE engineer_id = %s", (engineer_id,))
            print(f"✅ Cleared {cur.rowcount} matches for engineer_id: {engineer_id}")
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Error clearing matches for engineer_id {engineer_id}: {e}")
        conn.rollback()
        return False
    finally:
        if should_close_conn and conn:
            conn.close()

# backend.py の get_live_dashboard_data 関数をこちらに置き換えてください


@st.cache_data(ttl=10)
def get_live_dashboard_data():
    """
    【タイムゾーン対応・完全リファクタリング版】
    経営者向けライブモニタリングダッシュボード用のデータをまとめて取得する。
    """
    data = {
        "jobs_today": 0, "engineers_today": 0, "processed_items_today": 0,
        "new_matches_today": 0, "adopted_count_today": 0,
        "ai_activity_counts": {}, "funnel_data": {}, "proposal_count_total": 0,
        "active_auto_request_count": 0, "active_auto_requests": [],
        "top_performers": [], "recent_matches": [], "live_log_feed": []
    }
    
    conn = get_db_connection()
    if not conn:
        return data

    try:
        with conn.cursor() as cur:

            target_tz = pytz.timezone('America/Los_Angeles') #Asia/Tokyo
            now_in_target_tz = datetime.now(target_tz)
            
            # 「過去24時間前」の時刻を計算
            twenty_four_hours_ago = now_in_target_tz - timedelta(hours=24)
            
            # 「今月の始まり」はランキングで使うため残しておく
            this_month_start = now_in_target_tz.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


            # 過去24時間以内に登録された案件・技術者の数
            cur.execute("SELECT COUNT(*) FROM jobs WHERE is_hidden = 0 AND created_at >= %s", (twenty_four_hours_ago,))
            data["jobs_today"] = cur.fetchone()['count']
            
            cur.execute("SELECT COUNT(*) FROM engineers WHERE is_hidden = 0 AND created_at >= %s", (twenty_four_hours_ago,))
            data["engineers_today"] = cur.fetchone()['count']
            
            # ラベルは「本日」のままだが、中身は過去24時間の集計になる
            data["processed_items_today"] = data["jobs_today"] + data["engineers_today"]

            # 過去24時間以内に作成されたマッチングの総数
            cur.execute("SELECT COUNT(*) FROM matching_results WHERE is_hidden = 0 AND created_at >= %s", (twenty_four_hours_ago,))
            data["new_matches_today"] = cur.fetchone()['count']

            # 過去24時間以内に「採用」にステータス変更された件数
            cur.execute("SELECT COUNT(*) FROM matching_results WHERE status = '採用' AND status_updated_at >= %s", (twenty_four_hours_ago,))
            data["adopted_count_today"] = cur.fetchone()['count']

            # 過去24時間のAIアクティビティ
            cur.execute("SELECT activity_type, COUNT(*) as count FROM ai_activity_log WHERE created_at >= %s GROUP BY activity_type", (twenty_four_hours_ago,))
            for row in cur.fetchall():
                data["ai_activity_counts"][row['activity_type']] = row['count']

            # --- 3. その他の集計 ---
            # ファネルチャート用データ
            cur.execute("SELECT status, COUNT(*) as count FROM matching_results WHERE is_hidden = 0 GROUP BY status")
            for row in cur.fetchall():
                data['funnel_data'][row['status']] = row['count']

            # 担当者別ランキング（今月の「採用」件数）
            cur.execute("""
                SELECT u.username, COUNT(r.id) as adoption_count FROM matching_results r
                JOIN jobs j ON r.job_id = j.id JOIN users u ON j.assigned_user_id = u.id
                WHERE r.status = '採用' AND r.created_at >= %s GROUP BY u.username
                ORDER BY adoption_count DESC LIMIT 5
            """, (this_month_start,))
            data["top_performers"] = [dict(row) for row in cur.fetchall()]

            # 提案中の総件数
            cur.execute("SELECT COUNT(*) FROM matching_results WHERE status IN ('提案準備中', '提案中')")
            data["proposal_count_total"] = cur.fetchone()['count']
            
            # アクティブな自動マッチング依頼
            cur.execute("SELECT COUNT(*) FROM auto_matching_requests WHERE is_active = TRUE")
            data["active_auto_request_count"] = cur.fetchone()['count']
            cur.execute("""
                (SELECT req.*, j.project_name as item_name, j.document, COALESCE(mc.match_count, 0) as match_count FROM auto_matching_requests req JOIN jobs j ON req.item_id = j.id AND req.item_type = 'job' LEFT JOIN (SELECT job_id, COUNT(*) as match_count FROM matching_results WHERE is_hidden = 0 GROUP BY job_id) mc ON j.id = mc.job_id WHERE req.is_active = TRUE)
                UNION ALL
                (SELECT req.*, e.name as item_name, e.document, COALESCE(mc.match_count, 0) as match_count FROM auto_matching_requests req JOIN engineers e ON req.item_id = e.id AND req.item_type = 'engineer' LEFT JOIN (SELECT engineer_id, COUNT(*) as match_count FROM matching_results WHERE is_hidden = 0 GROUP BY engineer_id) mc ON e.id = mc.engineer_id WHERE req.is_active = TRUE)
                ORDER BY created_at DESC LIMIT 5
            """)
            data["active_auto_requests"] = [dict(row) for row in cur.fetchall()]

            # ▼▼▼【ここからが修正の核】▼▼▼
            # 10. リアルタイム活動ログ
            cur.execute("""
                SELECT * FROM (
                    SELECT 
                        'processing' as log_type, 
                        j.project_name, 
                        e.name as engineer_name, 
                        r.grade, 
                        r.created_at, 
                        j.id as job_id, 
                        e.id as engineer_id,
                        r.id as result_id  -- ★★★ マッチング結果IDを追加
                    FROM matching_results r 
                    JOIN jobs j ON r.job_id = j.id 
                    JOIN engineers e ON r.engineer_id = e.id
                    WHERE r.is_hidden = 0

                    UNION ALL

                    SELECT 
                        'input' as log_type, 
                        project_name, 
                        NULL as engineer_name, 
                        NULL as grade, 
                        created_at, 
                        id as job_id, 
                        NULL as engineer_id,
                        NULL as result_id -- ★★★ 型を合わせるためNULLを追加

                    FROM jobs WHERE is_hidden = 0

                    UNION ALL

                    SELECT 
                        'input' as log_type, 
                        NULL as project_name, 
                        name as engineer_name, 
                        NULL as grade, 
                        created_at, 
                        NULL as job_id, 
                        id as engineer_id,
                        NULL as result_id -- ★★★ 型を合わせるためNULLを追加
                        
                    FROM engineers WHERE is_hidden = 0
                ) AS combined_logs
                ORDER BY created_at DESC
                LIMIT 10;
            """)
            data["live_log_feed"] = [dict(row) for row in cur.fetchall()]
            # ▲▲▲【修正ここまで】▲▲▲
                    






    except Exception as e:
        print(f"Error in get_live_dashboard_data: {e}")
    finally:
        if conn:
            conn.close()
            
    return data





def generate_text(prompt: str, max_tokens: int = 150) -> str:
    """
    Gemini APIを呼び出し、プロンプトに対する応答を生成する関数。
    """

    # --- Gemini APIの初期設定 ---
    # この部分はファイルの先頭や適切な場所で行う
    try:
        
        gemini_model = genai.GenerativeModel('models/gemini-2.5-flash-lite')

        response = gemini_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=0.7 # 創造性の度合い
            )
        )
        return response.text.strip()
    
    except Exception as e:
        # st.secretsが読み込めない場合などのエラーハンドリング
        print(f"Gemini APIの初期化に失敗しました: {e}")
        gemini_model = None




def get_current_time_str_in_jst(format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
    """
    現在の時刻をJST（日本標準時）で取得し、指定されたフォーマットの文字列として返す。

    Args:
        format_str (str, optional): 
            時刻のフォーマット文字列。
            デフォルトは '%Y-%m-%d %H:%M:%S'。

    Returns:
        str: フォーマットされたJST時刻の文字列。
    """
    try:
        # 1. 東京のタイムゾーンオブジェクトを取得
        jst_tz = pytz.timezone('Asia/Tokyo')
        
        # 2. 東京時間での現在時刻を取得
        now_in_jst = datetime.now(jst_tz)
        
        # 3. 指定されたフォーマットで文字列に変換して返す
        return now_in_jst.strftime(format_str)
        
    except Exception as e:
        # pytzが見つからないなどのエラーが発生した場合のフォールバック
        print(f"ERROR in get_current_time_str_in_jst: {e}")
        # とりあえず、タイムゾーン情報なしの現在時刻を返す
        return datetime.now().strftime(format_str)
    

