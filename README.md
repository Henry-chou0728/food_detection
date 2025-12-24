# AI 智慧午餐助理系統流程圖

## 1. 數據採集與分析流程 (ETL Pipeline)
1. **Scrape (爬取)**: 
   - 啟動 Selenium 進入點餐系統。
   - 遍歷分頁，抓取餐點名稱、店家標題、價格及圖片 URL。
   - 將原始資料存入 `menu_items.csv`。
2. **Download (下載)**: 
   - 根據 URL 下載餐點圖片至本地資料夾。
3. **Analyze (AI 辨識)**: 
   - 調用 Gemini 2.5 Flash 模型，讀取圖片並對照檔名。
   - 根據衛福部標準推估每份餐點的組成與熱量。
   - 將分析結果儲存於 `analysis_result.csv`。
4. **Upload (雲端儲存)**: 
   - 將分析後的 CSV 數據上傳（或覆蓋）至 Google BigQuery 表格。

## 2. RAG 知識庫建立流程
1. **Data Ingestion (資料讀取)**: 
   - 從 BigQuery 讀取最新的餐點分析資料。
   - 從本地讀取 `食品營養成分資料庫2024UPDATE2.csv`。
2. **Embedding (向量化)**: 
   - 使用 `GoogleGenerativeAIEmbeddings` (models/embedding-001) 將文字轉為向量。
3. **Vector Store (存儲)**: 
   - 建立 FAISS 向量資料庫，並將餐點資料與營養成分資料進行合併（Merge）。

## 3. 使用者問答流程 (/ask_Q)
1. **Input (輸入)**: 使用者提出問題（例如：「明天星期二有什麼推薦的？」）。
2. **Contextualize (環境感知)**: 
   - 程式自動取得今日日期與星期。
   - 提取與該 `user_id` 相關的最近 20 則對話紀錄（Memory）。
3. **Prompt Engineering (指令工程)**: 
   - 將「時間、星期、對話紀錄、原始問題」封裝進 Prompt。
4. **Retrieval (檢索)**: 
   - 從 FAISS 資料庫中檢索出前 100 筆相關性最高的資料。
5. **Generation (生成)**: 
   - Gemini LLM 根據檢索到的菜單資訊與營養資料，產出繁體中文回覆。

## 4. 即時影像辨識流程 (/food_detection)
1. **Upload**: 使用者上傳一張食物照片。
2. **Vision Analysis**: Gemini 2.5 Pro 接收圖片並進行理性分析。
3. **Output**: 直接回傳食物清單、熱量評估與總熱量摘要。
