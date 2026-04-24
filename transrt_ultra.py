import pysrt
import requests
import os
import re
import sys
import glob

# --- 全域設定 ---
OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_API_BASE}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_API_BASE}/api/tags"
TIMEOUT = 45

def get_ollama_models():
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        response.raise_for_status()
        return [m['name'] for m in response.json().get('models', [])]
    except Exception:
        return []

def has_chinese(text):
    # 包含簡繁中文
    return any('\u4e00' <= char <= '\u9fff' for char in text)

def should_skip(text):
    t = text.strip()
    if not t: return True
    if re.match(r'^[\d\s%:.，。,!?-]+$', t): return True
    if re.search(r'http[s]?://|www\.', t): return True
    return False

def clean_output(translated, original_text):
    if not translated: return original_text
    translated = re.sub(r"<think>.*?</think>", '', translated, flags=re.DOTALL)
    garbage = [r"翻譯結果：", r"結果：", r"Translation:", r"The translation is:"]
    for p in garbage:
        translated = re.sub(p, '', translated, flags=re.IGNORECASE)
    return translated.strip()

def contains_significant_english(text):
    """檢查是否包含過多英文（可能漏翻）"""
    clean_text = text.replace('\n', ' ')
    english_words = re.findall(r'\b[a-zA-Z]{2,}\b', clean_text)
    if not has_chinese(text) and len(english_words) > 0: return True
    if has_chinese(text) and len(english_words) >= 4: return True
    return False

# --- 核心處理函式 (改為直接輸出台灣繁體) ---

def translate_core(text, model_name, context="", is_repair=False):
    if not is_repair and should_skip(text): return text
    
    # 強化的台灣繁體指令
    system_prompt = (
        "你是一位專業的翻譯官，負責將英文字幕翻譯成「台灣繁體中文」。\n"
        "規則：\n"
        "1. 必須使用台灣本地的語言習慣與詞彙風格。\n"
        "2. 嚴禁輸出簡體字，嚴禁在輸出中保留任何英文字句（人名除外）。\n"
        "3. 只輸出翻譯後的中文內容，不要有任何解釋。"
    )
    
    if is_repair:
        system_prompt += "\n注意：這行之前翻譯失敗或包含了英文，請務必完全轉換為純台灣繁體中文。"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context: {context}\nTranslate: {text}"}
        ],
        "stream": False,
        "options": {
            "temperature": 0.1, 
            "num_predict": 120, 
            "stop": ["\n", "Context:", "Translate:"]
        }
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        translated = r.json().get("message", {}).get("content", "").strip()
        cleaned = clean_output(translated, text)
        return cleaned if cleaned else text
    except Exception:
        return text

# --- 主流程 ---

def process_ultra(input_path, model_name):
    base_name = os.path.splitext(input_path)[0]
    clean_name = re.sub(r'[._-]en$', '', base_name, flags=re.IGNORECASE)
    output_path = f"{clean_name}_zh_tw.srt"
    
    try:
        subs = pysrt.open(input_path, encoding='utf-8')
    except:
        subs = pysrt.open(input_path, encoding='iso-8859-1')
    
    total = len(subs)
    
    # Phase 1: 高速翻譯 (直接繁體)
    print(f"[*] 階段 1/2: 正在進行台灣繁體翻譯...")
    context_queue = []
    for i, sub in enumerate(subs):
        current_context = " | ".join(context_queue)
        original_text = sub.text.replace('\n', ' ')
        
        sub.text = translate_core(sub.text, model_name, context=current_context)
        
        context_queue.append(original_text)
        if len(context_queue) > 2: context_queue.pop(0)
        
        if (i + 1) % 10 == 0 or (i + 1) == total:
            percent = (i + 1) / total * 100
            print(f"\r    翻譯進度: [{i+1}/{total}] ({percent:.1f}%)", end="")
            sys.stdout.flush()
            # 暫存避免意外
            if (i+1) % 100 == 0: subs.save(output_path, encoding='utf-8')
            
    print("\n[OK] 翻譯階段完成。")

    # Phase 2: 漏翻修補 (確保台灣繁體)
    print(f"[*] 階段 2/2: 正在掃描並修補漏翻/中英混雜行...")
    repair_count = 0
    for i, sub in enumerate(subs):
        if contains_significant_english(sub.text):
            prev_text = subs[i-1].text.replace('\n', ' ') if i > 0 else ""
            next_text = subs[i+1].text.replace('\n', ' ') if i < total-1 else ""
            context = f"{prev_text} | {next_text}"
            
            new_text = translate_core(sub.text, model_name, context, is_repair=True)
            if new_text != sub.text:
                sub.text = new_text
                repair_count += 1
                
            percent = (i + 1) / total * 100
            print(f"\r    修補進度: [{i+1}/{total}] ({percent:.1f}%) | 已修正: {repair_count}", end="")
            sys.stdout.flush()
            
    subs.save(output_path, encoding='utf-8')
    print(f"\n[ALL DONE] 全流程完成！共修補了 {repair_count} 行。")
    print(f"存檔路徑: {output_path}")

def main():
    print("============================================")
    print("   Ollama Subtitle Toolkit [ULTRA-FAST]     ")
    print("   目標：直接翻譯為台灣繁體中文用語           ")
    print("============================================")
    
    models = get_ollama_models()
    if not models:
        model_name = input("[!] 請輸入模型名稱: ").strip()
    else:
        print("\n可用模型清單:")
        for idx, m in enumerate(models): print(f"  [{idx+1}] {m}")
        choice = input(f"請選擇模型 (1-{len(models)}) [預設 1]: ").strip()
        model_name = models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]
    
    target_path = input("\n請輸入 SRT 路徑 (檔案或資料夾): ").strip().replace("'", "").replace('"', '')
    if not target_path or not os.path.exists(target_path):
        print("[!] 找不到路徑。")
        return

    targets = [target_path] if not os.path.isdir(target_path) else [f for f in glob.glob(os.path.join(target_path, "*.srt")) if "_zh" not in f]

    for index, file_path in enumerate(targets):
        print(f"\n任務 {index+1}/{len(targets)}: {os.path.basename(file_path)}")
        try:
            process_ultra(file_path, model_name)
        except KeyboardInterrupt:
            print("\n[!] 使用者中斷。")
            sys.exit(0)

if __name__ == "__main__":
    main()
