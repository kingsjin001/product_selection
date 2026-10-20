<#
调用已启动的 API，依次验证健康检查、样例导入、规则索引和证据检索。
#>
param(
    [string]$BaseUrl = "http://localhost:8000"
)

# 每一步均检查关键返回字段，失败时 PowerShell 直接停止并显示原因。
$health = Invoke-RestMethod "$BaseUrl/health"
if ($health.status -ne "ok") { throw "API health check failed" }

$import = Invoke-RestMethod -Method Post "$BaseUrl/api/imports/sample"
if ($import.products -lt 1 -or $import.rules -lt 1) { throw "Sample import returned an unexpected summary" }

$index = Invoke-RestMethod -Method Post "$BaseUrl/api/indexes/rules"
if ($index.records -lt 1) { throw "No rule evidence was indexed" }

$body = @{ query = "food contact material labeling"; market = "US"; top_k = 3 } | ConvertTo-Json
$search = Invoke-RestMethod -Method Post -ContentType "application/json" -Body $body "$BaseUrl/api/rules/search"
if ($search.data.Count -lt 1) { throw "Expected at least one rule-search result" }
if (-not $search.data[0].evidence_id -or -not $search.data[0].version) { throw "Search result is missing traceability fields" }

Write-Host "第一期验证通过。首条证据：$($search.data[0].evidence_id)"

