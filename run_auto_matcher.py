# run_auto_matcher.py (情報埋め込み・最終完成版)

import sys
import os
import psycopg2
from psycopg2.extras import DictCursor
import json
from datetime import datetime
import time

# プロジェクトルートをパスに追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

import backend as be

# --- 設定項目 ---
# Streamlit CloudのURLなど、デプロイ先のベースURLを設定
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8501")
# 一度に処理する新規レコードの数
BATCH_SIZE = 100

# --- バッチ処理専用のヘルパー関数 ---

def get_batch_db_connection():
    """ バッチ処理専用のDB接続関数（接続情報を直接記述） """
    # !! 注意: この方法はセキュリティリスクを伴います !!
    # このスクリプトが非公開の環境で実行されることを前提としています。
    # .streamlit/secrets.toml から完全な接続URLをコピー＆ペーストしてください。
    DATABASE_URL = "postgresql://postgres.skyavwbqgjkhaenjxgul:TDSN+DF-H#6&R&a@aws-1-us-east-1.pooler.supabase.com:6543/postgres"

    if "[YOUR_PASSWORD]" in DATABASE_URL:
        print("CRITICAL: DATABASE_URL is not configured in the script. Please paste the full connection string.")
        return None
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
    except Exception as e:
        print(f"CRITICAL: Database connection failed: {e}")
        return None

def get_latest_max_ids(conn):
    """ jobsとengineersテーブルの最新IDを取得する """
    max_job_id, max_engineer_id = 0, 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(id) FROM jobs")
            max_job_id = (res := cur.fetchone()) and res['max'] or 0
            cur.execute("SELECT MAX(id) FROM engineers")
            max_engineer_id = (res := cur.fetchone()) and res['max'] or 0
    except Exception as e:
        print(f"Error fetching max IDs: {e}")
    return max_job_id, max_engineer_id

# --- メイン処理 ---

