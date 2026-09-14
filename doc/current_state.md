# Current State Handoff

Updated: 2026-09-14 17:41 CST

## 2026-09-14 Tianyi Guide Integration

Robot Guide now controls the Tianyi two-arm subset directly through ROS 2
`/arm/status` and `/arm/cmd_pos`; it does not use `tianyi_hw_bridge` or an HTTP
action service. The repository is self-contained with the pinned Tianyi URDF,
model metadata, recorder-format action/pose JSON, and trajectory NPZ files under
`asset/tianyi2/` and `data/`.

Guide tasks may start from the mobile base's current position. Before the first
navigation, motors 11-17 and 21-27 move from their measured positions to
`concierge_init`; no other Tianyi motors are commanded. Each POI has one TTS
content field and an optional ordered action list. The action sequence executes
one action at a time while prepared TTS audio plays concurrently. A POI is
complete only after both speech and the full action sequence finish. With an
empty action list, the arms remain at `concierge_init` during speech.

Task Design supports adding repeated actions and moving or removing entries in
each POI's action sequence. Single-action task records remain readable and are
normalized to the ordered-list schema. Save-time and execution preflight reject
unknown actions but accept an empty list.

The validated local action catalog is:

- `concierge_present_left` and `concierge_present_right` (5 seconds each);
- `concierge_wave_left` and `concierge_wave_right` (5 seconds each);
- `concierge_speak_1`, `concierge_speak_2`, and `concierge_speak_3`
  (17 seconds each).

All seven actions pass schema, model, URDF hash, pose-reference, trajectory
timing, joint-limit, keyframe, and configured arm-speed validation. Every
composed pose matches its NPZ keyframe exactly. Live ROS preflight reports all
14 arm motors ready and all seven actions available.

Two full four-stop hardware guide runs were completed during development. The
second validated concurrent action and speech at every POI, waited for both
before continuing, and returned to the home dock successfully. The operator
subsequently configured multiple and empty action sequences through the UI and
confirmed the behavior works. The latest UI-driven guide run completed mobile
base actions 17-21 and returned to the dock at 17:17 CST with battery 100% and
charging enabled.

Automated verification currently passes 77 unit tests, compilation, JSON
validation, Gradio UI construction, and `git diff --check`. The Robot Guide UI
is running in tmux session `robot_guide_ui_8085` on `0.0.0.0:8085` (PID 123641).

## Current Robot State

The guide departure issue is resolved and has been validated through the live
robot and a separate user test. The last confirmed robot state is:

- `dockingStatus=on_dock`, `isCharging=true`, battery 100%.
- No active motion action.
- Map `a00c1f7d-f59d-45d3-b8c4-8472e1453fd0` is loaded and mapping is off.
- Home dock `home_dock` / `office2_charger` remains correctly bound.
- No health error, fatal, emergency-stop, lidar-disconnect, or SDP-disconnect
  flags. A non-blocking `depth camera disconnect` warning remains in
  `baseError`, while `hasDepthCameraDisconnected=false`.

The complete four-stop `guide` task finished successfully and returned to the
charger. The user subsequently tested the updated flow and reported no issue.

## Undock Issue Resolution

Adding or rebinding a charging dock was not required. The map already contained
the correct bound home dock. The failure was isolated to the explicit undock
path used before guide navigation:

- The configured `BackOffFromTagAction` returned `status=4, result=-1`.
- A documented empty-options `BackOffFromTagAction` returned success but caused
  zero displacement and left the robot on-dock and charging.
- `GoHomeAction` with the `no_dock` flag was also accepted as a no-op.
- The bounded `MoveByAction` fallback reported successful pulses but produced
  effectively zero displacement while the charging lock remained active.
- A normal planner-controlled `MoveToAction` from the dock to `Welcome`
  succeeded, physically departed the charger, reached the POI, and changed
  power state to `not_on_dock`, `isCharging=false`.

