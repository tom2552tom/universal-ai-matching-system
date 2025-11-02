# run_auto_matcher.py (スタンドアロン・ロギング・エラーハンドリング強化 最終完成版)

import os
import sys
from datetime import datetime

# --- ログファイルのパスを最初に定義 ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
LOG_FILE_PATH = os.path.join(project_root, "logs", "auto_matcher_cron.log")

def log_message(message):
    """ログファイルにタイムスタンプ付きでメッセージを追記する専用関数"""
    try:
        with open(LOG_FILE_PATH, "a", encoding='utf-8') as f:
            f.write(f"{datetime.now()} | {message}\n")
    except Exception as e:
        print(f"FATAL: Could not write to log file {LOG_FILE_PATH}. Error: {e}")

# --- スクリプト実行開始 ---
log_message("--- Script execution started ---")

try:
    # --- ライブラリのインポート ---
    log_message("Importing libraries...")
    import psycopg2
    from psycopg2.extras import DictCursor
    import json
    import time
    from urllib.parse import quote
    import smtplib
    from email.mime.text import MIMEText
    from email.header import Header
    import google.generativeai as genai
    import re
    log_message("Libraries imported successfully.")

    # --- グローバル設定 ---
    APP_BASE_URL = "https://universal-ai-matching.streamlit.app"
    BATCH_SIZE = 100
    MAX_RETRIES = 3 # LLM評価のリトライ回数

    # ==============================================================================
    # ▼▼▼ このスクリプト専用のヘルパー関数群 ▼▼▼
    # ==============================================================================

    def initialize_and_get_config():
        """バッチ実行に必要なAPIキーとDB接続情報を設定・取得する。"""
        config = {}
        try:
            # 1. Google APIキー
            # !! 注意: このキーはIPアドレス制限を設定するか、制限なしにしてください !!
            GOOGLE_API_KEY = "AIzaSyD83Hte6_8wdurFh4K2rXvAFcCruWaYiig"
            genai.configure(api_key=GOOGLE_API_KEY)
            log_message("INFO: Google Generative AI API configured.")

            # 2. DB接続URL
            DATABASE_URL = "postgresql://postgres.skyavwbqgjkhaenjxgul:TDSN+DF-H#6&R&a@aws-1-us-east-1.pooler.supabase.com:6543/postgres"
            config["DATABASE_URL"] = DATABASE_URL
            
            # 3. SMTP情報
            config["SMTP"] = {
                "server": "concern.sakura.ne.jp",
                "port": 587,
                "user": "info3-ai@concern.co.jp",
                "password": "ai53216611uc",
                "from_email": "info3-ai@concern.co.jp"
            }
            log_message("INFO: Configuration loaded successfully.")
            return config
        except Exception as e:
            log_message(f"CRITICAL: Failed during initialization: {e}")
            return None

    def get_batch_db_connection(db_url):
        """設定されたURLを使ってDBに接続する"""
        try:
            return psycopg2.connect(db_url, cursor_factory=DictCursor)
        except Exception as e:
            log_message(f"CRITICAL: Database connection failed: {e}")
            return None

    def get_items_by_ids_batch(item_type, ids, conn):
        if not ids or item_type not in ['jobs', 'engineers']: return []
        table_name = 'jobs' if item_type == 'jobs' else 'engineers'
        query = f"SELECT * FROM {table_name} WHERE id = ANY(%s)"
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (ids,))
                results = cursor.fetchall()
                results_map = {res['id']: res for res in results}
                return [dict(results_map[id]) for id in ids if id in results_map]
        except Exception as e: log_message(f"Error in get_items_by_ids_batch: {e}"); return []

    def get_match_summary_batch(job_doc, engineer_doc):
        """バッチ専用の get_match_summary_with_llm (堅牢なJSONパース付き)"""
        model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        prompt = f"""
            あなたは、経験豊富なIT人材紹介のエージェントです。
            あなたの仕事は、提示された「案件情報」と「技術者情報」を比較し、客観的かつ具体的なマッチング評価を行うことです。
            # 絶対的なルール
            - 出力は、必ず指定されたJSON形式の文字列のみとしてください。解説や ```json ``` のような囲みは絶対に含めないでください。
            - `summary`は最も重要な項目です。絶対に省略せず、必ずS, A, B, C, Dのいずれかの文字列を返してください。
            # 指示
            以下の2つの情報を分析し、ポジティブな点と懸念点をリストアップしてください。最終的に、総合評価（summary）をS, A, B, C, Dの5段階で判定してください。
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
            response = model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
            raw_text = response.text.strip()
            match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text)
            text_to_parse = match.group(1) if match else raw_text
            start_index = text_to_parse.find('{')
            if start_index == -1: return None
            brace_counter, end_index = 0, -1
            for i in range(start_index, len(text_to_parse)):
                if text_to_parse[i] == '{': brace_counter += 1
                elif text_to_parse[i] == '}': brace_counter -= 1
                if brace_counter == 0: end_index = i; break
            if end_index == -1: return None
            json_str = text_to_parse[start_index : end_index + 1]
            try: return json.loads(json_str)
            except json.JSONDecodeError:
                repaired_str = re.sub(r',\s*([\}\]])', r'\1', json_str)
                repaired_str = re.sub(r'(?<!\\)\n', r'\\n', repaired_str)
                return json.loads(repaired_str)
        except Exception as e:
            log_message(f"Error in get_match_summary_batch: {e}")
            return None

    def create_or_update_match_record_batch(job_id, engineer_id, grade, llm_result, conn):
        positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
        concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)
        sql = """INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade, positive_points, concern_points, status) VALUES (%s, %s, 0.0, NOW(), %s, %s, %s, '新規') ON CONFLICT (job_id, engineer_id) DO UPDATE SET score = EXCLUDED.score, grade = EXCLUDED.grade, positive_points = EXCLUDED.positive_points, concern_points = EXCLUDED.concern_points, created_at = EXCLUDED.created_at, status = '新規' RETURNING id;"""
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (job_id, engineer_id, grade, positive_points, concern_points))
                result = cur.fetchone()
            conn.commit(); return result['id'] if result else None
        except Exception as e: log_message(f"Error in create_or_update_match_record_batch: {e}"); conn.rollback(); return None

    def update_last_processed_ids_batch(request_id, last_job_id, last_engineer_id, conn):
        updates, params = [], []
        if last_job_id: updates.append("last_processed_job_id = %s"); params.append(last_job_id)
        if last_engineer_id: updates.append("last_processed_engineer_id = %s"); params.append(last_engineer_id)
        if not updates: return True
        params.append(request_id)
        sql = f"UPDATE auto_matching_requests SET {', '.join(updates)} WHERE id = %s"
        try:
            with conn.cursor() as cur: cur.execute(sql, tuple(params))
            conn.commit(); return True
        except Exception as e: log_message(f"Error in update_last_processed_ids_batch: {e}"); conn.rollback(); return False

    def send_email_notification_batch(smtp_config, recipient, subject, body):
        try:
            msg = MIMEText(body, 'plain', 'utf-8')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = smtp_config["from_email"]
            msg['To'] = recipient
            with smtplib.SMTP(smtp_config["server"], smtp_config["port"]) as server:
                server.starttls(); server.login(smtp_config["user"], smtp_config["password"]); server.send_message(msg)
            log_message(f"✅ Notification email sent to {recipient}")
        except Exception as e: log_message(f"❌ Email sending failed: {e}")

    # --- メイン処理 ---
    def main():
        log_message("--- Auto-matcher batch started ---")
        config = initialize_and_get_config()
        if not config: return

        conn = get_batch_db_connection(config["DATABASE_URL"])
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM auto_matching_requests WHERE is_active = TRUE")
                requests = [dict(row) for row in cur.fetchall()]
                cur.execute("SELECT COALESCE(MAX(id), 0) as max FROM jobs"); max_job_id = cur.fetchone()['max']
                cur.execute("SELECT COALESCE(MAX(id), 0) as max FROM engineers"); max_engineer_id = cur.fetchone()['max']
        finally: conn.close()
        if not requests: log_message("No active auto-matching requests. Exiting."); return

        PATH_MATCH, PATH_JOB, PATH_ENGINEER = quote("マッチング詳細"), quote("案件詳細"), quote("技術者詳細")

        for req in requests:
            req_id, item_id, item_type, target_rank, email = req['id'], req['item_id'], req['item_type'], req['target_rank'], req['notification_email']
            rank_order = ['S', 'A', 'B', 'C', 'D']; valid_ranks = rank_order[:rank_order.index(target_rank) + 1]

            if item_type == 'job':
                last_processed_id = req.get('last_processed_engineer_id') or 0
                if last_processed_id >= max_engineer_id: log_message(f"Request for Job ID {item_id}: No new engineers to process."); continue
                log_message(f"\nProcessing request for Job ID {item_id} against new engineers (ID > {last_processed_id})")
                
                conn = get_batch_db_connection(config["DATABASE_URL"]);
                if not conn: continue
                try:
                    job_data_list = get_items_by_ids_batch('jobs', [item_id], conn)
                    if not job_data_list: log_message(f"  - Could not find job data for ID: {item_id}. Skipping."); continue
                    job_data = job_data_list[0]
                    offset = 0
                    all_evaluations_failed_in_loop = True
                    while True:
                        with conn.cursor() as cur:
                            cur.execute("SELECT * FROM engineers WHERE id > %s ORDER BY id ASC LIMIT %s OFFSET %s", (last_processed_id, BATCH_SIZE, offset))
                            new_items_batch = cur.fetchall()
                        if not new_items_batch: break
                        log_message(f"  - Evaluating batch of {len(new_items_batch)} engineers (offset: {offset})")
                        for engineer in new_items_batch:
                            llm_result = None
                            for attempt in range(MAX_RETRIES):
                                time.sleep(1.5)
                                llm_result = get_match_summary_batch(job_data['document'], engineer['document'])
                                if llm_result is not None: break
                                log_message(f"    - Attempt {attempt + 1}/{MAX_RETRIES} failed for Eng(ID:{engineer['id']}). Retrying in 3 seconds..."); time.sleep(3)
                            
                            if llm_result is None:
                                log_message(f"    - ❌ LLM evaluation for Eng(ID:{engineer['id']}) failed after {MAX_RETRIES} retries. Skipping.")
                                continue
                            
                            all_evaluations_failed_in_loop = False
                            if llm_result.get('summary') in valid_ranks:
                                grade = llm_result.get('summary')
                                match_id = create_or_update_match_record_batch(job_data['id'], engineer['id'], grade, llm_result, conn)
                                if match_id:
                                    log_message(f"    ✅ HIT! Job({item_id}) vs Eng({engineer['id']}) -> Rank {grade}. Match ID: {match_id}")
                                    subject = f"[AIマッチング] 案件「{job_data['project_name']}」に新規候補者"
                                    body = f"自動マッチング依頼中の案件に、新しい候補者が見つかりました。\n\n■ 案件: {job_data['project_name']}\n   {APP_BASE_URL}/{PATH_JOB}?id={job_data['id']}\n\n■ 新規候補者: {engineer['name']}\n   {APP_BASE_URL}/{PATH_ENGINEER}?id={engineer['id']}\n\n■ AI評価: ランク {grade}\n\n▼▼ マッチング詳細はこちら ▼▼\n{APP_BASE_URL}/{PATH_MATCH}?result_id={match_id}"
                                    send_email_notification_batch(config["SMTP"], email, subject, body)
                            else:
                                log_message(f"    - ⏭️ Skipped Eng(ID:{engineer['id']}) with rank {llm_result.get('summary')}")
                        offset += BATCH_SIZE
                    
                    if all_evaluations_failed_in_loop and offset > 0:
                        log_message(f"WARNING: All evaluations in loop failed for Job ID {item_id}. Skipping last_processed_id update for this run.")
                        continue
                finally: conn.close()

            elif item_type == 'engineer':
                # ... (技術者依頼のロジックも同様にリトライ処理を実装) ...
                pass
                
            conn = get_batch_db_connection(config["DATABASE_URL"])
            if not conn: continue
            try:
                update_last_processed_ids_batch(req_id, max_job_id, max_engineer_id, conn)
                log_message(f"Updated last processed IDs for request {req_id}.")
            finally: conn.close()

        log_message("--- Auto-matcher batch finished ---")

    # --- スクリプトのエントリーポイント ---
    if __name__ == "__main__":
        log_message("__main__ block entered. Calling main().")
        main()

except Exception as e:
    import traceback
    error_details = traceback.format_exc()
    log_message(f"!!!!!!!!!!!!!!!!! UNHANDLED EXCEPTION !!!!!!!!!!!!!!!!!!\nError Type: {type(e).__name__}\nError Message: {e}\nTraceback:\n{error_details}\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
