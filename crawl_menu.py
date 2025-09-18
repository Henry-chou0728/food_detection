
import subprocess
import sys
import shutil

def install_if_missing(package_name, import_name=None):
    import_name = import_name or package_name
    try:
        __import__(import_name)
    except ImportError:
        print(f"⚠️ 未安裝 {package_name}，正在安裝中...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

# 安裝所需套件
install_if_missing('flask')
install_if_missing('requests')
install_if_missing('selenium')
install_if_missing('google-generativeai', 'google.generativeai')
install_if_missing('pillow', 'PIL')

from flask import Flask, jsonify
import csv, os, re, requests, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import google.generativeai as genai
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

app = Flask(__name__)

def clean_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name)

@app.route('/scrape_menu', methods=['POST'])
def scrape_menu():
    # 1. 先爬取菜單資料與圖片
    csv_path = 'menu_items.csv'
    image_dir = 'downloaded_images'

    # 🔥 新增這段：若已存在就刪除
    if os.path.exists(csv_path):
        os.remove(csv_path)

    # 刪除圖片資料夾（包含裡面的圖片）
    if os.path.exists(image_dir):
        shutil.rmtree(image_dir)

    os.makedirs(image_dir, exist_ok=True)
    csv_file = open(csv_path, mode='w', newline='', encoding='utf-8-sig')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['group_title', 'name', 'price', 'img_src', 'label', 'page_no'])

    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    # options.add_argument('--headless')  # 需要時打開無頭模式
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)

    def scrape_cards(page_no):
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.MuiContainer-root")))
        containers = driver.find_elements(By.CSS_SELECTOR, "div.MuiContainer-root")
        for container in containers:
            try:
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
                        try:
                            label = card.find_element(By.CSS_SELECTOR, "span.MuiChip-label").text.strip()
                        except:
                            label = ""

                        csv_writer.writerow([group_title, name, price, img_src, label, page_no])
                    except Exception as e:
                        print(f" Card 解析失敗: {e}")
            except Exception as e:
                print(f" Container 解析失敗: {e}")

    try:
        driver.get("https://www.zoheyeats-sys.com.tw/c/building/5")
        button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., '點擊查看圖片')]")))
        driver.execute_script("arguments[0].scrollIntoView(true);", button)
        driver.execute_script("arguments[0].click();", button)

        scrape_cards(page_no=1)

        for i in range(4): #翻四次頁
            try:
                next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//p[contains(., '後一日')]")))
                driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(2)
                scrape_cards(page_no=i+2)
            except Exception as e:
                print(f" 無法翻頁：{e}")
                break
    finally:
        driver.quit()
        csv_file.close()

    # 2. 下載圖片
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
                else:
                    print(f" 圖片下載失敗: {img_url}")
            except Exception as e:
                print(f" 錯誤: {e}")

    # 3. 使用 Gemini 分析圖片
    API_KEY = "AIzaSyC5lKSpC33Bm1lJmMFuaSfA_0viHJqiWek"
    genai.configure(api_key=API_KEY)

    base_prompt = (
        "請用繁體中文分析這張圖片，"
        "參考檔案名所給的資訊，"
        "用完全理性的方式判斷裡面有哪些食物，"
        "要特別關注分量，"
        "再透過 '衛福部食品營養成分資料庫 TFND' 的標準推估每樣食物的熱量，"
        "所有敘述請簡單扼要。\n"
    )

    img_paths = []
    for root, dirs, files_in_dir in os.walk(image_dir):
        for img_name in files_in_dir:
            if img_name.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
                img_paths.append(os.path.join(root, img_name))

    csv_lock = threading.Lock()
    analysis_csv_path = "analysis_result.csv"

    if os.path.exists(analysis_csv_path):
       os.remove(analysis_csv_path)

    with open(analysis_csv_path, mode='w', newline='', encoding='utf-8-sig') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(['filename', 'result'])

        model = genai.GenerativeModel('gemini-2.5-flash')

        def analyze_image(img_path):
            max_retries = 5
            for attempt in range(1, max_retries + 1):
                try:
                    prompt = base_prompt + f"圖片檔名：{os.path.basename(img_path)}"
                    img = Image.open(img_path).convert("RGB")
                    response = model.generate_content([prompt, img])
                    result = response.text.strip()
                    print(f" 分析完成：{img_path}")
                    with csv_lock:
                        csv_writer.writerow([img_path, result])
                    break
                except Exception as e:
                    print(f" 嘗試第 {attempt} 次失敗：{e}")
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                    else:
                        print(f" 最終失敗：{img_path}")

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(analyze_image, path) for path in img_paths]
            for _ in as_completed(futures):
                pass

    # 4. 回傳訊息與檔案路徑
    return jsonify({
        "status": "success",
        "message": "資料與圖片已下載並分析完成",
        "csv": csv_path,
        "analysis_csv": analysis_csv_path
    })



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5678, debug=True)
