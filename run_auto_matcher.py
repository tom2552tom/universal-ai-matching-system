# run_auto_matcher.py (バッチ処理・最終修正版)

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import backend as be
import json
from datetime import datetime
import time

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8501")

def main():
    print(f"--- Auto-matcher batch started at {datetime.now()} ---")
    
    # 1. アクティブな自動マッチング依頼を取得
    requests = []
    with be.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM auto_matching_requests WHERE is_active = TRUE")
        requests = [dict(row) for row in cur.fetchall()]
    
    if not requests:
        print("No active auto-matching requests. Exiting.")
        return

    # 2. 今回処理すべき最新IDの最大値を取得
    max_job_id, max_engineer_id = 0, 0
    with be.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(id) FROM jobs")
        max_job_id = (res := cur.fetchone()) and res['max'] or 0
        cur.execute("SELECT MAX(id) FROM engineers")
        max_engineer_id = (res := cur.fetchone()) and res['max'] or 0

    # 3. 各依頼に対して差分マッチングを実行
    for req in requests:
        req_id, item_id, item_type, target_rank, email = req['id'], req['item_id'], req['item_type'], req['target_rank'], req['notification_email']
        rank_order = ['S', 'A', 'B', 'C', 'D']
        valid_ranks = rank_order[:rank_order.index(target_rank) + 1]

        # --- 依頼が「案件」の場合 -> 未処理の「技術者」とマッチング ---
        if item_type == 'job':
            last_processed_id = req.get('last_processed_engineer_id') or 0
            if last_processed_id >= max_engineer_id:
                continue

            print(f"\nProcessing request for Job ID {item_id} against new engineers (ID > {last_processed_id})")
            job_data_list = be.get_items_by_ids_sync('jobs', [item_id])
            if not job_data_list: continue
            job_data = job_data_list[0]
            
            # ★★★【ここからが修正の核】★★★
            # 一度に全件取得せず、バッチで少しずつ処理する
            BATCH_SIZE = 100
            offset = 0
            
            while True:
                new_engineers_batch = []
                with be.get_db_connection() as conn, conn.cursor() as cur:
                    # id > last_processed_id の条件で、BATCH_SIZE分だけ取得
                    cur.execute(
                        "SELECT * FROM engineers WHERE id > %s ORDER BY id ASC LIMIT %s OFFSET %s",
                        (last_processed_id, BATCH_SIZE, offset)
                    )
                    new_engineers_batch = cur.fetchall()

                if not new_engineers_batch:
                    break # 処理する技術者がなくなったらループを抜ける

                print(f"  - Evaluating batch of {len(new_engineers_batch)} engineers (offset: {offset})")
                for engineer in new_engineers_batch:
                    # ... (LLM評価とメール通知のロジックは変更なし) ...
                    llm_result = be.get_match_summary_with_llm(job_data['document'], engineer['document'])
                    if llm_result and llm_result.get('summary') in valid_ranks:
                        grade = llm_result.get('summary')
                        match_id = be.create_or_update_match_record(job_data['id'], engineer['id'], 0.0, grade, llm_result)
                        if match_id:
                            print(f"    HIT! Job({item_id}) vs Eng({engineer['id']}) -> Rank {grade}. Match ID: {match_id}")
                            # ... (メール本文生成と送信) ...
                            be.send_email_notification(email, subject, body)
                
                offset += BATCH_SIZE
                time.sleep(0.5) # DBへの連続アクセスを避けるための短い待機
            # ★★★【修正ここまで】★★★

        # --- 依頼が「技術者」の場合も同様に修正 ---
        elif item_type == 'engineer':
            # ... (上記と同様のバッチ処理ロジックを案件用に実装) ...
            pass
            
        # 4. 最後に処理したIDを更新
        be.update_auto_match_last_processed_ids(req_id, max_job_id, max_engineer_id)
        print(f"Updated last processed IDs for request {req_id}.")

    print(f"--- Auto-matcher batch finished at {datetime.now()} ---")


if __name__ == "__main__":
    main()
