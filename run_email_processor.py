# ==============================================================================
# run_email_processor.py (完成版)
# ==============================================================================

import sys
import os
import toml
import imaplib
import email
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from datetime import datetime
import traceback
import psycopg2
from psycopg2.extras import DictCursor
import google.generativeai as genai
import json
import re
import io
import fitz
import docx
import pandas as pd

# --- グローバル設定 ---
_SECRETS = None
_CONFIG = None

# ==============================================================================
# 1. ヘルパー関数群
# ==============================================================================

# --- 設定・DB接続関連 ---
def load_secrets():
    global _SECRETS
    if _SECRETS is not None: return _SECRETS
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(current_dir, '.streamlit', 'secrets.toml')
        with open(secrets_path, "r", encoding="utf-8") as f: _SECRETS = toml.load(f)
        return _SECRETS
    except Exception as e:
        print(f"❌ secrets.toml の読み込み中にエラー: {e}")
        return None

def load_app_config():
    global _CONFIG
    if _CONFIG is not None: return _CONFIG
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, 'config.toml')
        with open(config_path, "r", encoding="utf-8") as f: _CONFIG = toml.load(f)
        return _CONFIG
    except Exception as e:
        print(f"❌ config.toml の読み込み中にエラー: {e}")
        return {}

def get_db_connection():
    secrets = load_secrets()
    if not secrets or "DATABASE_URL" not in secrets: raise ValueError("DATABASE_URLがsecrets.tomlに設定されていません。")
    return psycopg2.connect(secrets["DATABASE_URL"], cursor_factory=DictCursor)

def configure_genai():
    secrets = load_secrets()
    if not secrets or "GOOGLE_API_KEY" not in secrets: raise ValueError("GOOGLE_API_KEYがsecrets.tomlに設定されていません。")
    genai.configure(api_key=secrets["GOOGLE_API_KEY"])

# --- テキスト抽出・整形関連 ---
def clean_and_format_text(text: str) -> str:
    if not text: return ""
    text_with_tabs = re.sub(r' {2,}', '\t', text)
    full_text = "\n".join([line.strip() for line in text_with_tabs.splitlines()])
    return re.sub(r'\n{3,}', '\n\n', full_text).strip()

def extract_text_from_pdf(file_bytes):
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc: raw_text = "".join(page.get_text() for page in doc)
        formatted_text = clean_and_format_text(raw_text)
        return formatted_text if formatted_text else "[PDFテキスト抽出失敗: 内容が空または画像PDF]"
    except Exception as e: return f"[PDFテキスト抽出エラー: {e}]"

def extract_text_from_docx(file_bytes):
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        raw_text = "\n".join([p.text for p in doc.paragraphs])
        formatted_text = clean_and_format_text(raw_text)
        return formatted_text if formatted_text else "[DOCXテキスト抽出失敗: 内容が空]"
    except Exception as e: return f"[DOCXテキスト抽出エラー: {e}]"

def extract_text_from_excel(file_bytes: bytes) -> str:
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        all_text_parts = [f"\n### シート: {name}\n{pd.read_excel(xls, sheet_name=name, header=None).to_string(header=False, index=False, na_rep='')}" for name in xls.sheet_names if not pd.read_excel(xls, sheet_name=name, header=None).empty]
        if not all_text_parts: return "[Excelテキスト抽出失敗: 内容が空です]"
        return clean_and_format_text("".join(all_text_parts))
    except Exception as e: return f"[Excelテキスト抽出エラー: {e}]"

def get_email_contents(msg):
    subject = str(make_header(decode_header(msg["subject"]))) if msg["subject"] else ""
    from_ = str(make_header(decode_header(msg["from"]))) if msg["from"] else ""
    received_at = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    body_text, attachments = "", []
    if msg.is_multipart():
        for part in msg.walk():
            ctype, cdisp = part.get_content_type(), str(part.get("Content-Disposition"))
            if 'text/plain' in ctype and 'attachment' not in cdisp:
                charset = part.get_content_charset()
                try: body_text += part.get_payload(decode=True).decode(charset or 'utf-8', errors='ignore')
                except: body_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
            if 'attachment' in cdisp and (fname := part.get_filename()):
                filename = str(make_header(decode_header(fname)))
                #print(f"  > 添付ファイル '{filename}' を発見しました。")
                fb, lfname = part.get_payload(decode=True), filename.lower()
                content = ""
                if lfname.endswith(".pdf"): content = extract_text_from_pdf(fb)
                elif lfname.endswith(".docx"): content = extract_text_from_docx(fb)
                elif lfname.endswith((".xlsx", ".xls")): content = extract_text_from_excel(fb)
                elif lfname.endswith(".txt"): content = fb.decode('utf-8', errors='ignore')
                else: print(f"  > ℹ️ 添付ファイル '{filename}' は未対応形式のためスキップ。")
                if content: attachments.append({"filename": filename, "content": content})
    else:
        charset = msg.get_content_charset()
        try: body_text = msg.get_payload(decode=True).decode(charset or 'utf-8', errors='ignore')
        except: body_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    return {"subject": subject, "from": from_, "received_at": received_at, "body": body_text.strip(), "attachments": attachments}

