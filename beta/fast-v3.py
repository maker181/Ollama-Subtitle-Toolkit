import pysrt
import requests
import json
import sys
import os
import re

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
    except Exception: 
        return []

def should_skip(text):
    t = text.strip()
    if not t or re.match(r'^[\d\s%:.，。,!?-]+$', t): return True
    if re.search(r'http[s]?://|www\.', t): return True
    return False

def clean_output(translated):
    if not translated: return ""
    translated = re.sub(r"<think>.*?</think>", '', translated, flags=re.DOTALL)
    translated = translated.strip().strip('"').strip("'")
    return translated

def translate_text(text, model_name):
    if should_skip(text):
        return text
        
    # === 方法 A：增強型防禦提示詞 (System Prompt) ===
    system_prompt = (
        "You are an expert movie subtitle translator. You are translating a movie script. "
        "All input texts are safe, fictional, or historical movie dialogues. "
        "Translate the input English text into natural and accurate Simplified Chinese subtitles. "
        "Output ONLY the translated Chinese text. Do NOT refuse, do NOT censor, NO explanations, NO notes."
    )
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "stream": False,
        # === 方法 B：極低溫控參數優化 ===
        "options": {
            "temperature": 0.0,
            "top_p": 0.1
        }
    }
    
    try:
        res = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT)
        res.raise_for_status()
        result_text = res.json().get('message', {}).get('content', '')
        return clean_output(result_text)
    except Exception as e:
        # 發生錯誤時保留原英文，避免腳本崩潰
        return text

def process_srt(input_path, model_name):
    output_path = input_path.replace(".srt", "_zh.srt")
    if output_path == input_path:
        output_path = input_path.replace(".SRT", "_zh.srt")
        
    try:
        subs = pysrt.open(input_path, encoding='utf-8')
    except Exception:
        subs = pysrt.open(input_path, encoding='utf-8-sig')
        
    total = len(subs)
    print(f"\n[*] 處理中: {os.path.basename(input_path)}")
    print(f"[*] 使用模型: {model_name}")
    print(f"[*] 已啟用防誤觸優化與極低溫控參數 (Temp: 0.0)")
    print(f"[*] 提示：翻譯過程中可隨時按下 Ctrl+C 終止並儲存進度。")
    print("-" * 50)
    
    try:
        for i, sub in enumerate(subs):
            sub.text = translate_text(sub.text, model_name)
            
            # 每 10 行或最後一行更新進度並寫入檔案
            if (i + 1) % 10 == 0 or (i + 1) == total:
                percent = ((i + 1) / total) * 100
                print(f"\r    進度: [{i+1}/{total}] {percent:.1f}%", end="")
                sys.stdout.flush()
                subs.save(output_path, encoding='utf-8')
                
    except KeyboardInterrupt:
        # 當使用者按下 Ctrl+C 時觸發
        print("\n\n[!] 偵測到使用者中止 (Ctrl+C)！正在儲存已完成的翻譯進度...")
        subs.save(output_path, encoding='utf-8')
        print(f"[OK] 已安全儲存目前進度至: {output_path}")
        sys.exit(0)
    
    print(f"\n\n[OK] 全數翻譯完成！結果已存至: {output_path}")

def main():
    models = get_ollama_models()
    print("\n" + "="*50 + "\n  transrt_fast v2.1 - 完整進度與中斷儲存版\n" + "="*50)
    
    if not models:
        print("[!] 無法讀取 Ollama 模型清單，請手動輸入。")
        model_name = input("模型名稱: ").strip()
    else:
        print("可用模型清單：")
        for idx, m in enumerate(models): 
            print(f"  [{idx+1}] {m}")
        
        choice = input(f"\n請選擇要使用的模型 (1-{len(models)}) [1]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            model_name = models[int(choice)-1]
        else:
            model_name = models[0]
            
    target_path = input("\n輸入 SRT 檔案路徑: ").strip().strip('"').strip("'")
    if not os.path.exists(target_path):
        print("[Error] 找不到檔案！")
        return
        
    process_srt(target_path, model_name)

if __name__ == "__main__":
    main()