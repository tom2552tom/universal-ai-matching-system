import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

# --- 1. サンプルデータの準備 ---

# 求人案件データ
jobs = [
    {
        "id": "job_001",
        "title": "Ruby on Rails バックエンドエンジニア",
        "description": "自社開発SaaSのサーバーサイド開発担当。要件定義から開発、運用まで一貫して携わります。Ruby on Railsでの開発経験3年以上必須。AWS環境での開発経験者歓迎。"
    },
    {
        "id": "job_002",
        "title": "React フロントエンドエンジニア",
        "description": "toB向け管理画面のUI/UX改善と機能開発。TypeScriptとReactを用いた開発がメインです。UIコンポーネントの設計経験がある方を求めます。"
    },
    {
        "id": "job_003",
        "title": "データサイエンティスト（機械学習）",
        "description": "Pythonを用いて需要予測モデルや推薦システムの構築を行います。統計学の知識と、Scikit-learn, TensorFlow, PyTorch等のフレームワーク利用経験が必須です。"
    }
]

# 応募者データ（職務経歴書やプロフィールを想定）
candidates = [
    {
        "id": "candidate_A",
        "name": "山田 太郎",
        "resume": "株式会社ABCにて5年間、Rubyを用いたECサイトのサーバーサイド開発をリード。決済システムや在庫管理機能の設計・実装を担当。インフラは主にAWSを利用。個人開発でReactも学習中。"
    },
    {
        "id": "candidate_B",
        "name": "鈴木 花子",
        "resume": "Web制作会社でフロントエンドエンジニアとして3年勤務。ReactとTypeScriptを使い、大規模なSPA（シングルページアプリケーション）の構築経験が豊富。デザインシステムに基づいたコンポーネント開発が得意。"
    },
    {
        "id": "candidate_C",
        "name": "佐藤 次郎",
        "resume": "大学院で統計学を専攻後、事業会社でデータアナリストとして2年勤務。Pythonを使い、顧客データ分析や売上予測モデルの作成に従事。Kaggle参加経験あり。機械学習エンジニアへのキャリアチェンジ希望。"
    },
    {
        "id": "candidate_D",
        "name": "田中 三郎",
        "resume": "SIerにてJavaを用いた業務システム開発を4年間経験。プロジェクトリーダーとして顧客折衝も担当。Web業界への転職を希望しており、現在PythonとJavaScriptを独学中。"
    }
]

print("--- 1. データの準備完了 ---")

# --- 2. 文章埋め込みモデルの読み込み ---
print("モデルを読み込んでいます... (初回は時間がかかります)")
model = SentenceTransformer('intfloat/multilingual-e5-large')
print("--- 2. モデルの読み込み完了 ---")


# --- 3. 応募者データをベクトル化し、インデックスを構築 ---
candidate_resumes = [c["resume"] for c in candidates]
candidate_embeddings = model.encode(candidate_resumes, normalize_embeddings=True)

d = candidate_embeddings.shape[1] 
index = faiss.IndexFlatL2(d) 
index.add(candidate_embeddings)

print(f"--- 3. {len(candidates)}名の応募者からインデックスを構築完了 ---")

# --- 4. 各求人案件で応募者を検索 ---
print("\n--- 4. マッチング処理を開始 ---\n")

for job in jobs:
    print("==============================================")
    print(f"【求人案件】: {job['title']}")
    print("----------------------------------------------")
    
    query_vector = model.encode(job['description'], normalize_embeddings=True).reshape(1, -1)
    
    k = 3
    distances, indices = index.search(query_vector, k)
    
    # --- 5. 結果の表示 ---
    print(f"✨ マッチング上位 {k} 名の候補者 ✨")
    for i in range(k):
        matched_candidate = candidates[indices[0][i]]
        similarity_score = 1 - distances[0][i] 
        
        print(f"\n【順位】: {i+1}位 (類似度スコア: {similarity_score:.4f})")
        print(f"【氏名】: {matched_candidate['name']}")
        print(f"【経歴】: {matched_candidate['resume']}")

    print("==============================================\n")
