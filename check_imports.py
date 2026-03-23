# check_imports.py
import os
import re

root_dir = "Bot"  # Bot 配下だけでも可
pattern = re.compile(r"^\s*(from|import)\s+([^\s]+)")

for subdir, _, files in os.walk(root_dir):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(subdir, f)
            with open(path, "r", encoding="utf-8") as file:
                for line in file:
                    m = pattern.match(line)
                    if m:
                        module = m.group(2)
                        import_type = "relative" if line.strip().startswith("from .") else "absolute"
                        print(f"{path}: {import_type} -> {module}")