# --- LLM・DB処理関連 ---


# ▼▼▼【ここに関数を追加】▼▼▼
def extract_keywords_with_llm(text_content: str, item_type: str, count: int = 20) -> list:
    """
    AI(LLM)を使って、与えられたテキストから最も重要なスキルを「最大count個のリスト」として抽出する。
    """
    try:
        if item_type == 'job':
            instruction = f"以下の案件情報から、技術者を探す上で最も重要度が高いと思われる「必須スキル」を、重要なものから順番に最大{count}個抽出してください。"
        else: # item_type == 'engineer'
            instruction = f"以下の技術者情報から、その人のキャリアで最も核となっている「コアスキル」を、得意なものから順番に最大{count}個抽出してください。"
        
        prompt = f"""
        あなたは、与えられたテキストから最も重要な検索キーワードを抽出する専門家です。
        # 絶対的なルール:
        - 抽出するキーワードは、必ず**{count}個以内**に厳選してください。
        - 出力は、**カンマ区切りの単語リストのみ**とし、他のテキストは一切含めないでください。
        # 指示:
        {instruction}
        バージョン情報や経験年数などの付随情報は含めず、技術名や役職名などの単語のみを抽出してください。
        # 本番:
        入力テキスト: ---
        {text_content}
        ---
        出力:
        """
        
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')

        #request_options = {"timeout": 10}

        response = model.generate_content(prompt)
        
        keywords = [kw.strip().lower() for kw in response.text.strip().split(',') if kw.strip()]
        
        if not keywords:
            print("  > ⚠️ AIはキーワードを返しませんでした。")
            return []
            
        return keywords[:count]

    except Exception as e:
        print(f"  > ❌ LLMによるキーワード抽出中にエラー: {e}")
        return []
# ▲▲▲【追加ここまで】▲▲▲



def get_extraction_prompt(doc_type, text_content):
    """
    LLMに与える、情報抽出用のプロンプトを生成する。
    """
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



def _build_meta_info_string(item_type, item_data):
    meta_fields = []
    if item_type == 'job':
        meta_fields = [["国籍要件", "nationality_requirement"], ["開始時期", "start_date"], ["勤務地", "location"], ["単価", "unit_price"], ["必須スキル", "required_skills"]]
    elif item_type == 'engineer':
        meta_fields = [["国籍", "nationality"], ["稼働可能日", "availability_date"], ["希望勤務地", "desired_location"], ["希望単価", "desired_salary"], ["主要スキル", "main_skills"]]
    if not meta_fields: return "\n---\n"
    meta_parts = [f"[{display_name}: {item_data.get(key, '不明')}]" for display_name, key in meta_fields]
    return " ".join(meta_parts) + "\n---\n"

