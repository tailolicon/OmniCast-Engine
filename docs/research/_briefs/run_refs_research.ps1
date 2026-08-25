# Khai hoa nghien cuu _refs bang Grok Build CLI (headless).
# Dung: .\run_refs_research.ps1            -> chay tuan tu 7 brief
#       .\run_refs_research.ps1 -Briefs 04,05  -> chay brief chon loc
param(
  [string[]]$Briefs = @("01","02","03","04","05","06","07")
)
$grok = "$env:USERPROFILE\.grok\bin\grok.exe"
$repo = "E:\Project\OmniCast Engine"
$briefDir = Join-Path $repo "docs\research\_briefs"
$logDir = Join-Path $briefDir "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null

$check = & $grok models 2>&1 | Out-String
if ($check -match "not authenticated") {
  Write-Error "Grok chua dang nhap. Chay 'grok login' (hoac dat XAI_API_KEY) roi thu lai."
  exit 1
}

# ASCII-only de tranh loi encoding PS 5.1
$rules = "CHI duoc ghi/sua file duoi docs/research/ cua repo OmniCast. CAM sua moi file khac. CAM sua bat ky file nao trong _refs. Ket thuc phai in ra ten file report da ghi."

foreach ($b in $Briefs) {
  $file = Get-ChildItem $briefDir -Filter "$b*.md" | Select-Object -First 1
  if (-not $file) { Write-Warning "Khong thay brief $b"; continue }
  $log = Join-Path $logDir ("run_" + $file.BaseName + ".log")
  Write-Output ">>> [$(Get-Date -Format HH:mm:ss)] Brief $($file.Name) bat dau -> log: $log"
  & $grok --cwd $repo --prompt-file $file.FullName --always-approve --max-turns 300 --no-plan --rules $rules --output-format plain *> $log
  Write-Output ">>> [$(Get-Date -Format HH:mm:ss)] Brief $($file.Name) xong (exit=$LASTEXITCODE)"
}
Write-Output "HOAN TAT. Report nam o docs\research\REFS_SB_*.md"
