# 匯入套件 ====================================================================================

import sys
import os
import re
import csv
import time
import shutil
import subprocess
import threading
import datetime
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS

import cv2
import numpy as np
from PIL import Image
import uuid

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import pandas as pd
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain.chains import RetrievalQA

from google.cloud import bigquery
from google.auth import default
from google.oauth2 import service_account
from pathlib import Path

print("已匯入套件")

# 設定 Gemini API KEY
API_KEY = "AIzaSyC5lKSpC33Bm1lJmMFuaSfA_0viHJqiWek"  

# 初始化 Flask
app = Flask(__name__)
CORS(app)

def clean_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name)

# (爬蟲)============================================================================================

@app.route('/scrape_menu', methods=['POST'])
def scrape_analyze_upload():

    # ========== 基本設定 ==========
    csv_path = 'menu_items.csv'
    image_dir = 'downloaded_images'
    analysis_csv_path = 'analysis_result.csv'
    project_id = "my-bigquery-project-food"
    dataset_id = "dataset_food_detection"
    table_id = "analysis_result"
    pages = 4 #爬蟲頁數

    # ========== 清除舊資料 ==========
    for path in [csv_path, analysis_csv_path]:
        if os.path.exists(path):
            os.remove(path)
    if os.path.exists(image_dir):
        shutil.rmtree(image_dir)
    os.makedirs(image_dir, exist_ok=True)

    # ========== 爬蟲抓菜單 ==========
    csv_file = open(csv_path, mode='w', newline='', encoding='utf-8-sig')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['group_title', 'name', 'price', 'img_src', 'label', 'page_no'])
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)

    def scrape_cards(page_no):
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.MuiContainer-root")))
        containers = driver.find_elements(By.CSS_SELECTOR, "div.MuiContainer-root")
        for container in containers:
            try:
                group_title = container.find_element(By.CSS_SELECTOR, ".css-153oegz p").text.strip()
            except:
                group_title = ""
            cards = container.find_elements(By.CSS_SELECTOR, ".css-solczp .MuiBox-root")
            valid_cards = [card for card in cards if card.find_elements(By.TAG_NAME, 'img')]
            for card in valid_cards:
                try:
                    img_tag = card.find_element(By.TAG_NAME, 'img')
                    img_src = img_tag.get_attribute('src')
                    p_tags = card.find_elements(By.TAG_NAME, 'p')
                    name = p_tags[0].text.strip() if len(p_tags) > 0 else ""
                    price = p_tags[1].text.strip() if len(p_tags) > 1 else ""
                    label = card.find_element(By.CSS_SELECTOR, "span.MuiChip-label").text.strip() if card.find_elements(By.CSS_SELECTOR, "span.MuiChip-label") else ""
                    csv_writer.writerow([group_title, name, price, img_src, label, page_no])
                except Exception as e:
                    print(f"Card 解析失敗: {e}")

    try:
        driver.get("https://www.zoheyeats-sys.com.tw/c/building/5")
        button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., '點擊查看圖片')]")))
        driver.execute_script("arguments[0].click();", button)
        scrape_cards(1)
        for i in range(pages):
            try:
                next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//p[contains(., '後一日')]")))
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(2)
                scrape_cards(i + 2)
            except:
                break
    finally:
        driver.quit()
        csv_file.close()

    # ========== 下載圖片 ==========
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            title = clean_filename(row[0])
            name = clean_filename(row[1])
            price = row[2]
            img_url = row[3]
            page_no = row[5]
            filename = f"{title}_{name}_{price}_{page_no}.jpg"
            filepath = os.path.join(image_dir, filename)
            try:
                response = requests.get(img_url)
                if response.status_code == 200:
                    with open(filepath, 'wb') as img_file:
                        img_file.write(response.content)
            except Exception as e:
                print(f"圖片下載失敗: {e}")

    # ========== 分析圖片 ==========
    genai.configure(api_key= API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    base_prompt = (
        "請用繁體中文分析這張圖片，"
        "參考檔案名所給的資訊，"
        "用完全理性的方式判斷裡面有哪些食物，"
        "要特別關注分量，"
        "再透過 '衛福部食品營養成分資料庫 TFND' 的標準推估每樣食物的熱量，"
        "所有敘述請簡單扼要。\n"
    )

    img_paths = [os.path.join(image_dir, name) for name in os.listdir(image_dir)
                 if name.lower().endswith(('.jpg', '.png', '.jpeg'))]
    csv_lock = threading.Lock()
    with open(analysis_csv_path, mode='w', newline='', encoding='utf-8-sig') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(['filename', 'result'])

        def analyze_image(img_path):
            for attempt in range(1, pages):
                try:
                    prompt = base_prompt + f"圖片檔名：{os.path.basename(img_path)}"
                    img = Image.open(img_path).convert("RGB")
                    response = model.generate_content([prompt, img])
                    result = response.text.strip()
                    with csv_lock:
                        csv_writer.writerow([os.path.basename(img_path), result])
                    print(f"分析完成：{img_path}")
                    break
                except Exception as e:
                    print(f"第 {attempt} 次分析失敗：{e}")
                    time.sleep(2 ** attempt)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(analyze_image, path) for path in img_paths]
            for _ in as_completed(futures):
                pass

    # ========== 上傳 BigQuery ==========
    credentials, _ = default()
    client = bigquery.Client(project=project_id, credentials=credentials)
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        quote_character='"',
        allow_quoted_newlines=True
    )

    with open(analysis_csv_path, "rb") as source_file:
        load_job = client.load_table_from_file(source_file, table_ref, job_config=job_config)
        load_job.result()

    # ========== 結果回傳 ==========
    return jsonify({
        "status": "success",
        "message": "菜單爬蟲、圖片分析與 BigQuery 上傳完成！",
        "csv": csv_path,
        "analysis_csv": analysis_csv_path,
        "bq_table": table_ref
    })

