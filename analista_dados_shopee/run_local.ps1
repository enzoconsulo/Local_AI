# =============================================================================
# run_local.ps1 - UM script para os DOIS cenarios (deteccao automatica):
#
#   PRIMEIRA VEZ : cria o CHAVES_DADOS.env do exemplo (e abre para voce
#                  preencher), cria o venv, instala as dependencias, sobe o
#                  banco, aplica TODAS as migracoes e abre a aplicacao.
#   ROTINA       : detecta que tudo ja existe, pula o que nao precisa
#                  (instala dependencia so se requirements.txt mudou) e abre
#                  a aplicacao em segundos.
#
# Como rodar (na pasta analista_dados_shopee):
#   powershell -ExecutionPolicy Bypass -File .\run_local.ps1
# =============================================================================
$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $raiz

function Falha($msg) {
    Write-Host ""
    Write-Host "[ERRO] $msg" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Estudio Shopee DW - inicializacao ===" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# 1) CREDENCIAIS - se nao existem, e a primeira vez: cria, abre e para aqui.
# -----------------------------------------------------------------------------
if (-not (Test-Path "CHAVES_DADOS.env")) {
    Copy-Item "CHAVES_DADOS.env.example" "CHAVES_DADOS.env"
    Write-Host ""
    Write-Host "[PRIMEIRA VEZ] Criei o arquivo CHAVES_DADOS.env a partir do exemplo." -ForegroundColor Yellow
    Write-Host "Preencha nele: credenciais da Shopee, chave da OpenAI, chave do Groq" -ForegroundColor Yellow
    Write-Host "e a senha do banco. Vou abrir o arquivo agora - salve, feche e rode" -ForegroundColor Yellow
    Write-Host "este script de novo (dai ele segue sozinho ate o fim)." -ForegroundColor Yellow
    notepad "CHAVES_DADOS.env"
    exit 0
}

# -----------------------------------------------------------------------------
# 2) DOCKER - precisa estar instalado E com o motor ligado.
# -----------------------------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Falha "Docker Desktop nao encontrado. Instale em https://www.docker.com/products/docker-desktop e rode de novo."
}
cmd /c "docker ps >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Falha "O Docker esta instalado mas o motor nao esta rodando. Abra o Docker Desktop, espere o icone ficar verde e rode de novo."
}

Write-Host "[1/5] Subindo PostgreSQL + pgAdmin (Docker)..." -ForegroundColor Cyan
docker compose --env-file CHAVES_DADOS.env up -d
if ($LASTEXITCODE -ne 0) { Falha "docker compose falhou - veja a mensagem acima." }

# Espera o banco ficar saudavel (primeira vez demora mais: cria volume + schema)
$tentativas = 0
while ($true) {
    $pronto = docker ps --filter "name=cofre_shopee" --filter "health=healthy" --format "{{.Names}}"
    if ("$pronto" -match "cofre_shopee") { break }
    $tentativas++
    if ($tentativas -gt 60) { Falha "O banco nao ficou saudavel em 2 minutos. Diagnostico: docker logs cofre_shopee" }
    Start-Sleep -Seconds 2
}
Write-Host "      Banco pronto em localhost:5433 (pgAdmin em localhost:5050)." -ForegroundColor Green

# -----------------------------------------------------------------------------
# 3) PYTHON - cria o venv na primeira vez; depois so reutiliza.
# -----------------------------------------------------------------------------
Write-Host "[2/5] Ambiente Python..." -ForegroundColor Cyan
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "      [PRIMEIRA VEZ] Criando ambiente virtual..." -ForegroundColor Yellow
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { Falha "Nao consegui criar o venv. Instale o Python 3.10+ (https://www.python.org) com o launcher 'py'." }
}
$python = Join-Path $raiz ".venv\Scripts\python.exe"

# Dependencias: instala apenas quando o requirements.txt mudar (hash gravado
# dentro do proprio venv). Na rotina isso e pulado em ~0s.
$hashAtual = (Get-FileHash "requirements.txt" -Algorithm SHA256).Hash
$marcador = ".venv\requirements.sha256"
$hashSalvo = ""
if (Test-Path $marcador) { $hashSalvo = (Get-Content $marcador -Raw).Trim() }
if ($hashAtual -ne $hashSalvo) {
    Write-Host "      Instalando dependencias (acontece na 1a vez ou quando requirements.txt muda)..." -ForegroundColor Yellow
    & $python -m pip install --upgrade pip --quiet
    & $python -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) { Falha "pip install falhou - veja a mensagem acima." }
    Set-Content $marcador $hashAtual
    Write-Host "      Dependencias instaladas." -ForegroundColor Green
} else {
    Write-Host "      Dependencias em dia (nada a instalar)." -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# 4) BANCO - migracoes pendentes (idempotente: na rotina so confere e segue)
#            + teste real de conexao.
# -----------------------------------------------------------------------------
Write-Host "[3/5] Aplicando migracoes pendentes (seguro rodar sempre)..." -ForegroundColor Cyan
& $python init_db\aplicar_migrations.py
if ($LASTEXITCODE -ne 0) { Falha "As migracoes falharam - veja a mensagem acima." }

Write-Host "[4/5] Validando a conexao com o banco..." -ForegroundColor Cyan
& $python test_db.py
if ($LASTEXITCODE -ne 0) { Falha "Conexao com o banco falhou. Confira DB_PORT/senha no CHAVES_DADOS.env." }

# -----------------------------------------------------------------------------
# 5) APLICACAO
# -----------------------------------------------------------------------------
Write-Host "[5/5] Abrindo a aplicacao: http://localhost:8501 (Ctrl+C encerra)" -ForegroundColor Cyan
Write-Host ""
& $python -m streamlit run data_app.py
