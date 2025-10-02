from pathlib import Path
import streamlit as st
import sqlite3
import faiss
from sentence_transformers import SentenceTransformer
import numpy as np
import os

# --- 1. Bootstrapの読み込み ---
def load_bootstrap():
    # Bootstrap CSS
    st.markdown('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">', unsafe_allow_html=True)
    # Bootstrap Icons
    st.markdown('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">', unsafe_allow_html=True)
    # Google Fonts (Poppins)
    st.markdown("<link href='https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap' rel='stylesheet'>", unsafe_allow_html=True)
    # カスタムスタイル（Bootstrapの上書きと微調整）
    st.markdown("""
    <style>
        body { font-family: 'Poppins', sans-serif; background-color: #f0f2f6; }
        .stButton>button { width: 100%; } /* Streamlitのボタン幅を100%に */
        .card { margin-bottom: 1.5rem; } /* カード間のマージン */
    </style>
    """, unsafe_allow_html=True)

# --- 定数とファイルパス ---
DB_FILE = "bidirectional_system.db"
JOB_INDEX_FILE = "job_index.faiss"
CANDIDATE_INDEX_FILE = "candidate_index.faiss"
MODEL_NAME = 'intfloat/multilingual-e5-large'

# --- 2. モデルの読み込み ---
@st.cache_resource
def load_model():
    return SentenceTransformer(MODEL_NAME)

# --- 3. データベースの初期化と接続 ---
def init_database():
    # (省略... 前のコードと同じ)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, resume TEXT NOT NULL)')
    conn.commit()
    conn.close()

def get_db_connection():
    # (省略... 前のコードと同じ)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# --- 4. FAISSインデックスの差分更新 ---
def update_index(index_path, new_item_id, new_item_text):
    # (省略... 前のコードと同じ)
    dimension = model.get_sentence_embedding_dimension()
    if os.path.exists(index_path):
        index = faiss.read_index(index_path)
    else:
        index = faiss.IndexIDMap(faiss.IndexFlatL2(dimension))
    new_embedding = model.encode([new_item_text], normalize_embeddings=True, show_progress_bar=False)
    new_id = np.array([new_item_id], dtype=np.int64)
    index.add_with_ids(new_embedding, new_id)
    faiss.write_index(index, index_path)

# --- 5. キャッシュ対応のAIマッチング関数 ---
@st.cache_data(show_spinner=False)
def search(query_text, index_path, top_k=5):
    # (省略... 前のコードと同じ)
    if not os.path.exists(index_path) or faiss.read_index(index_path).ntotal == 0:
        return [], []
    index = faiss.read_index(index_path)
    query_vector = model.encode(query_text, normalize_embeddings=True).reshape(1, -1)
    distances, ids = index.search(query_vector, top_k)
    return distances[0].tolist(), ids[0].tolist()

# --- 6. Streamlit UIの定義 ---
st.set_page_config(page_title="AIマッチングシステム", layout="wide")

load_bootstrap()
model = load_model()
init_database()

# --- ヘッダー ---
st.markdown("""
<div class="container-fluid text-center p-4">
    <h1 class="display-4"><i class="bi bi-person-bounding-box"></i> AIマッチングシステム(Demo)</h1>
    <p class="lead">メールで届いた案件と応募者をDBに登録し、AIがマッチングします。</p>
</div>
""", unsafe_allow_html=True)

# --- メインコンテンツ ---
st.markdown('<div class="container">', unsafe_allow_html=True)
st.markdown('<div class="row">', unsafe_allow_html=True)