def main():
    print(f"--- Auto-matcher batch started at {datetime.now()} ---")
    
    # 1. アクティブな自動マッチング依頼を取得
    conn = get_batch_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM auto_matching_requests WHERE is_active = TRUE")
            requests = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

    if not requests:
        print("No active auto-matching requests. Exiting.")
        return

    # 2. 今回処理すべき最新IDの最大値を取得
    conn = get_batch_db_connection()
    if not conn: return
    try:
        max_job_id, max_engineer_id = get_latest_max_ids(conn)
    finally:
        conn.close()

    # 3. 各依頼に対して差分マッチングを実行
    for req in requests:
        req_id, item_id, item_type = req['id'], req['item_id'], req['item_type']
        target_rank, email = req['target_rank'], req['notification_email']
        
        rank_order = ['S', 'A', 'B', 'C', 'D']
        valid_ranks = rank_order[:rank_order.index(target_rank) + 1]

        # --- 依頼が「案件」の場合 -> 未処理の「技術者」とマッチング ---
        if item_type == 'job':
            last_processed_id = req.get('last_processed_engineer_id') or 0
            if last_processed_id >= max_engineer_id:
                print(f"Request for Job ID {item_id}: No new engineers to process.")
                continue

            print(f"\nProcessing request for Job ID {item_id} against new engineers (ID > {last_processed_id})")
            job_data = be.get_items_by_ids_sync('jobs', [item_id])[0]
            if not job_data: continue
            
            offset = 0
            while True:
                conn = get_batch_db_connection()
                if not conn: break
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT * FROM engineers WHERE id > %s ORDER BY id ASC LIMIT %s OFFSET %s", (last_processed_id, BATCH_SIZE, offset))
                        new_engineers_batch = cur.fetchall()
                finally:
                    conn.close()

                if not new_engineers_batch: break
                print(f"  - Evaluating batch of {len(new_engineers_batch)} engineers (offset: {offset})")

                for engineer in new_engineers_batch:
                    llm_result = be.get_match_summary_with_llm(job_data['document'], engineer['document'])
                    if llm_result and llm_result.get('summary') in valid_ranks:
                        grade = llm_result.get('summary')
                        match_id = be.create_or_update_match_record(job_data['id'], engineer['id'], 0.0, grade, llm_result)
                        if match_id:
                            print(f"    HIT! Job({item_id}) vs Eng({engineer['id']}) -> Rank {grade}. Match ID: {match_id}")
                            subject = f"[AIマッチング] 案件「{job_data['project_name']}」に新規候補者"
                            match_url = f"{APP_BASE_URL}/マッチング詳細?result_id={match_id}"
                            job_url = f"{APP_BASE_URL}/案件詳細?id={job_data['id']}"
                            eng_url = f"{APP_BASE_URL}/技術者詳細?id={engineer['id']}"
                            body = f"自動マッチング依頼中の案件に、新しい候補者が見つかりました。\n\n■ 案件: {job_data['project_name']}\n   {job_url}\n\n■ 新規候補者: {engineer['name']}\n   {eng_url}\n\n■ AI評価: ランク {grade}\n\n▼▼ マッチング詳細はこちら ▼▼\n{match_url}"
                            be.send_email_notification(email, subject, body)
                
                offset += BATCH_SIZE
                time.sleep(0.5)

        # --- 依頼が「技術者」の場合 -> 未処理の「案件」とマッチング ---
        elif item_type == 'engineer':
            last_processed_id = req.get('last_processed_job_id') or 0
            if last_processed_id >= max_job_id:
                print(f"Request for Engineer ID {item_id}: No new jobs to process.")
                continue

            print(f"\nProcessing request for Engineer ID {item_id} against new jobs (ID > {last_processed_id})")
            engineer_data = be.get_items_by_ids_sync('engineers', [item_id])[0]
            if not engineer_data: continue

            offset = 0
            while True:
                conn = get_batch_db_connection()
                if not conn: break
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT * FROM jobs WHERE id > %s ORDER BY id ASC LIMIT %s OFFSET %s", (last_processed_id, BATCH_SIZE, offset))
                        new_jobs_batch = cur.fetchall()
                finally:
                    conn.close()

                if not new_jobs_batch: break
                print(f"  - Evaluating batch of {len(new_jobs_batch)} jobs (offset: {offset})")

                for job in new_jobs_batch:
                    llm_result = be.get_match_summary_with_llm(job['document'], engineer_data['document'])
                    if llm_result and llm_result.get('summary') in valid_ranks:
                        grade = llm_result.get('summary')
                        match_id = be.create_or_update_match_record(job['id'], engineer_data['id'], 0.0, grade, llm_result)
                        if match_id:
                            print(f"    HIT! Eng({item_id}) vs Job({job['id']}) -> Rank {grade}. Match ID: {match_id}")
                            subject = f"[AIマッチング] 技術者「{engineer_data['name']}」に新規案件"
                            match_url = f"{APP_BASE_URL}/マッチング詳細?result_id={match_id}"
                            eng_url = f"{APP_BASE_URL}/技術者詳細?id={engineer_data['id']}"
                            job_url = f"{APP_BASE_URL}/案件詳細?id={job['id']}"
                            body = f"自動マッチング依頼中の技術者に、新しい案件が見つかりました。\n\n■ 技術者: {engineer_data['name']}\n   {eng_url}\n\n■ 新規案件: {job['project_name']}\n   {job_url}\n\n■ AI評価: ランク {grade}\n\n▼▼ マッチング詳細はこちら ▼▼\n{match_url}"
                            be.send_email_notification(email, subject, body)
                
                offset += BATCH_SIZE
                time.sleep(0.5)

        # 4. 最後に処理したIDを更新
        be.update_auto_match_last_processed_ids(req_id, max_job_id, max_engineer_id)
        print(f"Updated last processed IDs for request {req_id}.")

    print(f"--- Auto-matcher batch finished at {datetime.now()} ---")

if __name__ == "__main__":
    main()
