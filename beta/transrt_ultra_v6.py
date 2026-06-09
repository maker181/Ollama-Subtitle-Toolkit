import pysrt
import requests
import os
import re
import sys
import glob
import time
import select

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

def should_skip(text):
    t = text.strip()
    if not t or re.match(r'^[\d\s%:.，。,!?-]+$', t): return True
    if re.search(r'http[s]?://|www\.', t): return True
    return False

def clean_output(translated, original_text):
    if not translated: return original_text
    translated = re.sub(r"<think>.*?</think>", '', translated, flags=re.DOTALL)
    garbage = [r"^翻譯：", r"^翻譯結果：", r"^結果：", r"^Translation:", r"^精簡翻譯：", r"^台灣繁體：", r"^字幕：", r"^修改後：", r"^校稿："]
    for p in garbage:
        translated = re.sub(p, '', translated, flags=re.IGNORECASE)
    translated = translated.strip().strip('"').strip("'")
    return translated.strip()

# --- 核心翻譯功能 (單行純文字) ---
def translate_single_line(pure_text, model_name):
    if should_skip(pure_text): return pure_text
    system_prompt = (
        "You are a professional subtitle translator. "
        "Translate the following English subtitle line into Traditional Taiwan Chinese (台灣繁體中文).\n"
        "Requirements:\n"
        "1. Use natural Taiwan local terms and idioms.\n"
        "2. Output ONLY the translated text. NO explanations. NO notes."
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"English: {pure_text}\nTaiwanese Chinese:"}
        ],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 50, "stop": ["\n", "English:", "Note:"]}
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        translated = r.json().get("message", {}).get("content", "").strip()
        return clean_output(translated, pure_text)
    except: return pure_text

# --- 💡 核心改動：雙語校稿與修補功能 (Bilingual Review) ---
def proofread_single_line(pure_eng, pure_zh, model_name):
    """將英文原稿與中文譯文同時餵給 AI 進行校稿與修補"""
    if should_skip(pure_eng): return pure_zh
    
    system_prompt = (
        "You are an expert subtitle editor and proofreader. "
        "Compare the English source text with the provided Taiwan Chinese translation. "
        "Your task is to review, fix any missing translations (漏翻), correct mistranslations, "
        "and polish the text into fluent, natural Traditional Taiwan Chinese (台灣繁體中文).\n"
        "Rules:\n"
        "1. If the current translation is already accurate, natural, and correct, output the CURRENT translation EXACTLY.\n"
        "2. If there are missing parts, wrong words, or awkward phrasing, output the IMPROVED translation.\n"
        "3. Output ONLY the final Chinese text. NO explanations. NO notes."
    )
    
    user_content = f"English Source: {pure_eng}\nCurrent Translation: {pure_zh}\nPolished Taiwan Chinese:"
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "stream": False,
        "options": {
            "temperature": 0.2, # 給予校稿稍微多一點點的靈活性來潤飾語句
            "num_predict": 50,
            "stop": ["\n", "English Source:", "Note:", "Current Translation:"]
        }
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        reviewed = r.json().get("message", {}).get("content", "").strip()
        return clean_output(reviewed, pure_zh)
    except: return pure_zh

