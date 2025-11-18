# run_cleanup.py

import os
import sys
import toml
from datetime import datetime
import psycopg2
from psycopg2.extras import DictCursor

# --- グローバル設定 ---
# このスクリプトがどこから実行されても、プロジェクトルートを基準にパスを解決する
project_root = os.path.abspath(os.path.dirname(__file__))
LOG_FILE_PATH = os.path.join(project_root, "logs", "cleanup_cron.log")

# --- ヘルパー関数 ---

def log_message(message: str):
    """ログファイルにタイムスタンプ付きでメッセージを追記する"""
    try:
        # ログディレクトリが存在しない場合は作成する
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
        with open(LOG_FILE_PATH, "a", encoding='utf-8') as f:
            f.write(f"{datetime.now()} | {message}\n")
    except Exception as e:
        print(f"FATAL: Could not write to log file {LOG_FILE_PATH}. Error: {e}")

def get_db_url_from_secrets() -> str | None:
    """secrets.tomlからデータベースURLを取得する"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(current_dir, '.streamlit', 'secrets.toml')
        
        secrets = toml.load(secrets_path)
        
        # ▼▼▼【ここからが修正の核】▼▼▼
        # 'database'セクションを介さず、直接 'DATABASE_URL' キーにアクセスする
        db_url = secrets.get("DATABASE_URL")
        
        if not db_url:
            # もし 'DATABASE_URL' がなければ、'database'セクションも試す（念のため）
            db_url = secrets.get("database", {}).get("url")

        if not db_url:
            raise ValueError("DATABASE_URLがsecrets.tomlに見つかりません。")
            
        return db_url
        # ▲▲▲【修正ここまで】▲▲▲

    except Exception as e:
        log_message(f"CRITICAL: secrets.toml の読み込みまたはDATABASE_URLの取得に失敗: {e}")
        return None

# --- メイン処理 ---

def main(is_dry_run: bool):
    """メインのクリーンアップ処理を実行する"""
    
    if is_dry_run:
        log_message("--- Cleanup script started in DRY RUN mode ---")
    else:
        log_message("--- Cleanup script started in EXECUTE mode ---")

    db_url = get_db_url_from_secrets()
    if not db_url:
        return

    conn = None
    try:
        conn = psycopg2.connect(db_url, cursor_factory=DictCursor)
        with conn.cursor() as cur:
            
            # --- 1. 古い「案件(jobs)」のクリーンアップ ---
            log_message("Processing 'jobs' table...")
            
            # 案件テーブル用のSQL
            # 自動マッチング中の案件も保護するように修正
            jobs_sql_select = """
                SELECT id FROM jobs
                WHERE created_at <= NOW() - INTERVAL '120 hours'
                AND NOT EXISTS (
                    SELECT 1 FROM matching_results mr WHERE mr.job_id = jobs.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM auto_match_requests amr 
                    WHERE amr.item_type = 'job' 
                    AND amr.item_id = jobs.id 
                    AND amr.is_active = true
                );
            """
            jobs_sql_delete = """
                DELETE FROM jobs
                WHERE id = ANY(%s);
            """
            
            cur.execute(jobs_sql_select)
            target_job_ids = [row['id'] for row in cur.fetchall()]

            if not target_job_ids:
                log_message("  > No old/unmatched jobs to delete.")
            else:
                log_message(f"  > Found {len(target_job_ids)} old/unmatched jobs to delete. IDs: {target_job_ids}")
                if not is_dry_run:
                    cur.execute(jobs_sql_delete, (target_job_ids,))
                    log_message(f"  > ✅ Successfully deleted {cur.rowcount} jobs.")

            # --- 2. 古い「技術者(engineers)」のクリーンアップ ---
            log_message("Processing 'engineers' table...")
            
            # 技術者テーブル用のSQL
            # 自動マッチング中の技術者も保護するように修正
            engineers_sql_select = """
                SELECT id FROM engineers
                WHERE created_at <= NOW() - INTERVAL '120 hours'
                AND NOT EXISTS (
                    SELECT 1 FROM matching_results mr WHERE mr.engineer_id = engineers.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM auto_match_requests amr 
                    WHERE amr.item_type = 'engineer' 
                    AND amr.item_id = engineers.id 
                    AND amr.is_active = true
                );
            """
            engineers_sql_delete = """
                DELETE FROM engineers
                WHERE id = ANY(%s);
            """

            cur.execute(engineers_sql_select)
            target_engineer_ids = [row['id'] for row in cur.fetchall()]

            if not target_engineer_ids:
                log_message("  > No old/unmatched engineers to delete.")
            else:
                log_message(f"  > Found {len(target_engineer_ids)} old/unmatched engineers to delete. IDs: {target_engineer_ids}")
                if not is_dry_run:
                    cur.execute(engineers_sql_delete, (target_engineer_ids,))
                    log_message(f"  > ✅ Successfully deleted {cur.rowcount} engineers.")

            # ドライランでなければ、変更をコミット
            if not is_dry_run:
                conn.commit()
                log_message("Database changes have been committed.")
            else:
                log_message("Dry run finished. No changes were made to the database.")

    except (psycopg2.Error, Exception) as e:
        log_message(f"CRITICAL: An error occurred during cleanup process: {e}")
        if conn:
            conn.rollback()
            log_message("Database transaction has been rolled back.")
    finally:
        if conn:
            conn.close()
        log_message("--- Cleanup script finished ---\n")

# --- スクリプトのエントリーポイント ---
if __name__ == "__main__":
    # コマンドライン引数に "--execute" が含まれているかチェック
    # 含まれていなければ、is_dry_run は True になる
    is_dry_run_mode = "--execute" not in sys.argv
    
    main(is_dry_run=is_dry_run_mode)
