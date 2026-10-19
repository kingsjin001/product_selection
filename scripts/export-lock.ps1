<#
导出当前 py12 环境的完整依赖版本，用于记录本机可复现的验证环境。
#>
param(
    [string]$PythonPath = "D:\Programs\anaconda3\envs\py12\python.exe",
    [string]$OutputPath = "requirements.lock"
)

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python was not found: $PythonPath"
}

# 仅在 bootstrap-py12.ps1 成功安装项目后执行；清单包含传递依赖。
& $PythonPath -m pip freeze --all | Set-Content -LiteralPath $OutputPath -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw "Could not export dependency lock" }

Write-Host "已写入 $OutputPath，请同时记录验证所用的 Python 和 Docker 版本。"