# --- 結構處理防護層 (支援翻譯與校稿) ---
def process_text_structure(eng_text, zh_text, model_name, mode="translate"):
    """
    mode="translate": 負責將 eng_text 翻譯
    mode="proofread": 負責將 eng_text 與 zh_text 進行雙語校稿
    """
    eng_lines = eng_text.split('\n')
    # 如果是校稿模式，中文也依換行拆分；若行數不對齊，則保險退回成跟英文同數量
    zh_lines = zh_text.split('\n') if zh_text else [""] * len(eng_lines)
    if len(zh_lines) != len(eng_lines):
        zh_lines = [zh_text] + [""] * (len(eng_lines) - 1)
        
    processed_lines = []
    
    for e_line, z_line in zip(eng_lines, zh_lines):
        if should_skip(e_line):
            processed_lines.append(z_line if mode == "proofread" else e_line)
            continue
            
        pure_eng = re.sub(r'<[^>]+>', '', e_line).strip()
        pure_zh = re.sub(r'<[^>]+>', '', z_line).strip() if z_line else ""
        
        if not pure_eng:
            processed_lines.append(z_line if mode == "proofread" else e_line)
            continue
            
        # 根據模式決定呼叫翻譯還是校稿
        if mode == "translate":
            final_china = translate_single_line(pure_eng, model_name)
        else:
            final_china = proofread_single_line(pure_eng, pure_zh, model_name)
            
        # 標籤還原機制
        match = re.match(r'^(<font [^>]+>)(.*)(</font>)$', e_line.strip(), re.IGNORECASE)
        if match:
            start_tag, _, end_tag = match.groups()
            processed_lines.append(f"{start_tag}{final_china}{end_tag}")
        else:
            processed_lines.append(final_china)
            
    return "\n".join(processed_lines)

# --- 10秒倒數計時器 ---
def ask_review_with_timeout(timeout=10):
    print(f"\n[?] 是否要啟動「AI 雙語智慧校稿與修補」？(會同時對照英中原文，修正漏翻與語意)")
    print(f"請在 {timeout} 秒內輸入 [y] 並按 Enter 同意，超時或直接按 Enter 將預設為 [n] 跳過...")
    rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    if rlist:
        user_input = sys.stdin.readline().strip().lower()
        if user_input == 'y':
            print("[已確認] 開始智慧校稿流程。")
            return 'y'
    print("[提示] 超時或未同意，自動選擇：[n] 跳過校稿。")
    return 'n'

# --- 流程一：全字幕翻譯 ---
def do_full_translation(file_path, model_name):
    base_name = os.path.splitext(file_path)[0]
    clean_name = re.sub(r'[._-]en$', '', base_name, flags=re.IGNORECASE)
    output_path = f"{clean_name}_zh_tw.srt"
    
    try: subs = pysrt.open(file_path, encoding='utf-8')
    except: subs = pysrt.open(file_path, encoding='iso-8859-1')
        
    total = len(subs)
    print(f"\n[*] 執行 [全翻譯]: {os.path.basename(file_path)}")
    
    translated_count = 0
    for i, sub in enumerate(subs):
        if should_skip(sub.text): continue
        new_text = process_text_structure(sub.text, None, model_name, mode="translate")
        if new_text != sub.text:
            sub.text = new_text
            translated_count += 1
            
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"\r    翻譯進度: [{i+1}/{total}] ({(i+1)/total*100:.1f}%) | 已翻譯: {translated_count} 行", end="", flush=sys.stdout)
        if (i + 1) % 100 == 0: subs.save(output_path, encoding='utf-8')
            
    subs.save(output_path, encoding='utf-8')
    print(f"\n[OK] 翻譯儲存成功：{os.path.basename(output_path)}")
    
    # 翻譯完，自動詢問是否接續進行雙語校稿
    choice = ask_review_with_timeout(10)
    if choice == 'y':
        do_bilingual_review(file_path, output_path, model_name)
    print("-" * 40)

# --- 流程二：雙語智慧校稿與修補 ---
def do_bilingual_review(eng_file_path, zh_tw_file_path, model_name):
    """
    同時讀取英文原檔與中文翻譯檔，逐行對照校稿
    """
    print(f"\n[*] 執行 [雙語智慧校稿]...")
    print(f"    英文原稿: {os.path.basename(eng_file_path)}")
    print(f"    中文譯文: {os.path.basename(zh_tw_file_path)}")
    
    try: eng_subs = pysrt.open(eng_file_path, encoding='utf-8')
    except: eng_subs = pysrt.open(eng_file_path, encoding='iso-8859-1')
        
    try: zh_subs = pysrt.open(zh_tw_file_path, encoding='utf-8')
    except: zh_subs = pysrt.open(zh_tw_file_path, encoding='iso-8859-1')
    
    if len(eng_subs) != len(zh_subs):
        print("❌ 錯誤：英文原檔與中文字幕檔的總行數不一致，無法進行精確對照校稿！")
        return
        
    total = len(zh_subs)
    review_count = 0
    
    for i in range(total):
        eng_sub = eng_subs[i]
        zh_sub = zh_subs[i]
        
        # 傳入英文原文與當前中文，讓 AI 進行評估校正
        polished_text = process_text_structure(eng_sub.text, zh_sub.text, model_name, mode="proofread")
        
        if polished_text != zh_sub.text:
            zh_sub.text = polished_text
            review_count += 1
            
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"\r    校稿進度: [{i+1}/{total}] ({(i+1)/total*100:.1f}%) | 已優化/修復: {review_count} 行", end="", flush=sys.stdout)
        if (i + 1) % 100 == 0: zh_subs.save(zh_tw_file_path, encoding='utf-8')
            
    zh_subs.save(zh_tw_file_path, encoding='utf-8')
    print(f"\n[OK] 校稿階段完成！本檔案共優化/修正了 {review_count} 行。")