# ================================================================================================

# (文字分析)================================================================================================

chat_memory = {}
last_reset_time = datetime.datetime.now()
RESET_INTERVAL_HOURS = 3

@app.route('/ask_Q', methods=['POST'])
def ask_Q():

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "./my-bigquery-project-food-b1ca609756e5.json"
    
    # 取得今天的日期
    global chat_memory, last_reset_time
    today = datetime.date.today()
    weekday_number = today.weekday()
    now = datetime.datetime.now()

    if (now - last_reset_time).total_seconds() > RESET_INTERVAL_HOURS * 3600:
        chat_memory = {}
        last_reset_time = now

    # 對應中文星期
    weekday_map = {
        0: "星期一",
        1: "星期二",
        2: "星期三",
        3: "星期四",
        4: "星期五",
    }
    day = weekday_map[weekday_number]
    time = now.strftime("%Y-%m-%d %H:%M:%S")

    # 初始化 BigQuery 客戶端
    client = bigquery.Client()

    query = f"""
    SELECT * FROM `my-bigquery-project-food.dataset_food_detection.analysis_result`
    """

    # 執行查詢並轉成 DataFrame
    df = client.query(query).to_dataframe()

    # 將每列轉成文字段落
    documents = df.apply(lambda row: "；".join([f"{col}:{row[col]}" for col in df.columns]), axis=1).tolist()

    print("資料從 BigQuery 提取成功 !")

    # 嵌入模型
    embedding = GoogleGenerativeAIEmbeddings(
        model="models/embedding-001",
        google_api_key= API_KEY
    )

    # 向量資料庫
    db = FAISS.from_texts(documents, embedding=embedding)

    # 讀取 Excel 資料
    df_nutrition = pd.read_csv("食品營養成分資料庫2024UPDATE2.csv")
    df_nutrition = df_nutrition.dropna(how='all')
    nutrition_docs = df_nutrition.apply(lambda row: "；".join([f"{col}:{row[col]}" for col in df_nutrition.columns]), axis=1).tolist()

    # 建立第二個向量庫
    nutrition_db = FAISS.from_texts(nutrition_docs, embedding=embedding)

    # 合併向量庫
    db.merge_from(nutrition_db)

    # Gemini LLM
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key = API_KEY,
        temperature=0.1
    )

    # RAG 問答鏈
    rag_chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=db.as_retriever(search_kwargs={"k": 100}),
        return_source_documents=False
    )

    try:
        # 從 form-data 或 JSON 拿取使用者問題
        data = request.get_json() if request.is_json else request.form
        question = data.get('question')
        user_id = data.get('user_id') or 'default_user'

        if not question:
            return jsonify({'error': 'No question provided'}), 400
        
        # ======== 讀取對話記憶 (最多保留 20 則) ========
        memory = chat_memory.get(user_id, [])
        history_text = ""
        for q, a in memory[-20:]:  # 最多保留最近 20 則
            history_text += f"使用者：{q}\n助理：{a}\n"

        prompt_template = """
        你是一位平日午餐推薦助理，擁有當週的午餐菜單資料。請根據下列使用者問題，簡單、有條理地回答，並務必附上【店家名稱】與【餐點名稱】。

        回答規則如下：
        1. 根據問題中的「星期幾」決定要使用哪一天的菜單：
        - 星期一 ➜ 對應檔名含「_1.jpg」
        - 星期二 ➜ 對應檔名含「_2.jpg」
        - ...
        - 星期五 ➜ 對應檔名含「_5.jpg」
        2. 若問題中未明確提及星期幾，請從語意中推論相對時間（如「今天」、「明天」），並根據提供的 `weekday` 判斷實際日期。
        3. 若推論出來的時間落在週末（六日），請回答「週末不提供午餐」。
        4. 所有回答皆須使用【繁體中文】。
        5. 如問題與「平日午餐」無關，請婉拒回答。

        ---
        使用者問題：
        {query}

        目前時間資訊：
        - 星期幾：{weekday}
        - 時間：{time}

        對話歷史參考：
        {history}
        """
        prompt = prompt_template.format(query=question, weekday=day, time = time, history=history_text)
        response = rag_chain({"query": prompt})
        answer = response["result"]

        # ======== 儲存記憶 =========
        memory.append((question, answer))
        chat_memory[user_id] = memory  # 更新記憶

        return jsonify({
            "question": question,
            "answer": response["result"]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================

# (圖像分析)================================================================================================

@app.route('/food_detection', methods=['POST'])

def postInput():
    
    UPLOAD_FOLDER = 'uploads'
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # 設定 Gemini API KEY
    genai.configure(api_key=API_KEY)
    # 初始化 Gemini Vision Model
    model = genai.GenerativeModel('gemini-2.5-pro')

    # 1. 檢查是否有檔案
    if 'image' not in request.files:
        return jsonify({"error": "No image part"}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # 2. 產生唯一檔名 + 儲存到 uploads 資料夾
    unique_filename = f"{uuid.uuid4().hex}.jpg"
    input_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(input_path)

    try:
        # 3. 使用 PIL 開啟圖片
        img_pil = Image.open(input_path)

        # 4. 設定提示詞
        base_prompt = (
            "請用【繁體中文】分析這張圖片內容，"
            "以【理性客觀】的方式辨識圖中包含的食物項目，"
            "並依下列步驟進行分析：\n\n"
            "1. 列出圖中可辨識的食物（以食物名稱列出即可）。\n"
            "2. 為每一項食物撰寫簡短的評估（例如口感、營養特色或常見搭配）。\n"
            "3. 根據「衛福部食品營養成分資料庫（TFND）」標準，推估每樣食物的熱量（單位：大卡 kcal）。\n"
            "4. 統整所有食物的熱量，計算出總熱量。\n\n"
            "請依下列格式輸出：\n"
            "【食物名稱】：XXX\n"
            "【評估】：XXX\n"
            "【熱量】：XXX kcal\n"
            "(依序列出所有食物)\n\n"
            "【總熱量】：XXX kcal\n"
            "請勿捏造不存在的食物，也請勿加入圖片以外的內容。"
        )

        # 5. 呼叫 Gemini Vision 模型
        response = model.generate_content([
            base_prompt,
            img_pil
        ])
        result_text = response.text

        # 6. 整理回傳
        return jsonify({
            "message": "分析完成",
            "gemini_result": result_text,
        })

    finally:
        # 7. 清除暫存圖片
        if os.path.exists(input_path):
            os.remove(input_path)

# ================================================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5678, debug=True)