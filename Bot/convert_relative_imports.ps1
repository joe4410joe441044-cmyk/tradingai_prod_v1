# Bot/convert_relative_imports.ps1
# Bot フォルダ直下で実行してください
# 相対インポート（from ..module や from .module）を絶対インポートに置換します

$BotPath = Get-Location

# 再帰的にすべての .py ファイルを処理
Get-ChildItem -Path $BotPath -Recurse -Filter "*.py" | ForEach-Object {
    $file = $_.FullName
    $content = Get-Content $file

    # from ..module を from module に置換
    $newContent = $content -replace 'from \.\.([a-zA-Z0-9_\.]+)', 'from $1'

    # from .module を from module に置換
    $newContent = $newContent -replace 'from \.([a-zA-Z0-9_\.]+)', 'from $1'

    # 上書き保存
    Set-Content -Path $file -Value $newContent

    Write-Host "Processed $file"
}

Write-Host "=== All relative imports have been converted to absolute imports ==="