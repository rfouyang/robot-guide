# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.10 Robot Guide application with a Gradio UI. UI composition and tab callbacks live in `app/ui_guide/`. Business workflows are grouped under `component/`: map building, POI management, task design, and task execution. Shared robot and domain helpers belong in `component/common/`; low-level Slamware clients and rendering utilities belong in `util/slam_helper/`. Keep configuration data in `config/`, input `.stcm` maps in `asset/`, and generated maps/audio in the ignored `output/` directory. Tests live in `tests/` and should mirror the behavior under test.

## Build, Test, and Development Commands

- `uv sync` creates or updates `.venv` from `pyproject.toml` and `uv.lock`.
- `cp env_example .env` prepares local configuration; fill in required values before running.
- `.venv/bin/python app/ui_guide/ui_main.py` starts the Gradio UI on all interfaces.
- `.venv/bin/python -m unittest discover -s tests -v` runs the full test suite.
- `.venv/bin/python -m compileall app component util` performs a quick syntax/import compilation check.

There is no separate build step or configured formatter/linter. Keep `uv.lock` synchronized when dependencies change.

## Coding Style & Naming Conventions

Follow standard PEP 8 conventions: four-space indentation, `snake_case` for functions and modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Add type hints to public interfaces and short docstrings where behavior is not obvious. Keep Gradio event wiring in `app/`, workflow decisions in `component/`, and REST/device details in `util/slam_helper/`.

## Testing Guidelines

Tests use Python's `unittest` framework. Name files `test_*.py`, classes `*Tests`, and methods `test_<behavior>`. Add regression coverage for robot-state transitions, malformed API data, and rendering edge cases. Mock robot clients in unit tests; routine tests must not move hardware or require network access.

## Commit & Pull Request Guidelines

Recent history uses short, imperative, sentence-case subjects such as `Fix map-building session recovery`. Keep commits focused and exclude unrelated runtime changes, especially `config/task.json`, maps, and generated output. Pull requests should explain user-visible behavior, list verification commands, link the relevant issue, and include screenshots for UI changes. Call out any required robot setup or safety impact.

## Security & Robot Safety

Never commit `.env` or API keys. Confirm `SLAM_BASE_URL` targets the intended robot. Treat movement, mapping resets, map loads, and docking as hardware-affecting operations; document prerequisites and avoid destructive state changes unless explicitly required.
