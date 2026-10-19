<#
使用指定的 Conda Python 安装项目依赖，并执行第一期基础静态检查。
#>
param(
    [string]$PythonPath = "D:\Programs\anaconda3\envs\py12\python.exe"
)

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python was not found: $PythonPath"
}

& $PythonPath --version
& $PythonPath -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

& $PythonPath -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

# 将迁移脚本一并纳入静态检查，避免数据库升级文件遗漏质量检查。
& $PythonPath -m ruff check app tests migrations
if ($LASTEXITCODE -ne 0) { throw "Ruff check failed" }

Write-Host "Python 环境已准备完成，下一步可执行 docker compose up -d --build。"

