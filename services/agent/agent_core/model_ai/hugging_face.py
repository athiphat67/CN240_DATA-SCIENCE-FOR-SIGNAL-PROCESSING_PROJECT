from huggingface_hub import HfApi

api = HfApi()

# กำหนดชื่อ Repo ของคุณ
repo_id = "athiphatss/Xgboost_HSH965_gold_trading_signal"

# สร้าง Repo ใหม่ (ถ้าระบบเช็คว่ามีอยู่แล้ว มันจะข้ามไปทำงานต่อ)
api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True)

# อัปโหลดไฟล์ทั้งหมดในโฟลเดอร์ปัจจุบัน (".") ขึ้น Hugging Face
api.upload_folder(
    folder_path=".", 
    repo_id=repo_id, 
    repo_type="model"
)

print(f"✅ อัปโหลดไฟล์ทั้งหมดขึ้น {repo_id} สำเร็จแล้ว!")