def select_model():
    models = get_ollama_models()
    if not models: return input("[!] 未找到自動模型，請手動輸入模型名稱: ").strip()
    print("\n可用 Ollama 模型清單:")
    for idx, m in enumerate(models):
        flag = " (推薦使用)" if "breeze" in m.lower() else ""
        print(f"  [{idx+1}] {m}{flag}")
    choice = input(f"請選擇模型 (1-{len(models)}) [預設 1]: ").strip()
    return models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]

def main():
    print("============================================")
    print("   Ollama Subtitle Toolkit [ULTRA v6]       ")
    print("   新功能：AI 雙語對照校稿與智慧修補模式       ")
    print("============================================")
    current_model = select_model()
    
    while True:
        print("\n" + "="*45)
        print(f" 當前載入模型: {current_model}")
        print("="*45)
        print("  [1] 全字幕翻譯 + 智慧校稿 (自動輸出 _zh_tw.srt)")
        print("  [2] 獨立雙語校稿修補 (需提供英文原檔與中文檔)")
        print("  [3] 重新選擇 AI 模型")
        print("  [4] 結束並退出程式")
        print("-" * 45)
        
        choice = input("請選擇操作功能 (1-4): ").strip()
        if choice == '4':
            print("\n[DONE] 程式已安全結束。")
            break
        elif choice == '3':
            current_model = select_model()
            continue
        elif choice == '1':
            target_path = input(f"\n[全字幕翻譯] 請輸入或拖曳英文 SRT【檔案】或【資料夾】: ").strip().replace("'", "").replace('"', '')
            if not target_path or not os.path.exists(target_path): continue
            
            targets = [target_path] if os.path.isfile(target_path) else glob.glob(os.path.join(target_path, "*.srt"))
            targets = [f for f in targets if not (f.endswith('_zh_tw.srt') or f.endswith('_zh.srt'))]
            
            print(f"\n[+] 偵測到批量任務，共 {len(targets)} 個檔案準備處理...")
            for index, file_path in enumerate(targets):
                print(f"\n➔ 進度 [{index+1}/{len(targets)}]: {os.path.basename(file_path)}")
                try: do_full_translation(file_path, current_model)
                except KeyboardInterrupt: break
            print("\n🎉 該批次所有檔案處理結束！已自動返回主選單。")
            
        elif choice == '2':
            print("\n[獨立雙語校稿] 模式：")
            eng_path = input("1. 請輸入【英文原始】SRT 路徑: ").strip().replace("'", "").replace('"', '')
            zh_path = input("2. 請輸入【對應翻好】的中文 SRT 路徑: ").strip().replace("'", "").replace('"', '')
            
            if not os.path.exists(eng_path) or not os.path.exists(zh_path):
                print("❌ 錯誤：找不到指定的檔案路徑，返回主選選單。")
                continue
                
            try: do_bilingual_review(eng_path, zh_path, current_model)
            except KeyboardInterrupt: print("\n[!] 使用者中斷校稿。")
            print("\n🎉 校稿處理結束！已自動返回主選單。")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n\n[!] 程式已被強制中止。")
