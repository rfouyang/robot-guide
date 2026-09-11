# Current State Handoff

Updated: 2026-09-11 19:06 CST

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
bound home dock, and robot on-dock and charging. The guide now leaves through
its first POI navigation; do not run a separate undock first.

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

Architecture decision for the next session: `robot-guide` and `robot-action`
must remain independent repositories. Robot Guide must own all logic and data
needed to play Tianyi poses and actions. Its runtime must not import Python code
from `robot-action`, read files from that checkout, call a Robot Action HTTP
service, or require the Robot Action launcher to be running. The
`robot-action` repository is reference material and an independent action
recording/simulation tool only.

The Robot Guide implementation should therefore contain its own:

- Tianyi ROS 2 action client, controller-result waiting, cancellation, and
  hardware/diagnostic preflight logic;
- local `concierge_init` and `concierge_xxx` pose/action definitions or
  validated generated artifacts under Robot Guide configuration/assets;
- action catalog and task-stop action selection data;
- sequence execution using
  `concierge_init -> concierge_xxx -> concierge_init`, after navigation and
  before speech.

Suggested ownership is a Robot Guide workflow module such as
`component/body_action/`, configuration in
`config/concierge_action_config.py`, and pose/action files under
`asset/pose/` or `asset/action/`. The exact internal format can be selected
during implementation, but it must be versioned and usable entirely within
this repository.

Today's local HTTP integration is experimental work and is not the final
architecture. In the next session, rework or remove the Robot Guide
`component/common/body_action.py` HTTP client, `ROBOT_ACTION_BASE_URL`
configuration/documentation, the Robot Action localhost API dependency, and
the dual-service launch instructions. Keep and port the useful behavior:
task-design action selection, explicit run confirmation, result-aware
execution, cancellation, fresh health checks, and deterministic pose-sequence
building.

### Tianyi hardware bridge launcher

Launch the Tianyi 2.0 hardware bridge manually with the maintained script:

```bash
# Start and attach to the reusable tmux session.
/home/nvidia/workspace/launch/launch_tianyi_hw_bridge.sh

# Or start it in the background.
/home/nvidia/workspace/launch/launch_tianyi_hw_bridge.sh --detached
```

The script sources ROS 2 Humble and
`/home/nvidia/workspace/app/tianyi_ws/install/setup.bash`, then runs:

```bash
ros2 launch tianyi_hw_bridge hardware.launch.py \
  robot_variant:=tianyi_inspire_hand
```

It uses the tmux session `tianyi_hardware`. Inspect or manage it with:

```bash
tmux list-sessions
tmux attach-session -t tianyi_hardware
tmux capture-pane -pt tianyi_hardware:0
tmux kill-session -t tianyi_hardware
```

A systemd unit template exists at
`/home/nvidia/workspace/launch/tianyi-hw-bridge.service`, but the bridge should
continue to be launched manually unless an operator explicitly installs and
enables that unit. Starting the bridge controls real Tianyi hardware; confirm
the robot and surrounding area are safe before launch.

Current runtime blocker: the host is still missing
`ros-humble-joint-state-broadcaster` and
`ros-humble-joint-trajectory-controller`. An installation attempt was blocked
by interactive sudo authentication. Until an operator installs those packages,
the Tianyi bridge hardware plugin starts but its six configured controllers do
not load, so no body action can execute.

No physical Tianyi pose or trajectory was commanded during this implementation.

Robot Guide automated verification currently passes 25 tests, compilation, and
`git diff --check`. Robot Action compilation passed. Its ROS-aware `.venv`
dependency sync was stopped at the user's request and remains incomplete; the
download cache was retained under `/tmp/robot-action-uv-cache` for a future
session. No dependency process remains running.

Implementation work stopped here for the day. No further application-code
changes were made after the independent-repository decision, and no physical
robot action was sent.

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
