# pages/2_メール処理.py
import streamlit as st
# backend.pyから必要な関数をインポート
from backend import init_database, load_embedding_model, process_new_mails

# ★★★ 変更点: ページタイトルを更新 ★★★
st.set_page_config(page_title="Universal AIマッチングシステム | メール処理", layout="wide")

# アプリケーションの初期化
init_database()
load_embedding_model()

st.title("📧 メール処理実行")

st.markdown("""
このページでは、`mailbox`ディレクトリに置かれた新しいメール（テキストファイル）を読み込み、
データベースへの登録とマッチング処理を実行します。
""")

st.warning("処理には数分かかる場合があります。処理が完了するまでこのページを閉じないでください。")

if st.button("新着メールをチェックしてマッチング実行", type="primary", use_container_width=True):
    # process_new_mails関数を呼び出す
    success = process_new_mails()
    if success:
        st.balloons()
        st.success("全ての処理が正常に完了しました！")
        st.info("左のサイドバーから「ダッシュボード」を選択して、最新のマッチング結果を確認してください。")
    else:
        st.error("処理中にエラーが発生しました。コンソールのログを確認してください。")
