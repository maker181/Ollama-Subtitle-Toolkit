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
TIMEOUT = 30  # 縮短超時，避免卡死

def get_ollama_models():
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        response.raise_for_status()
        return [m['name'] for m in response.json().get('models', [])]
    except Exception:
        return []

def has_chinese(text):
    return any('\u4e00' <= char <= '\u9fff' for char in text)

def should_skip(text):
    t = text.strip()
    if not t or re.match(r'^[\d\s%:.，。,!?-]+$', t): return True
    if re.search(r'http[s]?://|www\.', t): return True
    return False

def contains_significant_english(text):
    """精準判定是否需要修補：若有中文但英文單字過長，或完全沒中文且不是純符號"""
    if should_skip(text): return False
    clean_text = text.replace('\n', ' ')
    english_words = re.findall(r'\b[a-zA-Z]{3,}\b', clean_text) # 提升至3個字母以上才算單字，避開單字元
    
    # 過濾常見無需翻譯的專有名詞（可自行擴充）
    skip_words = {"iphone", "windows", "android", "cpu", "srt", "app", "pc", "os"}
    english_words = [w for w in english_words if w.lower() not in skip_words]

    if not has_chinese(text) and len(english_words) > 0: return True
    if has_chinese(text) and len(english_words) >= 4: return True
    return False

def clean_output(translated, original_text):
    if not translated: return original_text
    # 移除 DeepSeek 等模型的思考標籤
    translated = re.sub(r"<think>.*?</think>", '', translated, flags=re.DOTALL)
    # 移除 AI 常常忍不住加的開頭廢話
    garbage = [r"^翻譯：", r"^翻譯結果：", r"^結果：", r"^Translation:", r"^精簡翻譯："]
    for p in garbage:
        translated = re.sub(p, '', translated, flags=re.IGNORECASE)
    
    # 移除前後引號
    translated = translated.strip().strip('"').strip("'")
    
    # 幻覺過濾：如果輸出的中文長度是原文的 3 倍以上，且包含 AI 解釋常用詞，通常是翻車了
    if len(translated) > len(original_text) * 3 and any(w in translated for w in ["這句", "表達", "意思是", "脈絡", "根據"]):
        return original_text
        
    return translated.strip()

def translate_core(text, model_name, context="", is_retry=False):
    if should_skip(text): return text
    
    # 融合 fast 的填空填鴨式 Prompt + Traditional Taiwan constraints
    system_prompt = (
        "You are a professional subtitle translator. "
        "Translate English to Traditional Taiwan Chinese (台灣繁體中文). "
        "Use Taiwan local terms (e.g., 影片, 專案, 記憶體). "
        "Output ONLY the translation. NO explanations. NO notes."
    )
    
    clean_text = text.replace('\n', ' ')
    # 建立上下文語境，幫助 AI 理解
    user_msg = f"Context: {context}\nEnglish: {clean_text}\nTaiwanese Chinese:" if context else f"English: {clean_text}\nTaiwanese Chinese:"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "stream": False,
        "options": {
            "temperature": 0.0 if not is_retry else 0.2,  # 第一次用 0 追求最穩定，重試稍微給一點隨機度
            "num_predict": 60,   # 字幕通常不長，60 綽綽有餘，能強力止損
            "stop": ["\n", "English:", "Note:", "Context:", "Context"] # 嚴格阻斷 AI 的續寫
        }
    }
    
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        translated = r.json().get("message", {}).get("content", "").strip()
        cleaned = clean_output(translated, text)
        
        # 立即檢查：如果發現有嚴重的漏翻（中英混雜），且這不是重試
        if not is_retry and contains_significant_english(cleaned):
            # 就地發起一次微調重試
            return translate_core(text, model_name, context=context, is_retry=True)
            
        return cleaned if cleaned else text
    except Exception:
        return text

def process_ultra_v2(input_path, model_name):
    base_name = os.path.splitext(input_path)[0]
    clean_name = re.sub(r'[._-]en$', '', base_name, flags=re.IGNORECASE)
    output_path = f"{clean_name}_zh_tw.srt"
    
    try:
        subs = pysrt.open(input_path, encoding='utf-8')
    except:
        subs = pysrt.open(input_path, encoding='iso-8859-1')
    
    total = len(subs)
    print(f"\n[*] 開始單階段高效台灣繁體翻譯: {os.path.basename(input_path)}")
    
    # 上下文佇列（保留前兩行的【英文原文】，避免中文汙染語境）
    eng_context_queue = []
    fixed_count = 0

    try:
        for i, sub in enumerate(subs):
            current_context = " | ".join(eng_context_queue)
            original_text = sub.text.replace('\n', ' ')
            
            # 執行翻譯
            new_text = translate_core(sub.text, model_name, context=current_context)
            
            # 統計就地修正（或成功翻譯）的行數
            if new_text != sub.text:
                sub.text = new_text
                fixed_count += 1
            
            # 維護英文上下文佇列
            eng_context_queue.append(original_text)
            if len(eng_context_queue) > 2: 
                eng_context_queue.pop(0)
            
            # 進度條與即時存檔
            if (i + 1) % 10 == 0 or (i + 1) == total:
                percent = (i + 1) / total * 100
                print(f"\r    處理進度: [{i+1}/{total}] ({percent:.1f}%) | 已翻譯/修正: {fixed_count} 行", end="")
                sys.stdout.flush()
                
            if (i + 1) % 50 == 0: 
                subs.save(output_path, encoding='utf-8')
                
        subs.save(output_path, encoding='utf-8')
        print(f"\n[OK] 處理完成！結果已存至: {output_path}")
        
    except KeyboardInterrupt:
        print(f"\n[!] 使用者中止，正在保存已處理的進度...")
        subs.save(output_path, encoding='utf-8')
        sys.exit(0)

def main():
    print("============================================")
    print("   Ollama Subtitle Toolkit [ULTRA v2]       ")
    print("   特點：單階段就地修補、高精準阻斷、台灣用語    ")
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
        print(f"\n任務 {index+1}/{len(targets)}")
        process_ultra_v2(file_path, model_name)
        
    print("\n[DONE] 所有任務結束。")

if __name__ == "__main__":
    main()