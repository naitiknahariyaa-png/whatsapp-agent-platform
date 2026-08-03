# External Dependencies

This directory contains upstream repositories used as git submodules.

## Repositories

| Repo | Purpose | Upstream |
|------|---------|----------|
| `anthropic-cookbook` | Skill content for LLM prompt injection | https://github.com/anthropics/anthropic-cookbook |
| `langgraph` | Agent orchestration / state graphs | https://github.com/langchain-ai/langgraph |
| `chroma` | Vector database (semantic memory) | https://github.com/chroma-core/chroma |

## Why Submodules?

- **Version locking** — Each submodule is pinned to a specific commit SHA.
- **No dependency bloat** — Only the files we use get pulled.
- **Easy upgrade** — Update SHA in `.gitmodules` when needed.

## How to Upgrade

```bash
cd external/anthropic-cookbook
git pull origin main
cd ..
git add anthropic-cookbook
git commit -m "chore: bump anthropic-cookbook"
```

## Version Lock

The current locked SHAs are in `.gitmodules` at the project root.
Run `git submodule status` to verify they match.

## CI Check

The `test_system.bat` script runs `git submodule status` and fails
if any submodule deviates from its locked SHA.