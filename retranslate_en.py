import pysrt
import requests
import os
import re
import sys

# --- 設定 ---
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

def contains_significant_english(text):
    """
    偵測是否包含顯著的英文內容。
    1. 完全沒中文且有英文。
    2. 有中文但英文單字數量超過 3 個（代表有漏翻的英文長句）。
    """
    clean_text = text.replace('\n', ' ')
    # 尋找英文單字（長度大於等於 2 的字母組合）
    english_words = re.findall(r'\b[a-zA-Z]{2,}\b', clean_text)
    
    if not has_chinese(text) and len(english_words) > 0:
        return True
    
    # 如果有中文，但英文單字超過 3 個，視為中英混雜漏翻
    if has_chinese(text) and len(english_words) >= 4:
        return True
        
    return False

def translate_line(text, model_name, context="", retry=0):
    clean_text = text.replace('\n', ' ').strip()
    
    system_prompt = "你是一個專業翻譯員。將輸入的內容（不論是全英或中英混雜）翻譯成自然流暢的中文。只需輸出翻譯結果，絕對不要保留英文句子。"
    
    if retry > 0:
        system_prompt = "請完全翻譯成中文，嚴禁在輸出中保留任何英文字母。只輸出中文。"

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
        r.raise_for_status()
        result = r.json().get("message", {}).get("content", "").strip()
        
        # 檢查結果是否仍然包含長英文
        if has_chinese(text) and contains_significant_english(result) and retry < 1:
            return translate_line(text, model_name, context, retry + 1)
            
        return result if result else text
    except Exception:
        return text

def main():
    models = get_ollama_models()
    if not models:
        model_name = input("[!] 請輸入模型名稱: ").strip()
    else:
        print("\n已找到模型清單:")
        for idx, m in enumerate(models):
            print(f"  [{idx+1}] {m}")
        choice = input(f"請選擇模型 (1-{len(models)}) [預設 1]: ").strip()
        model_name = models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]
    
    if len(sys.argv) < 2:
        path = input("\n請輸入 SRT 路徑: ").strip().replace("'", "").replace('"', '')
    else:
        path = sys.argv[1].replace("'", "").replace('"', '')

    if not path or not os.path.exists(path):
        print(f"[!] 找不到檔案: {path}")
        return

    try:
        subs = pysrt.open(path, encoding='utf-8')
    except:
        subs = pysrt.open(path, encoding='iso-8859-1')
        
    total = len(subs)
    count = 0
    print(f"[*] 正在掃描並修復漏翻/中英混雜行...")

    try:
        for i, sub in enumerate(subs):
            if contains_significant_english(sub.text):
                prev_text = subs[i-1].text.replace('\n', ' ') if i > 0 else ""
                next_text = subs[i+1].text.replace('\n', ' ') if i < total-1 else ""
                context = f"{prev_text} | {next_text}"
                
                print(f"\r    正在處理第 {i+1}/{total} 行...", end="")
                sys.stdout.flush()
                
                new_text = translate_line(sub.text, model_name, context)
                if new_text != sub.text:
                    sub.text = new_text
                    count += 1
                
                if count % 5 == 0:
                    subs.save(path, encoding='utf-8')

        subs.save(path, encoding='utf-8')
        print(f"\n[OK] 修復完成！共補翻/修正了 {count} 行。")
    except KeyboardInterrupt:
        print(f"\n[!] 使用者中止，已保存進度。")
        subs.save(path, encoding='utf-8')

if __name__ == "__main__":
    main()
