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
- `asset/` — Authoritative STCM maps that operators may deploy to the robot.
- `output/` — Generated maps, robot snapshots, identity cache, and audio for debugging.

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

Set the robot REST API address in `.env` (the default is shown below):

```env
SLAM_BASE_URL=http://192.168.11.1:1448
ROBOT_ACTION_BASE_URL=http://127.0.0.1:8765
```

The API must be reachable from the machine that runs the UI.

## Run the UI

```bash
.venv/bin/python app/ui_guide/ui_main.py
```

Use the UI in four steps:

1. **Map Building** — Identify the active map, switch to an `asset/` map, sync
   the current single-floor map, save a debug snapshot, or build a new map.
2. **POI Management** — Record and manage POIs.
3. **Task Design** — Create a task, choose POIs, add TTS content, and optionally
   select a validated Tianyi concierge action to run before speech.
4. **Task Execution** — Confirm physical body actions for the run, then run,
   stop, resume, or manually control the robot.

Make sure the robot is ready before starting movement.

## Tianyi concierge actions

Tianyi body actions run through the separate `robot-action` process. Start the
hardware bridge and action API manually before opening Robot Guide:

```bash
~/workspace/launch/launch_tianyi_hw_bridge.sh --detached
~/workspace/launch/launch_robot_action_service.sh --detached
```

The action catalog is intentionally limited to generated trajectories with a
matching successful MuJoCo report. The supplied concierge definitions all use
the sequence `concierge_init -> concierge_xxx -> concierge_init`. Generate or
regenerate them from the saved poses in the `robot-action` checkout:

```bash
cd ~/workspace/services/robot-action
.venv/bin/python -m app.build_concierge_actions --overwrite
```

The Guide executor never overlaps base navigation and body motion. A failed or
cancelled body action keeps the base at the current POI because the arms may not
have returned to `concierge_init`.

The map selector intentionally lists only `asset/*.stcm`. Files downloaded to
`output/` are test/debug artifacts and cannot be activated from the UI. Map
switch and sync operations require the robot to be healthy, idle, docked, and
charging. They are blocked when cloud map management is active; sync is also
blocked unless the robot reports exactly one floor.
