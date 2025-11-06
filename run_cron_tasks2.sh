#!/bin/bash

# --- スクリプトの基本設定 ---
# このシェルスクリプトがあるディレクトリを基準に動作するようにする
cd "$(dirname "$0")"

# --- ログファイルの設定 ---
LOG_FILE="./logs/cron_tasks2.log"
# ログディレクトリが存在しない場合は作成する
mkdir -p ./logs

# --- Python仮想環境のパス ---
# フルパスで指定するのが最も確実
PYTHON_EXEC="/Users/tomokazuhatanaka/Documents/GitHub/universal-ai-matching-system/venv/bin/python"

# --- 実行するPythonスクリプト ---
EMAIL_PROCESSOR_SCRIPT="run_email_processor.py"
AUTO_MATCHER_SCRIPT="run_auto_matcher.py"
CLEANUP_SCRIPT="run_cleanup.py" # ★★★ 追加 ★★★


# --- 処理開始のログ ---
echo "============================================================" >> "${LOG_FILE}"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron task script started." >> "${LOG_FILE}"




# --- 2. 自動マッチングスクリプトの実行 ---
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ${AUTO_MATCHER_SCRIPT}..." >> "${LOG_FILE}"

"${PYTHON_EXEC}" "${AUTO_MATCHER_SCRIPT}" >> "${LOG_FILE}" 2>&1

if [ $? -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${AUTO_MATCHER_SCRIPT} finished successfully." >> "${LOG_FILE}"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: ${AUTO_MATCHER_SCRIPT} failed. See log for details." >> "${LOG_FILE}"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron task script finished." >> "${LOG_FILE}"
echo "" >> "${LOG_FILE}" # ログの区切りとして空行を追加




# ▼▼▼【ここからが追加箇所】▼▼▼
# --- 3. クリーンアップスクリプトの実行 ---
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ${CLEANUP_SCRIPT}..." >> "${LOG_FILE}"

# --execute 引数を付けて、本番の削除モードで実行する
"${PYTHON_EXEC}" "${CLEANUP_SCRIPT}" --execute >> "${LOG_FILE}" 2>&1

if [ $? -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${CLEANUP_SCRIPT} finished successfully." >> "${LOG_FILE}"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: ${CLEANUP_SCRIPT} failed. See log for details." >> "${LOG_FILE}"
fi
# ▲▲▲【追加ここまで】▲▲▲

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron task script finished." >> "${LOG_FILE}"
echo "" >> "${LOG_FILE}" # ログの区切りとして空行を追加


