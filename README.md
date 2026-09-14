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
- `asset/` — Authoritative STCM maps and the pinned Tianyi model contract.
- `data/` — Recorder-format Tianyi poses, actions, and NPZ trajectories.
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
```

The API must be reachable from the machine that runs the UI.

## Run the UI

```bash
source /opt/ros/humble/setup.bash
.venv/bin/python app/ui_guide/ui_main.py
```

Use the UI in four steps:

1. **Map Building** — Identify the active map, switch to an `asset/` map, sync
   the current single-floor map, save a debug snapshot, or build a new map.
2. **POI Management** — Record and manage POIs.
3. **Task Design** — Create a task and give every POI TTS content plus an
   optional ordered list of validated Tianyi arm actions to run during speech.
4. **Task Execution** — Confirm physical arm actions for the run, then run,
   stop, resume, or manually control the robot.

Make sure the robot is ready before starting movement.

## Tianyi concierge actions

Robot Guide reads the same JSON and NPZ format as `tianyi-action-recorder` and
publishes the two arms directly through the vendor ROS 2 topics:

- status: `/arm/status`
- command: `/arm/cmd_pos`
- commanded motors: 11-17 and 21-27 only

No `tianyi_hw_bridge` or separate action service is used. The vendor body-control
node must already provide both topics. Check the direct runtime without sending
commands:

```bash
source /opt/ros/humble/setup.bash
.venv/bin/python -m component.common.tianyi_arm_runtime
```

The local artifact structure mirrors `tianyi-action-recorder`: model files are
under `asset/tianyi2/`, with action JSON, pose JSON, and NPZ files under
`data/actions/`, `data/poses/`, and `data/trajectories/`. Only complete actions
that pass the model, schema, pose-sequence, timing, and joint-limit checks appear
in Task Design.

Every task moves the arms to `concierge_init` before the first navigation. At
each POI it starts the ordered action sequence and prepared speech concurrently.
Actions play one by one in the configured order, and the POI completes only
after both the full sequence and speech finish. Every action verifies its return
to `concierge_init`. Base navigation never overlaps with arm motion or POI
speech. If a POI has no actions, the arms remain at `concierge_init` throughout
its speech. An initialization failure prevents departure; an action failure keeps
the base at the current POI. A guide may start from the base's current position;
the preflight still requires a bound home dock so completion and recoverable
failures can return the robot home.

The map selector intentionally lists only `asset/*.stcm`. Files downloaded to
`output/` are test/debug artifacts and cannot be activated from the UI. Map
switch and sync operations require the robot to be healthy, idle, docked, and
charging. They are blocked when cloud map management is active; sync is also
blocked unless the robot reports exactly one floor.
