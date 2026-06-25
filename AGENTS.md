# Repository Guidelines

## Project Structure & Module Organization

This repository contains three modular services plus cluster launch scripts.
`llm-api/` is the FastAPI LLM backend with source in `backend/`, tools in `tools/`, prompts in `prompts/`, helpers in `scripts/`, and runtime files in `data/`. `hoonbot/` is the FastAPI bot bridge; clients and heartbeat logic live in `core/`, HTTP handlers in `handlers/`, all prompt and heartbeat files in `prompts/`, role skill profiles in `profiles/`, and bot skills in `skills/`. `messenger/` is a Node/React app with Express and Socket.IO in `server/src/`, React/Vite in `client/src/`, shared types in `shared/`, and served web output in `client/dist-web/`. Root scripts such as `start-master.sh` and `start-slave.ps1` orchestrate cluster roles.

## Build, Test, and Development Commands

- `./start-master.sh --build` or `.\start-master.ps1 -Build`: install/build and start the master stack.
- `cd llm-api && ./start.sh --build`: install Python dependencies and start the API on port `10002`; start vLLM separately first.
- `cd messenger && ./start.sh --build` or `npm.cmd run build:web`: install/build Messenger and refresh the served web bundle.
- `cd messenger && npm.cmd run typecheck`: run TypeScript checks for server and client.
- `cd hoonbot && ./start.sh --build`: install Python dependencies, set up credentials if missing, and start the bot on port `10001`.
- `python -m py_compile <files>`: quick syntax check for changed Python files.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and 2-space indentation for TypeScript/TSX. Keep Python functions/modules in `snake_case`, TypeScript variables/functions in `camelCase`, React components in `PascalCase`, and constants uppercase where established. Prefer each app's `config.py` as the single runtime configuration surface; do not add hidden `.env` runtime requirements.

## Testing Guidelines

There is no repo-wide test suite configured. Validate with the smallest meaningful checks: `py_compile` for Python edits, `python scripts/test_llm.py` for Hoonbot connectivity, `npm.cmd run typecheck` for Messenger type changes, and `npm.cmd run build:web` when UI or shared types affect the served bundle.

## Commit & Pull Request Guidelines

Recent history uses very terse timestamp-like subjects. For new work, use small commits with clear scoped subjects such as `messenger: rebuild web attachment flow`. Pull requests should describe behavior changes, list verification commands, mention config or port changes, and include screenshots for visible Messenger UI changes.

## Security & Configuration Tips

Do not commit `data/`, credentials, `.env` files, model files, or generated binaries. The root `cluster_config.py` `EDIT HERE` block is the single user-facing config for all three services (role, IPs, ports, vLLM URL, secrets, per-service knobs); the app-owned `llm-api/config.py`, `hoonbot/config.py`, and `messenger/config.py` hold advanced per-service tuning and read the common values from `cluster_config.py`.
