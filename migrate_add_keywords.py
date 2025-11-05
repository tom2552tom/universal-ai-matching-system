# migrate_add_keywords.py

import os
import sys
import time
import psycopg2
from psycopg2.extras import DictCursor
import google.generativeai as genai
import toml

# --- このスクリプト専用のセットアップ ---
def setup():
    """必要な設定を読み込む"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(current_dir, '.streamlit', 'secrets.toml')
        with open(secrets_path, "r", encoding="utf-8") as f:
            secrets = toml.load(f)
        
        genai.configure(api_key=secrets["GOOGLE_API_KEY"])
        db_url = secrets["DATABASE_URL"]
        return db_url
    except Exception as e:
        print(f"❌ セットアップ中にエラーが発生しました: {e}")
        sys.exit(1)


def extract_keywords_for_migration(text_content: str, item_type: str, count: int = 10) -> list:
        """
        AI(LLM)を使って、与えられたテキストから検索キーワードを抽出する。
        """


        try:
            if item_type == 'job':
                instruction = "以下の案件情報から、技術者を探す上で最も重要度が高いと思われる「必須スキル」を、重要なものから順番に最大3つ抽出してください。"
            else: # item_type == 'engineer'
                instruction = "以下の技術者情報から、その人のキャリアで最も核となっている「コアスキル」を、得意なものから順番に最大3つ抽出してください。"
            
            prompt = f"""
            あなたは、与えられたテキストから最も重要な検索キーワードを抽出する専門家です。

            # 絶対的なルール:
            - 抽出するキーワードは、**必ず3個以内**に厳選してください。
            - 出力は、**カンマ区切りの単語リストのみ**とし、他のテキストは一切含めないでください。

            # 指示:
            {instruction}
            具体的な技術名（プログラミング言語、フレームワーク、DB、クラウド名など）を優先してください。

            # 具体例:
            入力:「Java(SpringBoot)での開発経験が10年あり、直近ではPHP(Laravel)も使用。AWSの経験も豊富です。」
            出力: Java, AWS, PHP

            # 本番:
            入力テキスト: ---
            {text_content}
            ---
            出力:
            """
            
            model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
            response = model.generate_content(prompt)
            
            keywords = [kw.strip().lower() for kw in response.text.strip().split(',') if kw.strip()]
            
            if not keywords:
                #log_message("WARNING: AI returned no keywords.")
                return []
                
            return keywords[:3] # 確実に3つ以内に制限してリストとして返す

        except Exception as e:
            #log_message(f"ERROR: Failed to extract keywords with LLM: {e}")
            return []
    # ▲▲▲【新しい関数ここまで】▲▲▲



def extract_keywords_for_migration(text_content: str, item_type: str, count: int = 10) -> list:
    """データ移行専用のキーワード抽出関数"""
    # (backend.pyやrun_auto_matcher.pyにあるものとほぼ同じロジック)
    try:
        # ... (プロンプトの定義) ...
        model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
        response = model.generate_content(prompt)
        keywords = [kw.strip().lower() for kw in response.text.strip().split(',') if kw.strip()]
        return keywords[:count]
    except Exception as e:
        print(f"    - ❌ キーワード抽出APIエラー: {e}")
        return []

def process_table(table_name: str, conn):
    """
    指定されたテーブルをスキャンし、keywordsがNULLのレコードを更新する。
    """
    print(f"\n--- テーブル '{table_name}' の処理を開始します ---")
    
    BATCH_SIZE = 50
    offset = 0
    updated_count = 0

    while True:
        try:
            with conn.cursor() as cur:
                # keywordsがNULLのレコードをバッチで取得
                cur.execute(
                    f"SELECT id, document FROM {table_name} WHERE keywords IS NULL LIMIT %s OFFSET %s",
                    (BATCH_SIZE, offset)
                )
                records = cur.fetchall()

            if not records:
                print(f"✅ テーブル '{table_name}' のすべてのレコードにキーワードが設定済みです。")
                break

            print(f"  > {len(records)}件のレコードを処理中 (オフセット: {offset})...")
            
            for record in records:
                item_id = record['id']
                document = record['document']
                item_type = 'job' if table_name == 'jobs' else 'engineer'
                
                print(f"    - ID: {item_id} のキーワードを抽出中...")
                
                # APIのレート制限を避けるために少し待機
                time.sleep(1.5) 
                
                keywords = extract_keywords_for_migration(document, item_type)

                if keywords:
                    # DBを更新
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE {table_name} SET keywords = %s WHERE id = %s",
                            (keywords, item_id)
                        )
                    conn.commit()
                    print(f"      -> ✅ 更新完了: {keywords}")
                    updated_count += 1
                else:
                    print(f"      -> ⚠️ キーワードが抽出できなかったため、スキップします。")

            # 次のバッチに進む
            offset += BATCH_SIZE

        except (psycopg2.Error, Exception) as e:
            print(f"❌ 処理中にデータベースエラーが発生しました: {e}")
            conn.rollback() # エラーが発生した場合は、そのトランザクションをロールバック
            break
            
    print(f"--- テーブル '{table_name}' の処理完了。合計 {updated_count} 件を更新しました。 ---")


def main():
    """メインの実行関数"""
    print("★★★ 既存データのキーワード一括追加スクリプトを開始します ★★★")
    db_url = setup()
    
    conn = psycopg2.connect(db_url, cursor_factory=DictCursor)
    if not conn:
        print("❌ データベースに接続できませんでした。")
        return

    try:
        # jobsテーブルを処理
        process_table('jobs', conn)
        
        # engineersテーブルを処理
        process_table('engineers', conn)

    finally:
        if conn:
            conn.close()
            print("\nデータベース接続を閉じました。")
            
    print("\n★★★ すべての処理が完了しました ★★★")


if __name__ == "__main__":
    main()
