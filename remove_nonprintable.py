import os
import re

root_dir = "Bot"  # Bot 配下すべて対象

# 改行・タブ・通常ASCII文字以外は削除
non_printable = re.compile(r'[^\x09\x0A\x0D\x20-\x7E]')

for subdir, _, files in os.walk(root_dir):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(subdir, f)
            with open(path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
            new_content = non_printable.sub("", content)
            with open(path, "w", encoding="utf-8") as file:
                file.write(new_content)
            print(f"[CLEANED] {path}")