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
TIMEOUT = 45 

def get_ollama_models():
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        response.raise_for_status()
        models = [m['name'] for m in response.json().get('models', [])]
        return models
    except Exception:
        return []

def has_chinese(text):
    # 包含簡體與繁體的範圍
    return any('\u4e00' <= char <= '\u9fff' for char in text)

def should_skip(text):
    t = text.strip()
    if not t: return True
    if re.match(r'^[\d\s%:.，。,!?-]+$', t): return True
    if re.search(r'http[s]?://|www\.', t): return True
    return False

def clean_output(translated, original_text):
    if not translated: return original_text
    # 移除 <think> 或 AI 的廢話
    translated = re.sub(r"<think>.*?</think>", '', translated, flags=re.DOTALL)
    # 移除常見的 AI 前綴語
    garbage = [r"翻譯結果：", r"结果：", r"Translation:", r"The translation is:"]
    for p in garbage:
        translated = re.sub(p, '', translated, flags=re.IGNORECASE)
    return translated.strip()

def translate_text(text, model_name, context="", retry=0):
    if should_skip(text): return text
    
    # 既然接受簡體，指令極簡化，效果反而更好
    system_prompt = (
        "You are a professional translator. Translate English to Chinese.\n"
        "Rules:\n"
        "1. Translate EVERYTHING except brand names and people's names.\n"
        "2. No English verbs or fragments should remain in the output.\n"
        "3. Output ONLY the translated Chinese text."
    )
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context: {context}\nTranslate: {text}"}
        ],
        "stream": False,
        "options": {
            "temperature": 0.1, 
            "num_predict": 100, 
            "stop": ["\n", "Context:", "Translate:"]
        }
    }
    
    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        result = response.json()
        translated = result.get("message", {}).get("content", "").strip()
        cleaned = clean_output(translated, text)
        
        # 檢查是否漏翻（有英文字母但沒中文）
        if re.search(r'[a-zA-Z]{4,}', text) and not has_chinese(cleaned) and retry < 1:
            return translate_text(text, model_name, context, retry + 1)
        
        return cleaned if cleaned else text
    except Exception:
        return text

def process_srt(input_path, model_name):
    base_name = os.path.splitext(input_path)[0]
    # 同樣處理檔名 en 的問題
    clean_name = re.sub(r'[._-]en$', '', base_name, flags=re.IGNORECASE)
    output_path = f"{clean_name}_zh.srt" # 改為 _zh 代表中文
    
    try:
        subs = pysrt.open(input_path, encoding='utf-8')
    except:
        subs = pysrt.open(input_path, encoding='iso-8859-1')
        
    total = len(subs)
    print(f"\n[*] 正在處理 (高效簡體/繁體版): {os.path.basename(input_path)}")
    
    context_queue = []
    
    try:
        for i, sub in enumerate(subs):
            current_context = " | ".join(context_queue)
            original_text = sub.text.replace('\n', ' ')
            
            sub.text = translate_text(sub.text, model_name, context=current_context)
            
            context_queue.append(original_text)
            if len(context_queue) > 2: context_queue.pop(0)
            
            if (i + 1) % 10 == 0 or (i + 1) == total:
                percent = (i + 1) / total * 100
                print(f"\r    進度: [{i+1}/{total}] ({percent:.1f}%) 翻譯中...", end="")
                sys.stdout.flush()
                subs.save(output_path, encoding='utf-8')
                
    except KeyboardInterrupt:
        print(f"\n[!] 使用者中斷。")
        subs.save(output_path, encoding='utf-8')
        sys.exit(0)
    
    print(f"\n[OK] 檔案翻譯完成！")

def main():
    models = get_ollama_models()
    if not models:
        model_name = input("[!] 請輸入模型名稱: ").strip()
    else:
        print("\n已找到模型清單:")
        for idx, m in enumerate(models): print(f"  [{idx+1}] {m}")
        choice = input(f"請選擇模型 (1-{len(models)}) [預設 1]: ").strip()
        model_name = models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]
    
    target_path = input("\n請輸入 SRT 檔案或資料夾路徑: ").strip().replace("'", "").replace('"', '')
    if not target_path or not os.path.exists(target_path): return

    targets = [target_path] if not os.path.isdir(target_path) else [f for f in glob.glob(os.path.join(target_path, "*.srt")) if "_zh" not in f]

    for index, file_path in enumerate(targets):
        print(f"\n===== 任務 {index+1}/{len(targets)} =====")
        process_srt(file_path, model_name)
    print("\n[DONE] 所有任務已完成！")

if __name__ == "__main__":
    main()
