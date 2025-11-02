# run_auto_matcher.py (機密情報埋め込み・最終完成版)

import os
import sys
import psycopg2
from psycopg2.extras import DictCursor
import json
from datetime import datetime
import time
from urllib.parse import quote
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import google.generativeai as genai
import re

# --- グローバル設定 ---
# Streamlit CloudのURLなど、デプロイ先のベースURLをここに記述
APP_BASE_URL = "https://tom2552tom-universal-ai-matching-system-1--tiqfde.streamlit.app"
# 一度にDBから取得・処理する新規レコードの数
BATCH_SIZE = 100

# ==============================================================================
# ▼▼▼ このスクリプト専用のヘルパー関数群 (backend.py を参照しない) ▼▼▼
# ==============================================================================

def initialize_and_get_config():
    """バッチ実行に必要なAPIキーとDB接続情報を設定・取得する。"""
    config = {}
    try:
        # 1. Google APIキー
        GOOGLE_API_KEY = "AIzaSyA4Vv_MWpMZ-2y8xGslYQJ9yvcBY9Pc-VA"
        genai.configure(api_key=GOOGLE_API_KEY)
        print("INFO: Google Generative AI API configured for batch process.")

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
        return config
    except Exception as e:
        print(f"CRITICAL: Failed during initialization: {e}")
        return None

def get_batch_db_connection(db_url):
    """設定されたURLを使ってDBに接続する"""
    try:
        return psycopg2.connect(db_url, cursor_factory=DictCursor)
    except Exception as e:
        print(f"CRITICAL: Database connection failed: {e}")
        return None

def get_items_by_ids_batch(item_type, ids, conn):
    """バッチ専用の get_items_by_ids_sync"""
    if not ids or item_type not in ['jobs', 'engineers']: return []
    table_name = 'jobs' if item_type == 'jobs' else 'engineers'
    query = f"SELECT * FROM {table_name} WHERE id = ANY(%s)"
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, (ids,))
            results = cursor.fetchall()
            results_map = {res['id']: res for res in results}
            return [dict(results_map[id]) for id in ids if id in results_map]
    except Exception as e:
        print(f"Error in get_items_by_ids_batch: {e}")
        return []

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
        raw_text = response.text
        start_index = raw_text.find('{')
        if start_index == -1: return None
        brace_counter, end_index = 0, -1
        for i in range(start_index, len(raw_text)):
            if raw_text[i] == '{': brace_counter += 1
            elif raw_text[i] == '}': brace_counter -= 1
            if brace_counter == 0: end_index = i; break
        if end_index == -1: return None
        json_str = raw_text[start_index : end_index + 1]
        try: return json.loads(json_str)
        except json.JSONDecodeError:
            repaired_str = re.sub(r',\s*([\}\]])', r'\1', json_str)
            return json.loads(repaired_str)
    except Exception as e:
        print(f"Error in get_match_summary_batch: {e}"); return None

def create_or_update_match_record_batch(job_id, engineer_id, grade, llm_result, conn):
    """バッチ専用の create_or_update_match_record"""
    positive_points = json.dumps(llm_result.get('positive_points', []), ensure_ascii=False)
    concern_points = json.dumps(llm_result.get('concern_points', []), ensure_ascii=False)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sql = """
        INSERT INTO matching_results (job_id, engineer_id, score, created_at, grade, positive_points, concern_points, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, '新規') ON CONFLICT (job_id, engineer_id) DO UPDATE SET
        score = EXCLUDED.score, grade = EXCLUDED.grade, positive_points = EXCLUDED.positive_points,
        concern_points = EXCLUDED.concern_points, created_at = EXCLUDED.created_at, status = '新規'
        RETURNING id;"""
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (job_id, engineer_id, 0.0, now_str, grade, positive_points, concern_points))
            result = cur.fetchone()
        conn.commit()
        return result['id'] if result else None
    except Exception as e: print(f"Error in create_or_update_match_record_batch: {e}"); conn.rollback(); return None

def update_last_processed_ids_batch(request_id, last_job_id, last_engineer_id, conn):
    """バッチ専用の update_auto_match_last_processed_ids"""
    updates, params = [], []
    if last_job_id: updates.append("last_processed_job_id = %s"); params.append(last_job_id)
    if last_engineer_id: updates.append("last_processed_engineer_id = %s"); params.append(last_engineer_id)
    if not updates: return True
    params.append(request_id)
    sql = f"UPDATE auto_matching_requests SET {', '.join(updates)} WHERE id = %s"
    try:
        with conn.cursor() as cur: cur.execute(sql, tuple(params))
        conn.commit(); return True
    except Exception as e: print(f"Error in update_last_processed_ids_batch: {e}"); conn.rollback(); return False

