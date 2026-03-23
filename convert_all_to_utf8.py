# convert_all_to_utf8.py
import os
import chardet  # 文字コード判定用ライブラリ
import sys

root_dir = "Bot"  # Bot 配下の全ファイルを対象

for subdir, _, files in os.walk(root_dir):
    for f in files:
        if f.endswith(".py"):
            file_path = os.path.join(subdir, f)
            with open(file_path, "rb") as file:
                raw = file.read()
                result = chardet.detect(raw)
                encoding = result['encoding']
                confidence = result['confidence']
                # 判定に自信が低ければ警告
                if not encoding or confidence < 0.8:
                    print(f"[WARNING] {file_path} 文字コード判定に自信なし: {encoding} ({confidence})")
                    continue
                if encoding.lower() != "utf-8":
                    print(f"[CONVERT] {file_path} ({encoding} → UTF-8)")
                    text = raw.decode(encoding)
                    with open(file_path, "w", encoding="utf-8") as out_file:
                        out_file.write(text)