<#
.SYNOPSIS
    Sobe o auto-imigração (CRM SAES) pra acesso pela rede local (LAN) e,
    opcionalmente, por um túnel público via cloudflared.

.DESCRIPTION
    Reproduz os passos manuais de sempre: checa se a porta já está em uso,
    sobe o app com waitress ouvindo em 0.0.0.0 (não só localhost), confirma
    que respondeu, garante a regra de firewall pra porta, e imprime o IP
    local pra abrir de outro aparelho no mesmo Wi-Fi. Com -Tunnel, também
    sobe um túnel cloudflared por cima e imprime a URL pública
    (trycloudflare.com).

.PARAMETER Port
    Porta TCP a usar. Padrão: 5000.

.PARAMETER Tunnel
    Também abre um túnel público via cloudflared (acessível de fora da
    rede local, não só do mesmo Wi-Fi). Sem garantia de uptime -- é um
    túnel gratuito de teste, cai se fechar o processo/terminal/PC.

.EXAMPLE
    .\start-lan.ps1
.EXAMPLE
    .\start-lan.ps1 -Tunnel
.EXAMPLE
    .\start-lan.ps1 -Port 5001
#>
param(
    [int]$Port = 5000,
    [switch]$Tunnel
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== auto-imigracao: subindo em LAN (porta $Port) ==" -ForegroundColor Cyan

# 1. Já tem algo escutando nessa porta? Não sobe um segundo processo por cima.
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $existingPid = $existing[0].OwningProcess
    Write-Host "Já tem um processo escutando na porta $Port (PID $existingPid). Não vou subir outro por cima." -ForegroundColor Yellow
    Write-Host "Pra derrubar antes de tentar de novo: Stop-Process -Id $existingPid -Force"
    exit 1
}

# 2. Sobe o waitress em background, ouvindo em todas as interfaces (0.0.0.0)
#    -- é isso que permite outro aparelho na rede acessar, diferente de
#    'python wsgi.py' (servidor de dev do Flask, só localhost e single-thread).
$waitressLog = Join-Path $PSScriptRoot "waitress-lan.log"
$waitressErr = Join-Path $PSScriptRoot "waitress.err.log"
$proc = Start-Process -FilePath "python" `
    -ArgumentList "-m", "waitress", "--host=0.0.0.0", "--port=$Port", "--call", "wsgi:create_app" `
    -RedirectStandardOutput $waitressLog `
    -RedirectStandardError $waitressErr `
    -NoNewWindow `
    -PassThru

Write-Host "waitress iniciado (PID $($proc.Id)), logs em $waitressLog / $waitressErr"

# 3. Espera responder antes de seguir
$ok = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) {
    Write-Host "O servidor não respondeu em http://127.0.0.1:$Port/ depois de 10s -- confira $waitressErr" -ForegroundColor Red
    exit 1
}
Write-Host "Servidor respondendo em http://127.0.0.1:$Port/" -ForegroundColor Green

# 4. Confere (ou cria) a regra de firewall -- sem ela, o servidor sobe mas
#    ninguém de fora do próprio PC consegue falar com ele.
$fwName = "auto-imigracao LAN $Port"
$rule = Get-NetFirewallRule -DisplayName $fwName -ErrorAction SilentlyContinue
if (-not $rule) {
    try {
        New-NetFirewallRule -DisplayName $fwName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
        Write-Host "Regra de firewall criada pra porta $Port." -ForegroundColor Green
    } catch {
        Write-Host "Não consegui criar a regra de firewall automaticamente (precisa rodar como Administrador). Crie manualmente:" -ForegroundColor Yellow
        Write-Host "  New-NetFirewallRule -DisplayName '$fwName' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow"
    }
} else {
    Write-Host "Regra de firewall pra porta $Port já existe." -ForegroundColor Green
}

# 5. IP local pra passar pros outros aparelhos da mesma rede
$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -notmatch "Loopback|vEthernet|WSL" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress

if ($ip) {
    Write-Host ""
    Write-Host "Acesse de outro aparelho no mesmo Wi-Fi:" -ForegroundColor Cyan
    Write-Host "  http://${ip}:${Port}" -ForegroundColor White
} else {
    Write-Host "Não consegui detectar o IP local automaticamente -- rode 'ipconfig' e use o IPv4 do adaptador ativo." -ForegroundColor Yellow
}

# 6. Túnel público opcional (fora da rede local)
if ($Tunnel) {
    Write-Host ""
    Write-Host "== Abrindo túnel público via cloudflared ==" -ForegroundColor Cyan
    $cfOutLog = Join-Path $PSScriptRoot "cloudflared.log"
    $cfErrLog = Join-Path $PSScriptRoot "cloudflared.err.log"
    $cfProc = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port" `
        -RedirectStandardOutput $cfOutLog `
        -RedirectStandardError $cfErrLog `
        -NoNewWindow `
        -PassThru
    Write-Host "cloudflared iniciado (PID $($cfProc.Id)), logs em $cfOutLog / $cfErrLog"

    # cloudflared loga a URL no stderr -- procura nos dois arquivos por segurança
    $url = $null
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        foreach ($logFile in @($cfErrLog, $cfOutLog)) {
            if (Test-Path $logFile) {
                $match = Select-String -Path $logFile -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($match) { $url = $match.Matches[0].Value; break }
            }
        }
        if ($url) { break }
    }
    if ($url) {
        Write-Host "URL pública: $url" -ForegroundColor Green
        Write-Host "(sem garantia de uptime -- túnel gratuito de teste, cai se fechar o processo/terminal/PC)" -ForegroundColor Yellow
    } else {
        Write-Host "Não consegui ler a URL pública ainda -- confira $cfErrLog manualmente." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Pra derrubar o servidor depois: Stop-Process -Id $($proc.Id) -Force" -ForegroundColor DarkGray