# --- 左カラム: データ登録 ---
st.markdown('<div class="col-lg-4">', unsafe_allow_html=True)
with st.container():
    st.markdown('<div class="card"><div class="card-body">', unsafe_allow_html=True)
    st.markdown('<h3 class="card-title"><i class="bi bi-pencil-square"></i> データ登録</h3>', unsafe_allow_html=True)
    st.caption("メールパーサーからの出力を想定")

    with st.expander("新しい案件を登録", expanded=False):
        with st.form("new_job_form", clear_on_submit=True):
            job_title = st.text_input("案件名")
            job_desc = st.text_area("案件詳細", height=100)
            if st.form_submit_button("案件を登録", use_container_width=True, type="primary"):
                if job_title and job_desc:
                    # (DB登録とインデックス更新のロジックは前のコードと同じ)
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute('INSERT INTO jobs (title, description) VALUES (?, ?)', (job_title, job_desc))
                    new_job_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    with st.spinner("インデックス更新中..."):
                        update_index(JOB_INDEX_FILE, new_job_id, job_desc)
                    st.success("案件を登録しました。")
                    st.rerun()
    
    with st.expander("新しい応募者を登録", expanded=False):
        with st.form("new_candidate_form", clear_on_submit=True):
            candidate_name = st.text_input("応募者名")
            candidate_resume = st.text_area("職務経歴", height=100)
            if st.form_submit_button("応募者を登録", use_container_width=True, type="primary"):
                if candidate_name and candidate_resume:
                    # (DB登録とインデックス更新のロジックは前のコードと同じ)
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute('INSERT INTO candidates (name, resume) VALUES (?, ?)', (candidate_name, candidate_resume))
                    new_candidate_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    with st.spinner("インデックス更新中..."):
                        update_index(CANDIDATE_INDEX_FILE, new_candidate_id, candidate_resume)
                    st.success("応募者を登録しました。")
                    st.rerun()
    st.markdown('</div></div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True) # col-lg-4 end

# --- 中央カラム: 応募者中心のマッチング ---
st.markdown('<div class="col-lg-4">', unsafe_allow_html=True)
with st.container():
    st.markdown('<div class="card"><div class="card-body">', unsafe_allow_html=True)
    st.markdown('<h3 class="card-title"><i class="bi bi-file-earmark-person"></i> 応募者に合う案件</h3>', unsafe_allow_html=True)
    conn = get_db_connection()
    all_candidates = [dict(row) for row in conn.execute('SELECT * FROM candidates ORDER BY id DESC').fetchall()]
    conn.close()
    if all_candidates:
        selected_candidate = st.selectbox("応募者を選択", options=all_candidates, format_func=lambda c: f"ID:{c['id']} - {c['name']}")
        if selected_candidate:
            st.markdown("---")
            st.subheader("おすすめ案件リスト")
            distances, ids = search(selected_candidate['resume'], JOB_INDEX_FILE)
            if ids:
                for dist, job_id in zip(distances, ids):
                    if job_id != -1:
                        conn = get_db_connection()
                        job = conn.execute('SELECT * FROM jobs WHERE id = ?', (int(job_id),)).fetchone()
                        conn.close()
                        if job:
                            score = (1 - dist) * 100
                            st.markdown(f"**{job['title']} (ID:{job['id']})**")
                            st.progress(int(score), text=f"マッチ度 {score:.1f}%")
                            with st.expander("詳細を見る"): st.write(job['description'])
    st.markdown('</div></div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True) # col-lg-4 end

# --- 右カラム: 案件中心のマッチング ---
st.markdown('<div class="col-lg-4">', unsafe_allow_html=True)
with st.container():
    st.markdown('<div class="card"><div class="card-body">', unsafe_allow_html=True)
    st.markdown('<h3 class="card-title"><i class="bi bi-journal-check"></i> 案件に合う応募者</h3>', unsafe_allow_html=True)
    conn = get_db_connection()
    all_jobs = [dict(row) for row in conn.execute('SELECT * FROM jobs ORDER BY id DESC').fetchall()]
    conn.close()
    if all_jobs:
        selected_job = st.selectbox("案件を選択", options=all_jobs, format_func=lambda j: f"ID:{j['id']} - {j['title']}")
        if selected_job:
            st.markdown("---")
            st.subheader("おすすめ応募者リスト")
            distances, ids = search(selected_job['description'], CANDIDATE_INDEX_FILE)
            if ids:
                for dist, candidate_id in zip(distances, ids):
                    if candidate_id != -1:
                        conn = get_db_connection()
                        candidate = conn.execute('SELECT * FROM candidates WHERE id = ?', (int(candidate_id),)).fetchone()
                        conn.close()
                        if candidate:
                            score = (1 - dist) * 100
                            st.markdown(f"**{candidate['name']} (ID:{candidate['id']})**")
                            st.progress(int(score), text=f"マッチ度 {score:.1f}%")
                            with st.expander("詳細を見る"): st.write(candidate['resume'])
    st.markdown('</div></div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True) # col-lg-4 end

st.markdown('</div>', unsafe_allow_html=True) # row end
st.markdown('</div>', unsafe_allow_html=True) # container end