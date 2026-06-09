import pysrt
import requests
import os
import re
import sys
import glob
import time
import select  # Linux/Unix 通用的非阻塞輸入檢查

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

def contains_significant_english(text):
    if should_skip(text): return False
    clean_text = re.sub(r'<[^>]+>', '', text).replace('\n', ' ')
    english_words = re.findall(r'\b[a-zA-Z]{3,}\b', clean_text)
    skip_words = {"iphone", "windows", "android", "cpu", "srt", "app", "pc", "os"}
    english_words = [w for w in english_words if w.lower() not in skip_words]
    if not has_chinese(text) and len(english_words) > 0: return True
    if has_chinese(text) and len(english_words) >= 4: return True
    return False

def clean_output(translated, original_text):
    if not translated: return original_text
    translated = re.sub(r"<think>.*?</think>", '', translated, flags=re.DOTALL)
    
    garbage = [r"^翻譯：", r"^翻譯結果：", r"^結果：", r"^Translation:", r"^精簡翻譯：", r"^台灣繁體：", r"^字幕："]
    for p in garbage:
        translated = re.sub(p, '', translated, flags=re.IGNORECASE)
    
    translated = translated.strip().strip('"').strip("'")
    if len(translated) > len(original_text) * 3 and any(w in translated for w in ["這句", "表達", "意思是", "脈絡", "根據"]):
        return original_text
    return translated.strip()

def translate_single_line(pure_text, model_name, is_repair=False):
    if should_skip(pure_text): return pure_text
    
    system_prompt = (
        "You are a professional subtitle translator. "
        "Translate the following English subtitle line into Traditional Taiwan Chinese (台灣繁體中文).\n"
        "Requirements:\n"
        "1. Use natural Taiwan local terms and idioms.\n"
        "2. Output ONLY the translated text. NO explanations. NO notes."
    )
    if is_repair:
        system_prompt += "\n3. Crucial: The previous translation failed. You MUST output PURE Traditional Taiwan Chinese now."

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"English: {pure_text}\nTaiwanese Chinese:"}
        ],
        "stream": False,
        "options": {
            "temperature": 0.0 if not is_repair else 0.3,
            "num_predict": 50,
            "stop": ["\n", "English:", "Note:", "Requirements:"]
        }
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        translated = r.json().get("message", {}).get("content", "").strip()
        return clean_output(translated, pure_text)
    except Exception:
        return pure_text

def translate_core(text, model_name, is_repair=False):
    if should_skip(text): return text
    lines = text.split('\n')
    translated_lines = []
    
    for line in lines:
        if should_skip(line):
            translated_lines.append(line)
            continue
            
        pure_text = re.sub(r'<[^>]+>', '', line).strip()
        if not pure_text:
            translated_lines.append(line)
            continue
            
        china_text = translate_single_line(pure_text, model_name, is_repair)
        
        match = re.match(r'^(<font [^>]+>)(.*)(</font>)$', line.strip(), re.IGNORECASE)
        if match:
            start_tag, _, end_tag = match.groups()
            translated_lines.append(f"{start_tag}{china_text}{end_tag}")
        else:
            translated_lines.append(china_text)
            
    return "\n".join(translated_lines)

# --- 核心改動：跨平台/Linux 專用倒數計時器 ---
def ask_repair_with_timeout(timeout=10):
    print(f"\n[?] 是否要掃描並修補可能漏翻或中英混雜的行數？")
    print(f"請在 {timeout} 秒內輸入 [y] 並按 Enter 同意，超時或直接按 Enter 將預設為 [n] 跳過...")
    
    # 使用 select 監聽標準輸入 (stdin)
    rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    
    if rlist:
        # 代表使用者有輸入東西並按了 Enter
        user_input = sys.stdin.readline().strip().lower()
        if user_input == 'y':
            print("[已確認] 開始修補流程。")
            return 'y'
    
    print("[提示] 超時或未同意，自動選擇：[n] 跳過修補。")
    return 'n'

# --- 核心流程：全翻譯 ---
def do_full_translation(file_path, model_name):
    base_name = os.path.splitext(file_path)[0]
    clean_name = re.sub(r'[._-]en$', '', base_name, flags=re.IGNORECASE)
    output_path = f"{clean_name}_zh_tw.srt"
    
    try:
        subs = pysrt.open(file_path, encoding='utf-8')
    except:
        subs = pysrt.open(file_path, encoding='iso-8859-1')
        
    total = len(subs)
    print(f"\n[*] 執行 [全翻譯]: {os.path.basename(file_path)}")
    
    translated_count = 0
    for i, sub in enumerate(subs):
        if should_skip(sub.text): continue
        new_text = translate_core(sub.text, model_name, is_repair=False)
        if new_text != sub.text:
            sub.text = new_text
            translated_count += 1
            
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"\r    翻譯進度: [{i+1}/{total}] ({(i+1)/total*100:.1f}%) | 已翻譯: {translated_count} 行", end="", flush=sys.stdout)
        if (i + 1) % 100 == 0: subs.save(output_path, encoding='utf-8')
            
    subs.save(output_path, encoding='utf-8')
    print(f"\n[OK] 翻譯儲存成功：{os.path.basename(output_path)}")
    
    choice = ask_repair_with_timeout(10)
    if choice == 'y':
        do_repair_only(output_path, model_name, called_from_full=True)
    print("-" * 40)