# ▼▼▼【ここが今回の修正の核となる関数】▼▼▼
def split_text_with_llm(text_content: str) -> (dict | None, list):
    logs = []
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
        logs.append("  > 📄 文書タイプを分類中...")

        #request_options = {"timeout": 10}

        response = model.generate_content(classification_prompt)
        doc_type = response.text.strip()
        logs.append(f"  > ✅ AIによる分類結果: {doc_type}")
    except Exception as e:
        logs.append(f"  > ❌ 文書の分類中にエラーが発生しました: {e}")
        return None, logs

    if "技術者情報" in doc_type:
        extraction_prompt = get_extraction_prompt('engineer', text_content)
    elif "案件情報" in doc_type:
        extraction_prompt = get_extraction_prompt('job', text_content)
    else:
        logs.append("  > ⚠️ このテキストは案件情報または技術者情報として分類されませんでした。")
        return None, logs

    generation_config = {"response_mime_type": "application/json"}
    safety_settings = {'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE', 'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'}
    
    try:
        logs.append("  > 🤖 AIが情報を構造化中...")

        #request_options = {"timeout": 20}

        response = model.generate_content(extraction_prompt, generation_config=generation_config, safety_settings=safety_settings)
        raw_text = response.text
        
        parsed_json = None
        start_index = raw_text.find('{')
        if start_index == -1:
            logs.append("  > ❌ LLM応答からJSON開始文字'{'が見つかりません。")
            return None, logs

        brace_counter, end_index = 0, -1
        for i in range(start_index, len(raw_text)):
            char = raw_text[i]
            if char == '{': brace_counter += 1
            elif char == '}': brace_counter -= 1
            if brace_counter == 0:
                end_index = i
                break
        
        if end_index == -1:
            logs.append("  > ❌ LLM応答のJSON構造が壊れています（括弧の対応が取れません）。")
            return None, logs

        json_str = raw_text[start_index : end_index + 1]
        try:
            parsed_json = json.loads(json_str)
            logs.append("  > ✅ JSONのパースに成功しました。")
        except json.JSONDecodeError as e:
            logs.append(f"  > ⚠️ JSONパース失敗。修復試行... (エラー: {e})")
            repaired_text = re.sub(r',\s*([\}\]])', r'\1', re.sub(r'(?<!\\)\n', r'\\n', json_str))
            try:
                parsed_json = json.loads(repaired_text)
                logs.append("  > ✅ JSONの修復と再パースに成功しました。")
            except json.JSONDecodeError as final_e:
                logs.append(f"  > ❌ JSON修復後もパース失敗: {final_e}")
                return None, logs

        if "技術者情報" in doc_type: parsed_json["jobs"] = []
        elif "案件情報" in doc_type: parsed_json["engineers"] = []
        return parsed_json, logs

    except Exception as e:
        logs.append(f"  > ❌ LLMによる構造化処理中に予期せぬエラーが発生しました: {e}")
        return None, logs


# run_email_processor.py 内

# ファイルの冒頭で、必要なライブラリがインポートされていることを確認
from datetime import datetime
import pytz # タイムゾーン処理に必要
import json
# ... 他の必要なimport文

def process_single_email_core(source_data: dict) -> (bool, list):
    """
    【完成版】
    単一のメールコンテンツを解析、キーワードを抽出し、DBに登録する。
    エラーハンドリングとタイムゾーン処理を強化。
    """
    logs = []
    if not source_data: 
        logs.append("⚠️ 処理するデータが空です。")
        return False, logs

    # --- 1. テキストコンテンツの準備 ---
    valid_attachments_content = [f"\n\n--- 添付ファイル: {att['filename']} ---\n{att.get('content', '')}" for att in source_data.get('attachments', []) if att.get('content')]
    if valid_attachments_content: 
        logs.append(f"  > ℹ️ {len(valid_attachments_content)}件の添付ファイル内容を解析に含めます。")
    
    full_text_for_llm = source_data.get('body', '') + "".join(valid_attachments_content)
    if not full_text_for_llm.strip(): 
        logs.append("⚠️ 解析対象のテキストがありません。")
        return False, logs

    # --- 2. AIによる情報構造化 ---
    parsed_data, llm_logs = split_text_with_llm(full_text_for_llm)
    logs.extend(llm_logs)
    if not parsed_data: 
        return False, logs
    
    new_jobs = parsed_data.get("jobs", [])
    new_engineers = parsed_data.get("engineers", [])
    if not new_jobs and not new_engineers: 
        logs.append("⚠️ LLMはテキストから案件情報または技術者情報を抽出できませんでした。")
        return False, logs
    
    # --- 3. データベースへの保存処理 ---
    logs.append("  > ✅ 抽出された情報をデータベースに保存します...")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                
                # タイムゾーンをLAに統一して、タイムゾーン付きのdatetimeオブジェクトを生成
                target_tz = pytz.timezone('America/Los_Angeles')
                now_in_la = datetime.now(target_tz)
                
                received_at_dt = source_data.get('received_at')
                # JSONとして保存するデータのために、datetimeオブジェクトをISO形式の文字列に変換
                source_json_str = json.dumps({k: v.isoformat() if isinstance(v, datetime) else v for k, v in source_data.items()}, ensure_ascii=False, indent=2)

                # --- jobs の処理 ---
                for item_data in new_jobs:
                    name = item_data.get("project_name", "名称未定の案件")
                    full_document = _build_meta_info_string('job', item_data) + (item_data.get("document") or full_text_for_llm)
                    
                    logs.append(f"    -> 案件『{name}』のキーワードを抽出中...")
                    keywords = extract_keywords_with_llm(full_document, 'job') # このファイル内に定義が必要
                    logs.append(f"    -> 抽出キーワード: {keywords}")

                    sql = """
                        INSERT INTO jobs (project_name, document, source_data_json, created_at, received_at, keywords) 
                        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                    """
                    params = (name, full_document, source_json_str, now_in_la, received_at_dt, keywords)
                    
                    try:
                        log_query = cursor.mogrify(sql, params).decode('utf-8', 'ignore')
                        logs.append(f"    -> Executing SQL: {log_query[:500]}...")
                    except Exception as log_err:
                        logs.append(f"    -> Failed to mogrify query for logging: {log_err}")
                    
                    cursor.execute(sql, params)
                    
                    result = cursor.fetchone()
                    if result:
                        logs.append(f"    -> 新規案件を登録: 『{name}』 (ID: {result['id']})")
                    else:
                        logs.append(f"    -> ⚠️ 案件『{name}』のDB登録に失敗、または既に存在します。")

                # --- engineers の処理 ---
                for item_data in new_engineers:
                    name = item_data.get("name", "名称不明の技術者")
                    full_document = _build_meta_info_string('engineer', item_data) + (item_data.get("document") or full_text_for_llm)

                    logs.append(f"    -> 技術者『{name}』のキーワードを抽出中...")
                    keywords = extract_keywords_with_llm(full_document, 'engineer') # このファイル内に定義が必要
                    logs.append(f"    -> 抽出キーワード: {keywords}")

                    sql = """
                        INSERT INTO engineers (name, document, source_data_json, created_at, received_at, keywords) 
                        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                    """
                    params = (name, full_document, source_json_str, now_in_la, received_at_dt, keywords)

                    try:
                        log_query = cursor.mogrify(sql, params).decode('utf-8', 'ignore')
                        logs.append(f"    -> Executing SQL: {log_query[:500]}...")
                    except Exception as log_err:
                        logs.append(f"    -> Failed to mogrify query for logging: {log_err}")

                    cursor.execute(sql, params)

                    result = cursor.fetchone()
                    if result:
                        logs.append(f"    -> 新規技術者を登録: 『{name}』 (ID: {result['id']})")
                    else:
                        logs.append(f"    -> ⚠️ 技術者『{name}』のDB登録に失敗、または既に存在します。")
                
            conn.commit()
    except Exception as e:
        logs.append(f"❌ DB保存中にエラーが発生: {e}")
        import traceback
        logs.append(traceback.format_exc())
        return False, logs
        
    logs.append("  > ✅ 保存完了！")
    return True, logs



