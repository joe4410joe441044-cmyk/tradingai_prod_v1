# -*- coding: utf-8 -*-
import os
import re

# Bot 配下の全 .py ファイルを対象
root_dir = "Bot"

# 日本語文字のパターン（ひらがな・カタカナ・漢字）
jp_pattern = re.compile(r'[一-龯ぁ-んァ-ン]')

# docstring の """ 内の日本語も削除したい場合
docstring_pattern = re.compile(r'(""".*?""")', re.DOTALL)

for subdir, _, files in os.walk(root_dir):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(subdir, f)
            with open(path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()

            # docstring 内の日本語を削除
            def remove_jp_from_docstring(match):
                s = match.group(0)
                return jp_pattern.sub("", s)

            content = docstring_pattern.sub(remove_jp_from_docstring, content)

            # 行単位のコメント内の日本語も削除
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                # '#' 以降の日本語を削除
                if '#' in line:
                    code, comment = line.split('#', 1)
                    comment = jp_pattern.sub("", comment)
                    line = code + '#' + comment
                new_lines.append(line)

            new_content = "\n".join(new_lines)

            # UTF-8 で保存
            with open(path, "w", encoding="utf-8") as file:
                file.write(new_content)

            print(f"[CLEANED] {path}")