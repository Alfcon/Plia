@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  Plia Source Archiver - For Claude Review
echo ============================================
echo.

set ZIP_NAME=plia_for_claude.zip
set TREE_FILE=plia_tree.txt

if exist "%ZIP_NAME%" (
    del "%ZIP_NAME%"
    echo Removed old archive.
)

if exist "%TREE_FILE%" (
    del "%TREE_FILE%"
)

echo Generating directory tree structure...
echo.

:: Iterative tree builder - avoids PowerShell call stack overflow on deep projects
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$treePath = Join-Path (Get-Location) '%TREE_FILE%';" ^
    "$exclude = @('.venv', '__pycache__', '.git', '.vs', 'merged_model', 'data', '.mypy_cache');" ^
    "$lines = [System.Collections.Generic.List[string]]::new();" ^
    "$lines.Add('Plia Project - Directory Tree');" ^
    "$lines.Add('Generated: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'));" ^
    "$lines.Add('Root: ' + (Get-Location).Path);" ^
    "$lines.Add('============================================');" ^
    "$lines.Add('');" ^
    "$root = (Get-Location).Path;" ^
    "$rootName = Split-Path $root -Leaf;" ^
    "$lines.Add($rootName + '/');" ^
    "$stack = [System.Collections.Generic.Stack[object]]::new();" ^
    "$rootChildren = Get-ChildItem -Path $root -ErrorAction SilentlyContinue | Where-Object { $exclude -notcontains $_.Name } | Sort-Object { -not $_.PSIsContainer }, Name;" ^
    "for ($i = $rootChildren.Count - 1; $i -ge 0; $i--) {" ^
        "$stack.Push(@{ Item = $rootChildren[$i]; Indent = ''; IsLast = ($i -eq $rootChildren.Count - 1) })" ^
    "};" ^
    "while ($stack.Count -gt 0) {" ^
        "$frame = $stack.Pop();" ^
        "$item = $frame.Item;" ^
        "$indent = $frame.Indent;" ^
        "$isLast = $frame.IsLast;" ^
        "if ($exclude -contains $item.Name) { continue };" ^
        "$prefix = if ($isLast) { '└── ' } else { '├── ' };" ^
        "$childIndent = if ($isLast) { $indent + '    ' } else { $indent + '│   ' };" ^
        "$label = if ($item.PSIsContainer) { $item.Name + '/' } else { $item.Name };" ^
        "$lines.Add($indent + $prefix + $label);" ^
        "if ($item.PSIsContainer) {" ^
            "$children = Get-ChildItem -Path $item.FullName -ErrorAction SilentlyContinue | Where-Object { $exclude -notcontains $_.Name } | Sort-Object { -not $_.PSIsContainer }, Name;" ^
            "for ($i = $children.Count - 1; $i -ge 0; $i--) {" ^
                "$stack.Push(@{ Item = $children[$i]; Indent = $childIndent; IsLast = ($i -eq $children.Count - 1) })" ^
            "}" ^
        "}" ^
    "};" ^
    "[System.IO.File]::WriteAllLines($treePath, $lines);" ^
    "Write-Host ('Tree saved to %TREE_FILE% (' + $lines.Count + ' lines, ' + (Get-Item $treePath).Length + ' bytes)')"

echo.
echo Collecting source files...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$source = Get-Location;" ^
    "$zip = Join-Path $source '%ZIP_NAME%';" ^
    "$treeFile = Join-Path $source '%TREE_FILE%';" ^
    "$exclude = @('.venv', '__pycache__', '.git', '.vs', 'merged_model', 'data', '.mypy_cache');" ^
    "$extensions = @('*.py', '*.json', '*.yaml', '*.yml', '*.cfg', '*.ini', '*.toml', '*.txt', '*.md');" ^
    "$files = Get-ChildItem -Recurse -File | Where-Object {" ^
        "$path = $_.FullName;" ^
        "if ($_.Name -eq '%TREE_FILE%') { return $false };" ^
        "$skip = $false;" ^
        "foreach ($ex in $exclude) { if ($path -like ('*\' + $ex + '\*') -or $path -like ('*\' + $ex)) { $skip = $true; break } };" ^
        "if ($skip) { return $false };" ^
        "$match = $false;" ^
        "foreach ($ext in $extensions) { if ($_.Name -like $ext) { $match = $true; break } };" ^
        "return $match" ^
    "};" ^
    "if ($files.Count -eq 0) { Write-Host 'No files found. Make sure you are running from the Plia root folder.'; exit 1 };" ^
    "$allFiles = @($files.FullName);" ^
    "if (Test-Path $treeFile) { $allFiles = @($treeFile) + $allFiles; Write-Host 'Tree file included.' } else { Write-Host 'WARNING: Tree file not found, skipping.' };" ^
    "Write-Host ('Found ' + $files.Count + ' source files to archive...');" ^
    "Compress-Archive -Path $allFiles -DestinationPath $zip -Force;" ^
    "Write-Host '';" ^
    "Write-Host 'Done! Archive created: %ZIP_NAME%';" ^
    "Write-Host '';" ^
    "Write-Host 'Files included:';" ^
    "if (Test-Path $treeFile) { Write-Host '  .\%TREE_FILE% (directory tree)' };" ^
    "foreach ($f in $files) { Write-Host ('  ' + $f.FullName.Replace([string]$source, '.')) }"

echo.
echo ============================================
echo  Upload "%ZIP_NAME%" to your Claude chat!
echo ============================================
echo.
pause