def send_email_notification_batch(smtp_config, recipient, subject, body):
    """バッチ専用の send_email_notification"""
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = smtp_config["from_email"]
        msg['To'] = recipient
        with smtplib.SMTP(smtp_config["server"], smtp_config["port"]) as server:
            server.starttls(); server.login(smtp_config["user"], smtp_config["password"]); server.send_message(msg)
        print(f"✅ Notification email sent to {recipient}")
        return True
    except Exception as e: print(f"❌ Email sending failed: {e}"); return False

# --- メイン処理 ---
def main():
    print(f"--- Auto-matcher batch started at {datetime.now()} ---")
    config = initialize_and_get_config()
    if not config: return

    conn = get_batch_db_connection(config["DATABASE_URL"])
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM auto_matching_requests WHERE is_active = TRUE")
            requests = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT MAX(id) FROM jobs")
            max_job_id = (res := cur.fetchone()) and res['max'] or 0
            cur.execute("SELECT MAX(id) FROM engineers")
            max_engineer_id = (res := cur.fetchone()) and res['max'] or 0
    finally: conn.close()
    if not requests: print("No active auto-matching requests. Exiting."); return

    PATH_MATCH, PATH_JOB, PATH_ENGINEER = quote("マッチング詳細"), quote("案件詳細"), quote("技術者詳細")

    for req in requests:
        req_id, item_id, item_type, target_rank, email = req['id'], req['item_id'], req['item_type'], req['target_rank'], req['notification_email']
        rank_order = ['S', 'A', 'B', 'C', 'D']; valid_ranks = rank_order[:rank_order.index(target_rank) + 1]

        if item_type == 'job':
            last_processed_id = req.get('last_processed_engineer_id') or 0
            if last_processed_id >= max_engineer_id: print(f"Request for Job ID {item_id}: No new engineers to process."); continue
            print(f"\nProcessing request for Job ID {item_id} against new engineers (ID > {last_processed_id})")
            
            conn = get_batch_db_connection(config["DATABASE_URL"]);
            if not conn: continue
            try:
                job_data_list = get_items_by_ids_batch('jobs', [item_id], conn)
                if not job_data_list: print(f"  - Could not find job data for ID: {item_id}. Skipping."); continue
                job_data = job_data_list[0]
                offset = 0
                while True:
                    with conn.cursor() as cur:
                        cur.execute("SELECT * FROM engineers WHERE id > %s ORDER BY id ASC LIMIT %s OFFSET %s", (last_processed_id, BATCH_SIZE, offset))
                        new_items_batch = cur.fetchall()
                    if not new_items_batch: break
                    print(f"  - Evaluating batch of {len(new_items_batch)} engineers (offset: {offset})")
                    for engineer in new_items_batch:
                        llm_result = get_match_summary_batch(job_data['document'], engineer['document'])
                        if llm_result and llm_result.get('summary') in valid_ranks:
                            grade = llm_result.get('summary')
                            match_id = create_or_update_match_record_batch(job_data['id'], engineer['id'], grade, llm_result, conn)
                            if match_id:
                                print(f"    HIT! Job({item_id}) vs Eng({engineer['id']}) -> Rank {grade}. Match ID: {match_id}")
                                subject = f"[AIマッチング] 案件「{job_data['project_name']}」に新規候補者"
                                
                                #body = f"自動マッチング依頼中の案件に、新しい候補者が見つかりました。\n\n■ 案件: {job_data['project_name']}\n   <{APP_BASE_URL}/{PATH_JOB}?id={job_data['id']}>\n\n■ 新規候補者: {engineer['name']}\n   <{APP_BASE_URL}/{PATH_ENGINEER}?id={engineer['id']}>\n\n■ AI評価: ランク {grade}\n\n▼▼ マッチング詳細はこちら ▼▼\n<{APP_BASE_URL}/{PATH_MATCH}?result_id={match_id}>"
                                # ★★★【ここからが修正の核】★★★
                                # URLを囲っていた山括弧 <> を削除
                                #subject = f"[AIマッチング] 案件「{job_data['project_name']}」に新規候補者"
                        
                                match_url = f"{APP_BASE_URL}/{PATH_MATCH}?result_id={match_id}"
                                job_url = f"{APP_BASE_URL}/{PATH_JOB}?id={job_data['id']}"
                                eng_url = f"{APP_BASE_URL}/{PATH_ENGINEER}?id={engineer['id']}"
                                
                                
                                body = f"""
自動マッチング依頼中の案件に、新しい候補者が見つかりました。

■ 案件: {job_data['project_name']}
{job_url}

■ 新規候補者: {engineer['name']}
{eng_url}

■ AI評価: ランク {grade}
▼▼ マッチング詳細はこちら ▼▼
{match_url}
"""
                                
                                send_email_notification_batch(config["SMTP"], email, subject, body)
                    offset += BATCH_SIZE; time.sleep(0.5)
            finally: conn.close()

        elif item_type == 'engineer':
            last_processed_id = req.get('last_processed_job_id') or 0
            if last_processed_id >= max_job_id: print(f"Request for Engineer ID {item_id}: No new jobs to process."); continue
            print(f"\nProcessing request for Engineer ID {item_id} against new jobs (ID > {last_processed_id})")
            
            conn = get_batch_db_connection(config["DATABASE_URL"]);
            if not conn: continue
            try:
                engineer_data_list = get_items_by_ids_batch('engineers', [item_id], conn)
                if not engineer_data_list: print(f"  - Could not find engineer data for ID: {item_id}. Skipping."); continue
                engineer_data = engineer_data_list[0]
                offset = 0
                while True:
                    with conn.cursor() as cur:
                        cur.execute("SELECT * FROM jobs WHERE id > %s ORDER BY id ASC LIMIT %s OFFSET %s", (last_processed_id, BATCH_SIZE, offset))
                        new_items_batch = cur.fetchall()
                    if not new_items_batch: break
                    print(f"  - Evaluating batch of {len(new_items_batch)} jobs (offset: {offset})")
                    for job in new_items_batch:
                        llm_result = get_match_summary_batch(job['document'], engineer_data['document'])
                        if llm_result and llm_result.get('summary') in valid_ranks:
                            grade = llm_result.get('summary')
                            match_id = create_or_update_match_record_batch(job['id'], engineer_data['id'], grade, llm_result, conn)
                            if match_id:
                                print(f"    HIT! Eng({item_id}) vs Job({job['id']}) -> Rank {grade}. Match ID: {match_id}")
                                subject = f"[AIマッチング] 技術者「{engineer_data['name']}」に新規案件"
                                #body = f"自動マッチング依頼中の技術者に、新しい案件が見つかりました。\n\n■ 技術者: {engineer_data['name']}\n   <{APP_BASE_URL}/{PATH_ENGINEER}?id={engineer_data['id']}>\n\n■ 新規案件: {job['project_name']}\n   <{APP_BASE_URL}/{PATH_JOB}?id={job['id']}>\n\n■ AI評価: ランク {grade}\n\n▼▼ マッチング詳細はこちら ▼▼\n<{APP_BASE_URL}/{PATH_MATCH}?result_id={match_id}>"
                                
                                match_url = f"{APP_BASE_URL}/{PATH_MATCH}?result_id={match_id}"
                                eng_url = f"{APP_BASE_URL}/{PATH_ENGINEER}?id={engineer_data['id']}"
                                job_url = f"{APP_BASE_URL}/{PATH_JOB}?id={job['id']}"

                                # ★★★ こちらも同様に修正 ★★★
                                body = f"""
自動マッチング依頼中の技術者に、新しい案件が見つかりました。

■ 技術者: {engineer_data['name']}
{eng_url}

■ 新規案件: {job['project_name']}
{job_url}

■ AI評価: ランク {grade}
▼▼ マッチング詳細はこちら ▼▼
{match_url}
"""
                                
                                send_email_notification_batch(config["SMTP"], email, subject, body)
                    offset += BATCH_SIZE; time.sleep(0.5)
            finally: conn.close()
            
        conn = get_batch_db_connection(config["DATABASE_URL"])
        if not conn: continue
        try:
            update_last_processed_ids_batch(req_id, max_job_id, max_engineer_id, conn)
            print(f"Updated last processed IDs for request {req_id}.")
        finally: conn.close()

    print(f"--- Auto-matcher batch finished at {datetime.now()} ---")

if __name__ == "__main__":
    main()
