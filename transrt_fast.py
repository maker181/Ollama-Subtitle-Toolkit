import pysrt
import requests
import json
import sys
import os
import re
import glob

# --- 設定區域 ---
OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_API_BASE}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_API_BASE}/api/tags"
TIMEOUT = 30 

def get_ollama_models():
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        response.raise_for_status()
        return [m['name'] for m in response.json().get('models', [])]
    except Exception: return []

def has_chinese(text):
    return any('\u4e00' <= char <= '\u9fff' for char in text)

def should_skip(text):
    t = text.strip()
    if not t or re.match(r'^[\d\s%:.，。,!?-]+$', t): return True
    if re.search(r'http[s]?://|www\.', t): return True
    return False

def clean_output(translated):
    if not translated: return ""
    # 移除思考過程與引號
    translated = re.sub(r"<think>.*?</think>", '', translated, flags=re.DOTALL)
    translated = translated.strip().strip('"').strip("'")
    
    # 如果輸出包含「根據、輸入、對話」等 AI 常用的分析詞彙且長度過長，可能是廢話
    if len(translated) > 50 and any(w in translated for w in ["輸入", "內容", "對話", "可能是", "根據"]):
        # 嘗試只取第一句
        translated = translated.split('。')[0] + '。'
            
    return translated.strip()

def translate_text(text, model_name, retry=0):
    if should_skip(text): return text
    
    # 強力限制：只准翻譯，不准廢話
    system_prompt = "You are a professional subtitle translator. Translate English to Chinese. Output ONLY the translation. NO explanations. NO notes."
    
    # 使用填空格式，並將原文的換行轉成空格，確保輸出也是單行
    clean_text = text.replace('\n', ' ')
    user_msg = f"English: {clean_text}\nChinese:"
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,  # 設為 0 最穩定，不會有幻覺
            "num_predict": 50,   # 限制輸出長度
            "stop": ["\n", "English:", "Note:"] # 只要換行就立刻停止，防止輸出分析
        }
    }
    
    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        result = response.json()
        translated = result.get("message", {}).get("content", "").strip()
        cleaned = clean_output(translated)
        
        # 漏翻檢查
        if not cleaned and retry < 1:
            return translate_text(text, model_name, retry + 1)
        
        return cleaned if cleaned else text
    except: return text

def process_srt(input_path, model_name):
    base_name = os.path.splitext(input_path)[0]
    output_path = f"{re.sub(r'[._-]en$', '', base_name, flags=re.IGNORECASE)}_zh.srt"
    
    try:
        subs = pysrt.open(input_path, encoding='utf-8')
    except:
        subs = pysrt.open(input_path, encoding='iso-8859-1')
        
    total = len(subs)
    print(f"\n[*] 處理中: {os.path.basename(input_path)}")
    
    try:
        for i, sub in enumerate(subs):
            sub.text = translate_text(sub.text, model_name)
            
            if (i + 1) % 10 == 0 or (i + 1) == total:
                percent = ((i + 1) / total) * 100
                print(f"\r    進度: [{i+1}/{total}] {percent:.1f}%", end="")
                sys.stdout.flush()
                subs.save(output_path, encoding='utf-8')
                
    except KeyboardInterrupt:
        subs.save(output_path, encoding='utf-8')
        sys.exit(0)
    
    print(f"\n[OK] 完成！結果已存至: {output_path}")

def main():
    models = get_ollama_models()
    print("\n" + "="*40 + "\n  transrt_fast - 穩定填空版\n" + "="*40)
    
    if not models:
        model_name = input("模型名稱: ").strip()
    else:
        for idx, m in enumerate(models): print(f"  [{idx+1}] {m}")
        choice = input(f"選擇模型 (1-{len(models)}) [1]: ").strip()
        model_name = models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]
    
    target_path = input("\n輸入 SRT 路徑: ").strip().replace("'", "").replace('"', '')
    if not target_path or not os.path.exists(target_path): return

    targets = [target_path] if os.path.isfile(target_path) else glob.glob(os.path.join(target_path, "*.srt"))
    targets = [f for f in targets if "_zh" not in f]

    for file_path in targets:
        process_srt(file_path, model_name)
    print("\n[DONE] 任務結束。")

if __name__ == "__main__":
    main()
