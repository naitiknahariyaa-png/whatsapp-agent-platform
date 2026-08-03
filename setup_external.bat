@echo off
echo ============================================
echo  WhatsApp Agent Platform - External Repo Setup
echo ============================================
echo.

if not exist "external" mkdir external

echo [1/4] Adding git submodules...
echo.

rem === BULK REPO LIST - Add your GitHub repos here ===
set REPO_LIST=^
https://github.com/anthropics/anthropic-cookbook.git^
https://github.com/langchain-ai/langgraph.git^
https://github.com/chroma-core/chroma.git^
https://github.com/n8n-io/n8n.git^
https://github.com/twentyhq/twenty.git

rem === OR add one-by-one (uncomment these) ===
rem git submodule add https://github.com/anthropics/anthropic-cookbook.git external/anthropic-cookbook
rem git submodule add https://github.com/langchain-ai/langgraph.git external/langgraph
rem git submodule add https://github.com/chroma-core/chroma.git external/chroma
rem git submodule add https://github.com/n8n-io/n8n.git external/n8n
rem git submodule add https://github.com/twentyhq/twenty.git external/twenty-crm

echo Adding repos from list...
for %%r in (%REPO_LIST%) do (
    for /f "tokens=4 delims=/" %%n in ("%%r") do (
        if not exist "external\%%~nn" (
            echo [+] Adding %%~nn...
            git submodule add %%r external/%%~nn 2>nul
        ) else (
            echo [i] %%~nn already exists
        )
    )
)

echo.
echo [2/4] Initializing all submodules...
git submodule update --init --recursive 2>nul
echo [v] Submodules initialized

echo.
echo [3/4] Setting PYTHONPATH...
set PYTHONPATH=%cd%;%cd%\external\anthropic-cookbook;%cd%\external\langgraph;%cd%\external\chroma
echo [v] PYTHONPATH updated for this session

echo.
echo [4/4] Locking versions...
if not exist ".gitmodules" (
    echo [i] Run 'git init' then re-run this script to lock versions
) else (
    echo [v] .gitmodules ready - SHAs will lock on first commit
)

echo.
echo ============================================
echo  External repos ready!
echo  Total repos added: 
git submodule status 2>nul | find /c /v ""
echo.
echo  To add MORE repos later:
echo    git submodule add https://github.com/OWNER/REPO.git external/REPO
echo    git submodule update --init
echo.
echo  To verify locked SHAs:
echo    git submodule status
echo ============================================
echo.
pause