$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path "CHAVES_DADOS.env")) {
    Copy-Item "CHAVES_DADOS.env.example" "CHAVES_DADOS.env"
    Write-Host "Arquivo CHAVES_DADOS.env criado a partir do exemplo. Edite-o antes de continuar." -ForegroundColor Yellow
    exit 0
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker não encontrado no PATH. Instale o Docker Desktop e tente novamente."
    exit 1
}

Write-Host "Subindo PostgreSQL e pgAdmin..." -ForegroundColor Cyan
docker compose --env-file CHAVES_DADOS.env up -d

Write-Host "Criando ambiente virtual Python..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    py -3 -m venv .venv
}

.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "Validando conexão com o banco..." -ForegroundColor Cyan
python test_db.py

Write-Host "Abrindo a aplicação..." -ForegroundColor Cyan
streamlit run data_app.py
