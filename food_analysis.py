# import zipfile
# import os
# import csv
# from PIL import Image
# import google.generativeai as genai

# # ========================
# # 設定 API KEY
# API_KEY = "AIzaSyC5lKSpC33Bm1lJmMFuaSfA_0viHJqiWek"
# genai.configure(api_key=API_KEY)

# # ========================
# # 1️⃣ 輸入本機 zip 路徑
# zip_name = "C:\\Users\\黃暐智\\Desktop\\周和\\CODE\\downloaded_images.zip"  # 例如 ./my_images.zip

# # 2️⃣ 解壓縮
# with zipfile.ZipFile(zip_name, 'r') as zip_ref:
#     zip_ref.extractall("images")

# # 3️⃣ 設定 Gemini 模型
# model = genai.GenerativeModel('gemini-2.5-flash')

# # 4️⃣ 基本分析 prompt
# base_prompt = (
#     "請用繁體中文分析這張圖片，"
#     "用完全理性的方式判斷裡面有哪些食物，"
#     "要特別關注分量，"
#     "再透過分量以 USDA 的標準推估每樣食物的熱量，"
#     "所有敘述請簡單扼要。\n"
# )

# # 5️⃣ 開啟 CSV
# with open("analysis_result.csv", mode='w', newline='', encoding='utf-8-sig') as csvfile:
#     csv_writer = csv.writer(csvfile)
#     csv_writer.writerow(['filename', 'result'])

#     # 6️⃣ 遞迴所有子資料夾
#     for root, dirs, files_in_dir in os.walk("images"):
#         for img_name in files_in_dir:
#             img_path = os.path.join(root, img_name)

#             if not img_name.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
#                 continue

#             print(f"📌 分析中：{img_path}")

#             custom_prompt = f"圖片檔名：{img_name}"
#             final_prompt = base_prompt + custom_prompt

#             img = Image.open(img_path)

#             response = model.generate_content([final_prompt, img])

#             result_text = response.text.strip()
#             print(result_text)

#             csv_writer.writerow([img_path, result_text])

# print("✅ 所有分析已完成，結果已存成 analysis_result.csv")



import zipfile
import os
import csv
from PIL import Image
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

# ========================
API_KEY = "AIzaSyC5lKSpC33Bm1lJmMFuaSfA_0viHJqiWek"
genai.configure(api_key=API_KEY)

zip_name = "C:\\Users\\黃暐智\\Desktop\\周和\\CODE\\downloaded_images.zip"

with zipfile.ZipFile(zip_name, 'r') as zip_ref:
    zip_ref.extractall("images")

base_prompt = (
    "請用繁體中文分析這張圖片，"
    "用完全理性的方式判斷裡面有哪些食物，"
    "要特別關注分量，"
    "再透過分量以 USDA 的標準推估每樣食物的熱量，"
    "所有敘述請簡單扼要。\n"
)

img_paths = []
for root, dirs, files_in_dir in os.walk("images"):
    for img_name in files_in_dir:
        if img_name.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
            img_paths.append(os.path.join(root, img_name))

print(f"✅ 共找到 {len(img_paths)} 張圖片")

csv_lock = threading.Lock()
csv_file = open("analysis_result.csv", mode='w', newline='', encoding='utf-8-sig')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(['filename', 'result'])

# 建立一次 Model
model = genai.GenerativeModel('gemini-2.5-flash')

def analyze_image(img_path):
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            custom_prompt = f"圖片檔名：{os.path.basename(img_path)}"
            final_prompt = base_prompt + custom_prompt

            img = Image.open(img_path).convert("RGB")

            # 關鍵：直接傳 PIL.Image 給 Gemini
            response = model.generate_content([final_prompt, img])

            result_text = response.text.strip()
            print(f"✅ 分析完成：{img_path}（嘗試第 {attempt} 次）")

            with csv_lock:
                csv_writer.writerow([img_path, result_text])
            break

        except Exception as e:
            print(f"⚠️ 第 {attempt} 次嘗試失敗：{img_path}，原因：{e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                print(f"❌ 分析失敗超過 {max_retries} 次：{img_path}")

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = [executor.submit(analyze_image, img_path) for img_path in img_paths]
    for _ in as_completed(futures):
        pass

csv_file.close()
print("✅ 所有分析已完成 ➜ 已輸出 analysis_result.csv")