# ==============================================================================
# 2. バッチ処理のメインロジック
# ==============================================================================

def fetch_and_process_emails_batch():
    mail = None
    try:
        secrets, config = load_secrets(), load_app_config()
        if not secrets: return
        configure_genai()
        FETCH_LIMIT = config.get("email_processing", {}).get("fetch_limit", 10)
        SERVER, USER, PASSWORD = secrets.get("EMAIL_SERVER"), secrets.get("EMAIL_USER"), secrets.get("EMAIL_PASSWORD")
        if not all([SERVER, USER, PASSWORD]):
            print("❌ メールサーバーの接続情報が secrets.toml に設定されていません。")
            return
        
        try:
            mail = imaplib.IMAP4_SSL(SERVER)
            mail.login(USER, PASSWORD)
            mail.select('inbox')
            print("✅ メールサーバーへの接続完了")
        except Exception as e:
            print(f"❌ メールサーバーへの接続またはログインに失敗: {e}")
            return

        _, messages = mail.search(None, 'UNSEEN')
        email_ids = messages[0].split()
        
        if not email_ids:
            print("ℹ️ 処理対象の未読メールは見つかりませんでした。")
        else:
            latest_ids = email_ids[::-1][:FETCH_LIMIT]
            checked_count, total_processed_count = len(latest_ids), 0
            print(f"ℹ️ 最新の未読メール {checked_count}件をチェックします。（設定上限: {FETCH_LIMIT}件）")

            for i, email_id in enumerate(latest_ids):
                print(f"\n--- ({i+1}/{checked_count}) メールID {email_id.decode()} を処理中 ---")
                _, msg_data = mail.fetch(email_id, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        source_data = get_email_contents(msg)
                        success, logs = process_single_email_core(source_data)
                        for log_line in logs: print(log_line)
                        if success:
                            total_processed_count += 1
                            mail.store(email_id, '+FLAGS', '\\Seen')
            
            print(f"\n--- チェック完了 ---")
            print(f"▶︎ 処理済みメール: {total_processed_count}件 / チェックしたメール: {checked_count}件")

    except Exception as e:
        print(f"❌ メール処理全体で予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        if mail and mail.state == 'SELECTED':
            mail.close()
            mail.logout()
            print("ℹ️ メールサーバーから切断しました。")

# ==============================================================================
# 3. スクリプトのエントリーポイント
# ==============================================================================

def main():
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"--- [ {start_time} ] 定期メール処理を開始します ---")
    fetch_and_process_emails_batch()
    end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"--- [ {end_time} ] 処理が正常に完了しました ---")

if __name__ == "__main__":
    main()
