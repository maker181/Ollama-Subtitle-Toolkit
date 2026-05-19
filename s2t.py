import os
import sys
import re
import glob
import pysrt
from opencc import OpenCC


def convert_file(clean_path, cc):
    """處理單一檔案的轉換邏輯"""
    # 檢查是否已經是轉好的檔案，避免重複處理
    if clean_path.endswith('.zh-tw.srt'):
        return

    print(f"\n[*] 正在處理檔案: {os.path.basename(clean_path)}")

    # 讀取 SRT 檔案（相容 UTF-8 與基本 ANSI 舊編碼）
    try:
        subs = pysrt.open(clean_path, encoding='utf-8')
    except UnicodeDecodeError:
        try:
            subs = pysrt.open(clean_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            try:
                subs = pysrt.open(clean_path, encoding='gbk')
            except Exception:
                print(f"❌ 無法讀取檔案（編碼不支援）: {clean_path}")
                return

    # 檔名正規化處理，將舊有的格式清乾淨，統一換成 .zh-tw.srt
    base = os.path.splitext(clean_path)[0]
    clean_base = re.sub(r'[._-]zh([-_]tw)?$', '', base, flags=re.IGNORECASE)
    output_path = f"{clean_base}.zh-tw.srt"

    # 逐行轉換字幕
    total = len(subs)
    for i, sub in enumerate(subs):
        if any('\u4e00' <= char <= '\u9fff' for char in sub.text):
            sub.text = cc.convert(sub.text)

        # 輸出進度條
        if (i + 1) % 50 == 0 or (i + 1) == total:
            percent = (i + 1) / total * 100
            print(f"\r  進度: [{i+1}/{total}] ({percent:.1f}%)", end="")
            sys.stdout.flush()

    # 儲存新檔案
    subs.save(output_path, encoding='utf-8')
    print(f"\n✅ 轉換成功！已儲存至：{os.path.basename(output_path)}")


def main():
    print("=" * 60)
    print("    SRT 字幕簡轉繁工具 (支援單檔/資料夾批量拖曳 & 台灣用語)")
    print("=" * 60)

    # 獲取路徑
    if len(sys.argv) < 2:
        user_input = input("請輸入或「直接拖曳」SRT 檔案或【資料夾】進來，然後按 Enter：")
    else:
        user_input = sys.argv[1]

    # 清理路徑引號
    target_path = user_input.strip().replace("'", "").replace('"', '')

    if not target_path or not os.path.exists(target_path):
        print(f"\n❌ 錯誤：找不到指定的路徑：{target_path}")
        return

    # 初始化 OpenCC
    cc = OpenCC('s2twp')

    # 判斷是資料夾還是單一檔案
    if os.path.isdir(target_path):
        print(f"\n[+] 偵測到資料夾，開始批量搜尋 SRT 檔案...")
        # 搜尋資料夾下所有 .srt 檔案（不分大小寫）
        srt_files = glob.glob(os.path.join(target_path, "*.[sS][rR][tT]"))
        
        # 過濾掉本來就已經是 .zh-tw.srt 的檔案
        srt_files = [f for f in srt_files if not f.endswith('.zh-tw.srt')]

        if not srt_files:
            print("總結：資料夾內沒有找到需要轉換的簡體 .srt 檔案。")
            return

        print(f"共找到 {len(srt_files)} 個 SRT 檔案，開始依序處理：")
        for file_path in srt_files:
            try:
                convert_file(file_path, cc)
                print("-" * 40)
            except Exception as e:
                print(f"\n❌ 處理 {os.path.basename(file_path)} 時發生錯誤: {e}")
        print("\n🎉 所有檔案批量轉換完成！")

    elif os.path.isfile(target_path):
        convert_file(target_path, cc)
    else:
        print("❌ 未知的路徑類型")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] 使用者已中斷操作。")
    except Exception as e:
        print(f"\n❌ 發生未預期的錯誤: {e}")

    print("\n" + "=" * 60)
    input("按任意鍵結束視窗...")