# --- 核心流程：僅漏翻檢查與修補 ---
def do_repair_only(file_path, model_name, called_from_full=False):
    try:
        subs = pysrt.open(file_path, encoding='utf-8')
    except:
        subs = pysrt.open(file_path, encoding='iso-8859-1')
        
    total = len(subs)
    if not called_from_full:
        print(f"\n[*] 執行 [獨立漏翻檢查修補]: {os.path.basename(file_path)}")
        
    repair_count = 0
    for i, sub in enumerate(subs):
        if contains_significant_english(sub.text):
            re_translated = translate_core(sub.text, model_name, is_repair=True)
            if re_translated != sub.text:
                sub.text = re_translated
                repair_count += 1
                
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"\r    修補進度: [{i+1}/{total}] ({(i+1)/total*100:.1f}%) | 已修復: {repair_count} 行", end="", flush=sys.stdout)
            
    subs.save(file_path, encoding='utf-8')
    print(f"\n[OK] 修補完成！本檔案共修正了 {repair_count} 行。")

def select_model():
    models = get_ollama_models()
    if not models:
        return input("[!] 未找到自動模型，請手動輸入模型名稱: ").strip()
    print("\n可用 Ollama 模型清單:")
    for idx, m in enumerate(models):
        flag = " (推薦使用)" if "breeze" in m.lower() else ""
        print(f"  [{idx+1}] {m}{flag}")
    choice = input(f"請選擇模型 (1-{len(models)}) [預設 1]: ").strip()
    return models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]

def get_target_files(target_path, mode):
    if os.path.isfile(target_path):
        return [target_path]
    elif os.path.isdir(target_path):
        all_srts = glob.glob(os.path.join(target_path, "*.srt"))
        if mode == 1:
            return [f for f in all_srts if not (f.endswith('_zh_tw.srt') or f.endswith('_zh.srt'))]
        else:
            return all_srts
    return []

def main():
    print("============================================")
    print("   Ollama Subtitle Toolkit [ULTRA v5.1]     ")
    print("   修正：Linux 環境相容、防跳行、格式強固化     ")
    print("============================================")
    
    current_model = select_model()
    
    while True:
        print("\n" + "="*45)
        print(f" 當前載入模型: {current_model}")
        print("="*45)
        print("  [1] 全字幕翻譯 (自動輸出 _zh_tw.srt)")
        print("  [2] 獨立漏翻檢查與修補 (覆寫原檔/指定檔)")
        print("  [3] 重新選擇 AI 模型")
        print("  [4] 結束並退出程式")
        print("-" * 45)
        
        choice = input("請選擇操作功能 (1-4): ").strip()
        if choice == '4':
            print("\n[DONE] 感謝使用，程式已安全結束。")
            break
        elif choice == '3':
            current_model = select_model()
            continue
        elif choice in ('1', '2'):
            mode = int(choice)
            mode_title = "全字幕翻譯" if mode == 1 else "獨立漏翻檢查"
            
            target_path = input(f"\n[{mode_title}] 請輸入或拖曳 SRT【檔案】或【資料夾】: ").strip().replace("'", "").replace('"', '')
            if not target_path or not os.path.exists(target_path):
                print("[!] 找不到指定的路徑，請重新輸入。")
                continue
                
            targets = get_target_files(target_path, mode)
            if not targets:
                print("[!] 資料夾內沒有找到符合條件的 .srt 檔案。")
                continue
                
            print(f"\n[+] 偵測到批量任務，共 {len(targets)} 個檔案準備處理...")
            for index, file_path in enumerate(targets):
                print(f"\n➔ 進度 [{index+1}/{len(targets)}]: {os.path.basename(file_path)}")
                try:
                    if mode == 1: do_full_translation(file_path, current_model)
                    elif mode == 2: do_repair_only(file_path, current_model)
                except KeyboardInterrupt:
                    print("\n[!] 使用者中斷當前檔案，即將返回主選單...")
                    break
            print("\n🎉 該批次所有檔案處理結束！已自動返回主選單。")
        else:
            print("[!] 輸入錯誤，請輸入 1 到 4 的數字。")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n\n[!] 程式已被強制中止。")
