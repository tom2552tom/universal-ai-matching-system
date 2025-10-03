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
MIN_SCORE_THRESHOLD = 0.0 

@st.cache_data
def load_app_config():
    try:
        with open("config.toml", "r", encoding="utf-8") as f: return toml.load(f)
    except FileNotFoundError: return {"app": {"title": "Universal AI Agent"}}

@st.cache_resource
def load_embedding_model():
    try: return SentenceTransformer(MODEL_NAME)
    except Exception as e: st.error(f"埋め込みモデル '{MODEL_NAME}' の読み込みに失敗しました: {e}"); return None

def init_database():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS engineers (id INTEGER PRIMARY KEY AUTOINCREMENT, document TEXT NOT NULL, source_data_json TEXT, created_at TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS matching_results (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, engineer_id INTEGER, score REAL, created_at TEXT, is_hidden INTEGER DEFAULT 0, FOREIGN KEY (job_id) REFERENCES jobs (id), FOREIGN KEY (engineer_id) REFERENCES engineers (id))')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; return conn

# ★★★ 404エラー修正: ユーザー様が発見した正しいモデル名を採用 ★★★
def split_text_with_llm(text_content):
    #model = genai.GenerativeModel('models/gemini-1.5-pro-latest')
    model = genai.GenerativeModel('models/gemini-2.5-pro')
    prompt = f"""
あなたは、IT業界の案件情報と技術者情報を構造化データとして抽出する優秀なアシスタントです。
以下のメール本文テキストから、「案件情報」と「技術者情報」をそれぞれ抽出し、指定のJSON形式で出力してください。
# 抽出項目とルール
- document: 元の情報をサマリーした、概要テキスト。
- nationality: 技術者の国籍。
- nationality_requirement: 案件の国籍要件。
- start_date: 稼働開始可能日または案件の開始時期。
- 該当する情報がない項目は null としてください。
- 抽出できる情報がない場合は、空のリスト `[]` を持つJSONを返してください。
# 対象テキスト
---
{text_content}
---
# 出力形式 (JSONのみ)
{{ "jobs": [ ... ], "engineers": [ ... ] }}
"""
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        with st.spinner("LLMがテキストを解析・構造化中..."):
            response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        return json.loads(response.text)
    except Exception as e:
        st.error(f"LLMによる構造化に失敗: {e}"); return None

def get_match_summary_with_llm(job_doc, engineer_doc):
    #model = genai.GenerativeModel('models/gemini-1.5-pro-latest')
    model = genai.GenerativeModel('models/gemini-2.5-pro')
    prompt = f"""
あなたは優秀なIT採用担当者です。以下の【案件情報】と【技術者情報】を比較し、分析してください。
結果は必ず指定のJSON形式で出力してください。
# 分析のポイント
- positive_points: マッチする点。
- concern_points: 懸念点。
- summary: 総合的なサマリー。
# 【案件情報】
{job_doc}
# 【技術者情報】
{engineer_doc}
# 出力形式 (JSONのみ)
{{ "positive_points": ["<合致する点1>"], "concern_points": ["<懸念点1>"], "summary": "<総合評価サマリー>" }}
"""
    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    try:
        with st.spinner("AIがマッチング根拠を分析中..."):
            response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        return json.loads(response.text)
    except Exception as e:
        st.error(f"根拠の分析中にエラー: {e}"); return None

def process_single_content(source_data: dict):
    if not source_data: st.warning("処理するデータが空です。"); return False
    body_text_for_llm = source_data.get('body', '')
    if not body_text_for_llm.strip(): st.warning("メール本文が空のため、AIによる解析をスキップします。"); return False
    parsed_data = split_text_with_llm(body_text_for_llm)
    if not parsed_data: return False
    new_jobs_data = parsed_data.get("jobs", []); new_engineers_data = parsed_data.get("engineers", [])
    if not new_jobs_data and not new_engineers_data: st.warning("LLMはメール本文から案件情報または技術者情報を抽出できませんでした。"); return False
    with get_db_connection() as conn:
        cursor = conn.cursor(); now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        source_json_str = json.dumps(source_data, ensure_ascii=False, indent=2)
        for item_data in new_jobs_data:
            doc = item_data.get("document")
            if not (doc and str(doc).strip() and str(doc).lower() != 'none'): st.warning("LLMが案件の要約を生成できませんでした。メール本文を代替として使用します。"); doc = body_text_for_llm
            meta_info = f"[国籍要件: {item_data.get('nationality_requirement', '不明')}] [開始時期: {item_data.get('start_date', '不明')}]\n---\n"; full_document = meta_info + doc
            cursor.execute('INSERT INTO jobs (document, source_data_json, created_at) VALUES (?, ?, ?)', (full_document, source_json_str, now_str)); 
        for item_data in new_engineers_data:
            doc = item_data.get("document")
            if not (doc and str(doc).strip() and str(doc).lower() != 'none'): st.warning("LLMが技術者の要約を生成できませんでした。メール本文を代替として使用します。"); doc = body_text_for_llm
            meta_info = f"[国籍: {item_data.get('nationality', '不明')}] [稼働可能日: {item_data.get('start_date', '不明')}]\n---\n"; full_document = meta_info + doc
            cursor.execute('INSERT INTO engineers (document, source_data_json, created_at) VALUES (?, ?, ?)', (full_document, source_json_str, now_str)); 
    return True

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
                    st.write(f"📄 添付ファイル '{filename}' を発見しました。"); attachments.append({"filename": filename})
    else:
        charset = msg.get_content_charset()
        try: body_text = msg.get_payload(decode=True).decode(charset if charset else 'utf-8', errors='ignore')
        except Exception: body_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    return {"body": body_text.strip(), "attachments": attachments}

# ★★★ TypeError修正: すべてのreturnパスで2つの値を返すように修正 ★★★
def fetch_and_process_emails():
    log_stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(log_stream):
            try:
                SERVER, USER, PASSWORD = st.secrets["EMAIL_SERVER"], st.secrets["EMAIL_USER"], st.secrets["EMAIL_PASSWORD"]
            except KeyError as e:
                st.error(f"メールサーバーの接続情報がSecretsに設定されていません: {e}")
                return False, log_stream.getvalue() # 2つの値を返す

            try:
                mail = imaplib.IMAP4_SSL(SERVER)
                mail.login(USER, PASSWORD)
                mail.select('inbox')
            except Exception as e:
                st.error(f"メールサーバーへの接続またはログインに失敗しました: {e}")
                return False, log_stream.getvalue() # 2つの値を返す

            total_processed_count = 0
            try:
                with st.status("最新の未読メールを取得・処理中...", expanded=True) as status:
                    _, messages = mail.search(None, 'UNSEEN')
                    email_ids = messages[0].split()
                    if not email_ids:
                        st.write("処理対象の未読メールは見つかりませんでした。")
                    else:
                        latest_ids = email_ids[::-1][:10]
                        st.write(f"最新の未読メール {len(latest_ids)}件をチェックします。")
                        for i, email_id in enumerate(latest_ids):
                            _, msg_data = mail.fetch(email_id, '(RFC822)')
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    msg = email.message_from_bytes(response_part[1])
                                    source_data = get_email_contents(msg)
                                    if source_data['body'] or source_data['attachments']:
                                        st.write(f"✅ メールID {email_id.decode()} は処理対象です。解析を開始します...")
                                        if process_single_content(source_data):
                                            total_processed_count += 1
                                            mail.store(email_id, '+FLAGS', '\\Seen')
                                    else: st.write(f"✖️ メールID {email_id.decode()} は処理対象外です。スキップします。")
                            st.write(f"({i+1}/{len(latest_ids)}) チェック完了")
                    status.update(label="メールチェック完了", state="complete")
            finally:
                mail.close()
                mail.logout()

        if total_processed_count > 0:
            st.success(f"合計 {total_processed_count} 件のメールからデータを抽出し、保存しました。"); st.balloons()
        else:
            st.info("処理対象となる新しい未読メールはありませんでした。")
        return True, log_stream.getvalue() # 2つの値を返す

    except Exception as e:
        st.error(f"予期せぬエラーが発生しました: {e}")
        return False, log_stream.getvalue() # 2つの値を返す

def hide_match(result_id): pass
# (ベクトル検索関連の update_index, search, run_matching_for_item は今回のデバッグでは使用していないため、省略しています)
