import pysrt
import requests
import sys
import os
import re

# --- 設定 ---
OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_API_BASE}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_API_BASE}/api/tags"

def get_ollama_models():
    """獲取本地已安裝的 Ollama 模型清單"""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        response.raise_for_status()
        return [m['name'] for m in response.json().get('models', [])]
    except Exception:
        return []

def convert_s2t(text, model_name):
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system", 
                "content": "你是一個簡轉繁專家。請將輸入的簡體中文轉換為繁體中文。只輸出轉換後的文字，不要有任何解釋或註解。"
            },
            {"role": "user", "content": text}
        ],
        "stream": False,
        "options": {"temperature": 0.1}
    }
    try:
        r = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=30)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()
    except Exception:
        return text

def main():
    # 1. 選擇模型
    models = get_ollama_models()
    if not models:
        model_name = input("[!] 請輸入模型名稱: ").strip()
    else:
        print("\n已找到模型清單 (建議使用 Qwen 系列):")
        for idx, m in enumerate(models):
            print(f"  [{idx+1}] {m}")
        choice = input(f"請選擇模型 (1-{len(models)}) [預設 1]: ").strip()
        model_name = models[int(choice)-1] if choice.isdigit() and 1 <= int(choice) <= len(models) else models[0]
    
    print(f"[*] 使用模型: {model_name}")

    # 2. 處理路徑
    if len(sys.argv) < 2:
        path = input("\n請輸入要轉繁體的 SRT 路徑: ").strip().replace("'", "").replace('"', '')
    else:
        path = sys.argv[1].replace("'", "").replace('"', '')

    if not path or not os.path.exists(path):
        print("[!] 無效路徑")
        return

    # 3. 處理 SRT
    subs = pysrt.open(path, encoding='utf-8')
    
    # 移除原有的擴展名並加上 _zh_tw
    base = os.path.splitext(path)[0]
    # 移除可能存在的 _zh, .zh, -zh 或 _zh_tw 等標籤，避免重複
    clean_base = re.sub(r'[._-]zh(_tw)?$', '', base, flags=re.IGNORECASE)
    output_path = f"{clean_base}_zh_tw.srt"
    
    total = len(subs)
    print(f"[*] 正在進行純淨簡轉繁: {os.path.basename(path)}")
    
    try:
        for i, sub in enumerate(subs):
            # 只有包含中文時才進行轉換，節省資源
            if any('\u4e00' <= char <= '\u9fff' for char in sub.text):
                sub.text = convert_s2t(sub.text, model_name)
            
            if (i + 1) % 20 == 0 or (i + 1) == total:
                percent = (i + 1) / total * 100
                print(f"\r    進度: [{i+1}/{total}] ({percent:.1f}%)", end="")
                sys.stdout.flush()
                subs.save(output_path, encoding='utf-8')
                
    except KeyboardInterrupt:
        print(f"\n[!] 使用者中斷，已儲存目前進度。")
        subs.save(output_path, encoding='utf-8')
        sys.exit(0)

    print(f"\n[OK] 轉換完成！存檔至: {output_path}")

if __name__ == "__main__":
    main()
