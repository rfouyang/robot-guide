# Robot Guide

Humanoid Guide application for map building, POI management, task design, and task execution.

## Folder structure

- `app/ui_guide/` — Gradio UI and four tabs.
- `component/common/` — Shared Guide models and services.
- `component/map_building/` — Map-building logic.
- `component/poi_management/` — POI logic.
- `component/task_design/` — Task creation and storage.
- `component/task_execution/` — Task running, stopping, and resuming.
- `util/slam_helper/` — SLAM API and robot movement functions.
- `config/` — Saved task configuration.
- `asset/` — Input map files.
- `output/` — Generated maps and audio.

## Installation

```bash
uv sync
```

Copy `env_example` to `.env`, then add your API key:

```bash
cp env_example .env
```

Edit `.env`:

```env
BYTEPLUS_API_KEY=your_byteplus_api_key
```

The robot API address is configured in `util/slam_helper/base.py`.

## Run the UI

```bash
.venv/bin/python app/ui_guide/ui_main.py
```

Use the UI in four steps:

1. **Map Building** — Build, save, or upload a map.
2. **POI Management** — Record and manage POIs.
3. **Task Design** — Create a task, choose POIs, and add TTS content.
4. **Task Execution** — Run, stop, resume, or manually control the robot.

Make sure the robot is ready before starting movement.
