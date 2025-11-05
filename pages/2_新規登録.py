# pages/1_新規データ登録.py

import streamlit as st
import backend as be
import time
import ui_components as ui

# --- ページの基本設定 ---
ui.apply_global_styles()
st.set_page_config(page_title="新規データ登録", layout="centered") # このページは中央寄せレイアウトが見やすい
if not ui.check_password():
    st.stop()

# --- ページタイトル ---
st.title("📝 新規データ登録")
st.info("ここに案件情報または技術者情報のテキストを貼り付けて登録できます。AIが自動でタイプを判別し、キーワード抽出まで行います。")
st.divider()

# --- 新規登録フォーム ---
# clear_on_submit=True にすることで、登録成功後にフォームがクリアされる
with st.form("new_item_form", clear_on_submit=True):
    
    input_text = st.text_area(
        "登録する情報",
        height=400, # 高さを十分に確保
        placeholder="メール本文やスキルシートのテキストをここに貼り付けてください..."
    )
    
    submitted = st.form_submit_button("この内容でAI解析・登録を実行", type="primary", use_container_width=True)

# --- 実行ロジック ---
if submitted:
    if not input_text.strip():
        st.warning("登録する情報が入力されていません。")
    else:
        # 登録処理を実行し、結果に基づいて画面遷移
        with st.spinner("AIが解析・登録処理を実行中です..."):
            final_result = None
            # バックエンドのジェネレータ関数を呼び出す
            # st.statusは使わず、完了後に一気に遷移する
            for result in be.register_item_from_text(input_text):
                # ジェネレータの最後のyield（辞書）を待つ
                if isinstance(result, dict) and result.get("type") == "complete":
                    final_result = result
            
            if final_result:
                item_type = final_result.get("item_type")
                item_id = final_result.get("item_id")
                
                st.success(f"登録が完了しました！(タイプ: {item_type}, ID: {item_id}) 詳細ページに移動します。")
                time.sleep(2) # メッセージを読ませるための待機

                if item_type == 'job':
                    st.session_state['selected_job_id'] = item_id
                    st.switch_page("pages/6_案件詳細.py")
                elif item_type == 'engineer':
                    st.session_state['selected_engineer_id'] = item_id
                    st.switch_page("pages/5_技術者詳細.py")
            else:
                # ジェネレータから完了通知が来なかった場合
                st.error("登録処理に失敗しました。入力内容を確認するか、管理者にお問い合わせください。")

st.divider()
ui.display_footer()
