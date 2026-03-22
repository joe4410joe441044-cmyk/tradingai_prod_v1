# Bot 内の全 Python ファイルを UTF-8 に変換し、先頭に UTF-8 指定を追加
$BotPath = Get-Location
$exclude = @("venv", "__pycache__")  # 除外フォルダ

Get-ChildItem -Path $BotPath -Recurse -Filter "*.py" |
    Where-Object { $exclude -notcontains $_.PSParentPath.Split('\')[-1] } |
    ForEach-Object {
        $file = $_.FullName
        Write-Host "Processing $file ..."

        # ファイル内容を既存のエンコーディングで読み込む
        $lines = Get-Content $file -Encoding Default

        # 先頭に UTF-8 指定がなければ追加
        if ($lines.Count -eq 0 -or ($lines[0] -notmatch "coding: utf-8")) {
            $lines = @("# -*- coding: utf-8 -*-") + $lines
        }

        # UTF-8 で書き直す
        Set-Content -Path $file -Value $lines -Encoding UTF8

        Write-Host "Converted $file to UTF-8"
    }

Write-Host "=== All Python files in Bot folder converted to UTF-8 ==="