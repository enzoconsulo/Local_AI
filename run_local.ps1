$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "Configuração do ambiente local..." -ForegroundColor Cyan

if (-not (Test-Path "CHAVES.env")) {
    Write-Error "Arquivo CHAVES.env não encontrado na raiz. Crie-o com as chaves de GROQ e RunPod antes de continuar."
    exit 1
}

if (-not (Test-Path "analista_dados_shopee/CHAVES_DADOS.env")) {
    if (Test-Path "analista_dados_shopee/CHAVES_DADOS.env.example") {
        Copy-Item "analista_dados_shopee/CHAVES_DADOS.env.example" "analista_dados_shopee/CHAVES_DADOS.env"
    } else {
        @"
POSTGRES_USER=admin_shopee
POSTGRES_PASSWORD=sua_senha_blindada
POSTGRES_DB=estudio_shopee
DB_HOST=localhost
DB_PORT=5433
TZ=America/Sao_Paulo
PGADMIN_DEFAULT_EMAIL=admin@estudio.com
PGADMIN_DEFAULT_PASSWORD=admin
SHOPEE_PARTNER_ID=seu_partner_id
SHOPEE_PARTNER_KEY=sua_partner_key
SHOPEE_SHOP_ID=seu_shop_id
SHOPEE_REFRESH_TOKEN=seu_refresh_token
GROQ_API_KEY=sua_chave_groq
RUNPOD_API_KEY=sua_chave_runpod
ENDPOINT_ID_RUNPOD_DADOS=seu_endpoint_dados
ENDPOINT_ID_RUNPOD_vLLM=seu_endpoint_vllm
"@ | Set-Content "analista_dados_shopee/CHAVES_DADOS.env"
    }
    Write-Host "Arquivo analista_dados_shopee/CHAVES_DADOS.env criado. Edite-o com suas credenciais antes de continuar." -ForegroundColor Yellow
    exit 0
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker não encontrado no PATH. Instale o Docker Desktop e tente novamente."
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual Python..." -ForegroundColor Cyan
    py -3 -m venv .venv
}

Write-Host "Ativando ambiente virtual..." -ForegroundColor Cyan
. .\.venv\Scripts\Activate.ps1

Write-Host "Instalando dependências..." -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "Subindo PostgreSQL e pgAdmin..." -ForegroundColor Cyan
docker compose --env-file analista_dados_shopee/CHAVES_DADOS.env -f analista_dados_shopee/docker-compose.yml up -d

Write-Host "Validando conexão com o banco..." -ForegroundColor Cyan
python analista_dados_shopee/test_db.py

# --- Se banco nao iniciar, crasha o pipeline e impede a execução da aplicação ---
if ($LASTEXITCODE -ne 0) {
    Write-Error "Falha na conexão com o banco de dados. Pipeline abortado para proteger a integridade da aplicação."
    exit 1
}
# ---------------------------------

Write-Host "Inicializando o motor de IA..." -ForegroundColor Cyan
python llm.py