import os
import sys
import re
import pysrt
from opencc import OpenCC


def convert_srt_s2twp(input_file_path):
    """將輸入的簡體 SRT 檔案透過 OpenCC 轉換為台灣習慣用語之繁體中文。"""
    # 1. 移除拖曳檔案時，系統自動帶入的首尾單引號或雙引號
    clean_path = input_file_path.strip().replace("'", "").replace('"', "")

    # 檢查檔案是否存在
    if not clean_path or not os.path.exists(clean_path):
        print(f"\n❌ 錯誤：找不到指定的檔案路徑：{clean_path}")
        return

    print(f"\n[*] 正在處理檔案: {os.path.basename(clean_path)}")

    # 2. 初始化 OpenCC 台灣常用詞彙組態 (如：视频 -> 影片)
    cc = OpenCC("s2twp")

    # 3. 讀取 SRT 檔案（相容 UTF-8 與基本 ANSI 舊編碼）
    try:
        subs = pysrt.open(clean_path, encoding="utf-8")
    except UnicodeDecodeError:
        try:
            subs = pysrt.open(clean_path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            subs = pysrt.open(clean_path, encoding="gbk")  # 備用簡體編碼

    # 4. 檔名正規化處理，避免出現 .zh_tw_tw_tw.srt 的疊加情況
    base = os.path.splitext(clean_path)[0]
    clean_base = re.sub(r"[._-]zh(_tw)?$", "", base, flags=re.IGNORECASE)
    output_path = f"{clean_base}_zh_tw.srt"

    # 5. 逐行轉換字幕
    total = len(subs)
    for i, sub in enumerate(subs):
        # 只有包含中文時才進行轉換，節省資源
        if any("\u4e00" <= char <= "\u9fff" for char in sub.text):
            sub.text = cc.convert(sub.text)

        # 輸出進度條
        if (i + 1) % 50 == 0 or (i + 1) == total:
            percent = (i + 1) / total * 100
            print(f"\r  進度: [{i+1}/{total}] ({percent:.1f}%)", end="")
            sys.stdout.flush()

    # 6. 儲存新檔案
    subs.save(output_path, encoding="utf-8")
    print(f"\n✅ 轉換成功！新檔案已儲存至：\n   {output_path}\n")


if __name__ == "__main__":
    print("=" * 60)
    print("        SRT 字幕簡轉繁工具 (支援台灣用語轉換 & 檔案拖曳)")
    print("=" * 60)

    # 支援兩種使用方式：
    # 1. 直接把檔案拖到腳本圖示上開啟（透過 sys.argv 傳入參數）
    # 2. 先執行腳本，再把檔案拖進終端機視窗
    if len(sys.argv) < 2:
        file_path = input("請輸入或「直接拖曳」SRT 檔案進來，然後按 Enter：")
    else:
        file_path = sys.argv[1]

    try:
        convert_srt_s2twp(file_path)
    except KeyboardInterrupt:
        print("\n[!] 使用者已中斷操作。")
    except Exception as e:
        print(f"\n❌ 發生未預期的錯誤: {e}")

    # 防止雙擊執行時視窗一閃而過
    input("按任意鍵結束...")