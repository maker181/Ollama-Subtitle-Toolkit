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
    garbage = [r"翻譯結果：", r"结果：", r"Translation:", r"The translation is:"]
    for p in garbage:
        translated = re.sub(p, '', translated, flags=re.IGNORECASE)
    return translated.strip()

def contains_significant_english(text):
    clean_text = text.replace('\n', ' ')
    english_words = re.findall(r'\b[a-zA-Z]{2,}\b', clean_text)
    if not has_chinese(text) and len(english_words) > 0: return True
    if has_chinese(text) and len(english_words) >= 4: return True
    return False

# --- 核心處理函式 ---

def translate_fast(text, model_name, context="", retry=0):
    if should_skip(text): return text
    system_prompt = (
        "You are a professional translator. Translate English to Chinese.\n"
        "Rules:\n1. Translate EVERYTHING except brand names and people's names.\n"
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
        "options": {"temperature": 0.1, "num_predict": 100, "stop": ["\n", "Context:", "Translate:"]}
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        translated = r.json().get("message", {}).get("content", "").strip()
        cleaned = clean_output(translated, text)
        if re.search(r'[a-zA-Z]{4,}', text) and not has_chinese(cleaned) and retry < 1:
            return translate_fast(text, model_name, context, retry + 1)
        return cleaned if cleaned else text
    except Exception:
        return text

def translate_repair(text, model_name, context="", retry=0):
    clean_text = text.replace('\n', ' ').strip()
    system_prompt = "你是一個專業翻譯員。將輸入內容翻譯成自然流暢的中文。只需輸出翻譯結果，絕對不要保留英文。"
    if retry > 0: system_prompt = "請完全翻譯成中文，嚴禁保留任何英文字母。只輸出中文。"
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context: {context}\nTranslate: {clean_text}"}
        ],
        "stream": False,
        "options": {"temperature": 0.1, "stop": ["\n", "Context:", "Translate:"]}
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        result = r.json().get("message", {}).get("content", "").strip()
        if has_chinese(text) and contains_significant_english(result) and retry < 1:
            return translate_repair(text, model_name, context, retry + 1)
        return result if result else text
    except Exception:
        return text

def convert_s2t(text, model_name):
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一個簡轉繁專家。請將輸入的簡體中文轉換為繁體中文。只輸出轉換後的文字，不要有任何解釋。"},
            {"role": "user", "content": text}
        ],
        "stream": False,
        "options": {"temperature": 0.1}
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=30)
        return r.json().get("message", {}).get("content", "").strip()
    except Exception:
        return text

# --- 主流程 ---

def process_ultra(input_path, model_name):
    base_name = os.path.splitext(input_path)[0]
    clean_name = re.sub(r'[._-]en$', '', base_name, flags=re.IGNORECASE)
    output_path = f"{clean_name}_zh_tw.srt"
    
    # 讀取檔案
    try:
        subs = pysrt.open(input_path, encoding='utf-8')
    except:
        subs = pysrt.open(input_path, encoding='iso-8859-1')
    
    total = len(subs)
    
    # Phase 1: 高速初翻
    print(f"[*] 階段 1/3: 正在進行初步翻譯...")
    context_queue = []
    for i, sub in enumerate(subs):
        current_context = " | ".join(context_queue)
        original_text = sub.text.replace('\n', ' ')
        sub.text = translate_fast(sub.text, model_name, context=current_context)
        context_queue.append(original_text)
        if len(context_queue) > 2: context_queue.pop(0)
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"\r    初翻進度: [{i+1}/{total}]", end="")
            sys.stdout.flush()
    print("\n[OK] 初翻完成。")

    # Phase 2: 漏翻修補
    print(f"[*] 階段 2/3: 正在掃描並修復漏翻行...")
    repair_count = 0
    for i, sub in enumerate(subs):
        if contains_significant_english(sub.text):
            prev_text = subs[i-1].text.replace('\n', ' ') if i > 0 else ""
            next_text = subs[i+1].text.replace('\n', ' ') if i < total-1 else ""
            context = f"{prev_text} | {next_text}"
            new_text = translate_repair(sub.text, model_name, context)
            if new_text != sub.text:
                sub.text = new_text
                repair_count += 1
            print(f"\r    修復進度: [{i+1}/{total}] (已修復 {repair_count} 行)", end="")
            sys.stdout.flush()
    print("\n[OK] 修復完成。")

    # Phase 3: 簡轉繁
    print(f"[*] 階段 3/3: 正在進行純淨簡轉繁...")
    for i, sub in enumerate(subs):
        if any('\u4e00' <= char <= '\u9fff' for char in sub.text):
            sub.text = convert_s2t(sub.text, model_name)
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"\r    轉繁進度: [{i+1}/{total}]", end="")
            sys.stdout.flush()
    
    subs.save(output_path, encoding='utf-8')
    print(f"\n[ALL DONE] 全流程完成！檔案已儲存至: {output_path}")

def main():
    print("=== Ollama Subtitle Toolkit [ULTRA MODE] ===")
    models = get_ollama_models()
    if not models:
        model_name = input("[!] 請輸入模型名稱: ").strip()
    else:
        print("\n可用模型:")
        for idx, m in enumerate(models): print(f"  [{idx+1}] {m}")
        choice = input(f"請選擇模型 (1-{len(models)}) [預設 1]: ").strip()
        model_name = models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]
    
    target_path = input("\n請輸入 SRT 路徑 (檔案或資料夾): ").strip().replace("'", "").replace('"', '')
    if not target_path or not os.path.exists(target_path):
        print("[!] 路徑不存在。")
        return

    targets = [target_path] if not os.path.isdir(target_path) else [f for f in glob.glob(os.path.join(target_path, "*.srt")) if "_zh" not in f]

    for index, file_path in enumerate(targets):
        print(f"\n===== 任務 {index+1}/{len(targets)}: {os.path.basename(file_path)} =====")
        try:
            process_ultra(file_path, model_name)
        except KeyboardInterrupt:
            print("\n[!] 使用者中斷。")
            sys.exit(0)
        except Exception as e:
            print(f"\n[ERROR] 處理失敗: {e}")

if __name__ == "__main__":
    main()
