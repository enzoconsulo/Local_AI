# Atalho da raiz: delega para o script inteligente do app principal, que
# detecta sozinho se e a primeira execucao (setup completo) ou rotina.
#   powershell -ExecutionPolicy Bypass -File .\run_local.ps1
$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
& powershell -ExecutionPolicy Bypass -File (Join-Path $raiz "analista_dados_shopee\run_local.ps1")
exit $LASTEXITCODE