`component/task_execution/executor.py` now lets the first planned navigation
perform departure for both fresh and resumed guide runs. It verifies the power
state after the first navigation and only runs failure recovery when the robot
actually left the dock. This also fixes the prior misleading recovery behavior,
where `departed` was set before undocking succeeded.

The manual **Undock** control still uses the explicit dock-tag implementation
and is not the validated path for this Hermes firmware. It is not needed for a
guide run; use **Run Selected Task**, which now departs through planned
navigation.

## Live Validation

The controlled live sequence was:

- Action 37: direct planned navigation from the charger to `Welcome`; success.
- Action 38: return home; success and charging confirmed.
- Action 39: patched guide departure and navigation to `Welcome`; success.
- Action 40: navigation to `Teleoperation`; success.
- Action 41: navigation to `Demo Explain`; success.
- Action 42: navigation to `Demo Table`; success.
- Action 43: final return home; success and charging confirmed.
- Final task event: `Task 'guide' completed`.

All four configured speech segments ran at their POIs. Final verification found
no active action, and the robot was on-dock and charging.

Automated verification:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall app component util
git diff --check
```

Result: 15 tests passed, compilation passed, and `git diff --check` passed.

## Operating Guidance

Start a new guide only when the normal preflight conditions are met: map loaded,
mapping off, system healthy, no active action, localization quality at least 50,
and a bound home dock. The base may start from its current position. The Tianyi
arms move to `concierge_init` before the first POI navigation; do not run a
separate undock first.

Useful read-only state checks:

```bash
curl --connect-timeout 2 --max-time 5 http://192.168.11.1:1448/api/multi-floor/status
curl --connect-timeout 2 --max-time 5 http://192.168.11.1:1448/api/core/system/v1/power/status
curl --connect-timeout 2 --max-time 5 http://192.168.11.1:1448/api/core/slam/v1/localization/pose
curl --connect-timeout 2 --max-time 5 http://192.168.11.1:1448/api/core/system/v1/robot/health
curl --connect-timeout 2 --max-time 5 http://192.168.11.1:1448/api/core/motion/v1/actions/:current
```

## Repository Work in Progress

### Tianyi concierge action integration

Robot Guide now owns a self-contained copy of the recorder-format Tianyi model,
poses, action definitions, and NPZ trajectories. It does not use
`tianyi_hw_bridge`, an HTTP action service, or files from another checkout at
runtime. It subscribes directly to `/arm/status` and publishes directly to
`/arm/cmd_pos`, limited to motors 11-17 and 21-27.

The direct runtime validates the pinned URDF hash, action/pose/trajectory schema,
17-joint recorder order, timing, joint limits, all 14 live arm statuses, motor
errors, temperature, and vendor command subscriber availability. Only the two
arms are extracted for hardware commands.

Every Guide POI requires speech content and may have an ordered action list. A
task moves to `concierge_init` before navigation, then uses
`navigate -> (ordered action sequence + speech)` at each POI. Actions execute
one by one while speech plays concurrently, and the POI completes only after
both finish. With an empty action list, the arms stay at `concierge_init` while
speech plays. Every configured action must start and finish at `concierge_init`.
Initialization failure prevents departure, while action failure keeps the base
at the POI.

The real robot successfully completed full guide tasks using the direct arm
runtime and returned to the home dock; post-run arm preflight reported all 14
motors ready with no error.

### Existing map and guide work

The map-management UI work and guide-departure fix are implemented but not
committed. Map management adds current map identification, strict
`asset/*.stcm` selection, map switching, single-floor sync, and robot snapshots
saved only to `output/`.

Relevant changed/new files:

- `README.md`
- `app/ui_guide/tabs/map_building_tab.py`
- `app/ui_guide/ui_main.py`
- `component/map_building/service.py`
- `component/map_building/map_identity.py`
- `component/task_execution/executor.py`
- `util/slam_helper/map_client.py`
- `tests/test_map_management.py`
- `tests/test_task_execution.py`
- `AGENTS.md`

Preserve the user's unrelated `config/task.json` modification and untracked
`asset/office2_poi.stcm`. No commit has been created.
