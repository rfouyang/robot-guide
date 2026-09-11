import sys
from pathlib import Path

import gradio as gr
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.ui_guide.context import GUIDE


MAP_BUILD_SERVICE = GUIDE.map_building


def _asset_choices():
    return [item["name"] for item in MAP_BUILD_SERVICE.list_asset_maps()]


def _identity_text(identity, message=None):
    verified = identity.get("verified", False)
    match = identity.get("match", "unknown")
    if verified:
        verification = f"verified ({match} asset match)"
    elif match == "registry":
        verification = "not verified (cached name only)"
    elif match == "ambiguous":
        verification = "not verified (multiple asset maps match)"
    else:
        verification = "not matched to an asset map"

    floor = " / ".join(
        str(value)
        for value in (identity.get("building"), identity.get("floor"))
        if value not in (None, "")
    ) or "unknown"
    cloud_managed = identity.get("managed_by_cloud")
    cloud_text = (
        "unknown" if cloud_managed is None else ("yes" if cloud_managed else "no")
    )
    mapping = identity.get("mapping")
    mapping_text = (
        "unknown" if mapping is None else ("active" if mapping else "stopped")
    )
    heading = f"**{message}**  \n" if message else ""
    return (
        heading
        + f"**Current robot map:** `{identity.get('display_name', 'Unknown')}`  \n"
        + f"**Identity:** {verification}  \n"
        + f"**Robot map ID:** `{identity.get('map_id') or 'unknown'}`  \n"
        + f"**Load status:** {identity.get('load_status', 'UNKNOWN')}  \n"
        + f"**Floor:** {floor}  \n"
        + f"**Cloud managed:** {cloud_text}  \n"
        + f"**Mapping:** {mapping_text}"
    )


def refresh_current_map_ui(selected=None):
    choices = _asset_choices()
    value = selected if selected in choices else (choices[0] if choices else None)
    try:
        identity = MAP_BUILD_SERVICE.get_current_map_identity()
    except Exception as exc:
        logger.warning(f"Failed to identify current robot map: {exc}")
        identity = {
            "display_name": "Unknown",
            "verified": False,
            "match": "unknown",
            "managed_by_cloud": None,
            "mapping": None,
            "identity_error": str(exc),
        }
    return (
        _identity_text(identity),
        identity,
        gr.update(choices=choices, value=value),
    )


def _status_text(status):
    power = status["power"]
    mapping = "active" if status["mapping"] else "stopped"
    charging = "yes" if power.get("isCharging") else "no"

    return (
        f"**Mapping:** {mapping}  \n"
        f"**Battery:** {power.get('batteryPercentage', 'unknown')}%  \n"
        f"**Dock:** {power.get('dockingStatus', 'unknown')}  \n"
        f"**Charging:** {charging}"
    )


def _get_view(session):
    view = MAP_BUILD_SERVICE.get_map_view(session)
    return view["image"], view["status"]


def start_build_map(filename, dock_name, confirmed, session):
    if session and session.get("active"):
        raise gr.Error("A map-building session is already active")
    if not confirmed:
        raise gr.Error("Confirm that the current in-memory map may be cleared")

    try:
        session = MAP_BUILD_SERVICE.start(filename, dock_name=dock_name)
        image, status = _get_view(session)
    except Exception as exc:
        logger.exception("Failed to start map building")
        raise gr.Error(str(exc)) from exc

    return (
        session,
        image,
        _status_text(status),
        session["start_pose"],
        status["pose"],
        status["power"],
        status.get("home_dock") or session["home_dock"],
        None,
        gr.update(interactive=False),
        gr.update(interactive=False),
        gr.update(interactive=False),
        gr.update(interactive=True),
        gr.update(interactive=False),
    )


def finish_build_map(session):
    try:
        session = MAP_BUILD_SERVICE.finish(session)
        image, status = _get_view(session)
    except Exception as exc:
        logger.exception("Failed to finish map building")
        raise gr.Error(str(exc)) from exc

    return (
        session,
        image,
        _status_text(status),
        status["pose"],
        status["power"],
        status.get("home_dock") or session["home_dock"],
        session["output_path"],
        gr.update(interactive=True),
        gr.update(interactive=True),
        gr.update(interactive=True),
        gr.update(interactive=False),
        gr.update(value=False),
        gr.update(interactive=True),
    )


def stop_existing_mapping(session):
    """Recover after a browser restart left mapping active on the robot."""
    if session and session.get("active"):
        raise gr.Error("Use Finish Build Map for the map-building session in this browser")

    try:
        MAP_BUILD_SERVICE.stop_active_mapping()
        image, status = _get_view(None)
    except Exception as exc:
        logger.exception("Failed to stop existing map building")
        raise gr.Error(str(exc)) from exc

    return (
        {"active": False},
        image,
        _status_text(status),
        status["pose"],
        status["power"],
        status.get("home_dock"),
        gr.update(interactive=True),
        gr.update(interactive=False),
        gr.update(interactive=False),
    )


def refresh_build_map(session):
    if not session or not session.get("active"):
        return (gr.skip(),) * 5

    try:
        image, status = _get_view(session)
    except Exception as exc:
        logger.warning(f"Failed to refresh map preview: {exc}")
        return (
            gr.skip(),
            f"**Preview refresh failed:** {exc}",
            gr.skip(),
            gr.skip(),
            gr.skip(),
        )

    return (
        image,
        _status_text(status),
        status["pose"],
        status["power"],
        status.get("home_dock") or session.get("home_dock"),
    )


def save_map_to_output(filename, overwrite):
    try:
        output_path = MAP_BUILD_SERVICE.save_map(filename, overwrite=overwrite)
    except Exception as exc:
        logger.exception("Failed to save local map backup")
        raise gr.Error(str(exc)) from exc
    return str(output_path), f"**Saved robot snapshot:** `{output_path}`"


def _view_after_map_operation():
    try:
        image, status = _get_view(None)
        return image, _status_text(status)
    except Exception as exc:
        logger.warning(f"Map operation succeeded but preview refresh failed: {exc}")
        return gr.skip(), f"**Live preview refresh failed:** {exc}"


def switch_asset_map(selected, confirmed):
    if not selected:
        raise gr.Error("Choose a map from the asset catalog first")
    if not confirmed:
        raise gr.Error("Confirm the map switch before continuing")
    try:
        identity = MAP_BUILD_SERVICE.switch_map(selected)
        image, build_status = _view_after_map_operation()
    except Exception as exc:
        logger.exception("Failed to switch the robot map")
        raise gr.Error(str(exc)) from exc

    choices = _asset_choices()
    return (
        _identity_text(identity, message=f"Switched to asset/{selected}"),
        identity,
        gr.update(choices=choices, value=selected),
        image,
        build_status,
        f"**Map switch completed and verified:** `asset/{selected}`",
        gr.update(value=False),
    )


def sync_current_map(confirmed):
    if not confirmed:
        raise gr.Error("Confirm the single-floor map sync before continuing")
    try:
        identity = MAP_BUILD_SERVICE.sync_current_map()
        image, build_status = _view_after_map_operation()
    except Exception as exc:
        logger.exception("Failed to synchronize the current robot map")
        raise gr.Error(str(exc)) from exc

    choices = _asset_choices()
    selected = identity.get("display_name") if identity.get("verified") else None
    if selected not in choices:
        selected = choices[0] if choices else None
    return (
        _identity_text(identity, message="Current robot map synchronized"),
        identity,
        gr.update(choices=choices, value=selected),
        image,
        build_status,
        "**Sync completed:** the robot's in-memory map was saved and reloaded.",
        gr.update(value=False),
    )


def build_map_building_tab():
    session = gr.State({"active": False})
    timer = gr.Timer(2.0, active=True)

    gr.Markdown("## Current Robot Map")
    gr.Markdown(
        "Maps available for deployment come only from `asset/`. Downloads from "
        "the robot are saved to `output/` for debugging and are never offered "
        "as selectable maps. Switching or syncing requires the robot to be "
        "docked, charging, healthy, and idle; reload resets localization to "
        "the charging dock."
    )
    current_map_summary = gr.Markdown("**Loading the current robot map...**")
    current_map_details = gr.JSON(label="Current map details")
    with gr.Row():
        asset_map = gr.Dropdown(
            label="Asset map to deploy",
            choices=_asset_choices(),
            value=None,
            allow_custom_value=False,
            scale=3,
        )
        refresh_identity_button = gr.Button("Refresh Current Map", scale=1)

    switch_confirmed = gr.Checkbox(
        label=(
            "I confirm that the selected asset map should replace the stored "
            "robot map and reload at the charging dock"
        )
    )
    switch_button = gr.Button("Switch to Selected Asset Map", variant="primary")

    sync_confirmed = gr.Checkbox(
        label=(
            "I confirm this is a single-floor setup and understand Sync saves "
            "and reloads the robot's current in-memory map"
        )
    )
    sync_button = gr.Button("Sync Current Map to Robot Storage")
    map_operation_status = gr.Markdown("**No map-management operation running.**")

    with gr.Row():
        backup_filename = gr.Textbox(
            label="Robot snapshot filename (saved under output/)",
            value="robot_map.stcm",
            scale=2,
        )
        overwrite_backup = gr.Checkbox(
            label="Overwrite existing output file",
            scale=1,
        )
        save_button = gr.Button("Save Map from Robot", scale=1)
    saved_map = gr.File(label="Saved robot STCM snapshot", interactive=False)

    gr.Markdown("## Build a New Map")
    gr.Markdown(
        "Build a new Guide map from the charging dock. The robot must already "
        "be on the dock and charging before starting."
    )

    with gr.Row():
        filename = gr.Textbox(label="Map filename", value="office2.stcm")
        dock_name = gr.Textbox(label="Charging dock name", value="office2_charger")

    confirmed = gr.Checkbox(
        label="I understand that Start clears the robot's current in-memory map"
    )

    with gr.Row():
        start_button = gr.Button("Start Build Map", variant="primary")
        finish_button = gr.Button("Finish Build Map", interactive=False)
        stop_existing_button = gr.Button(
            "Stop Existing Mapping",
            variant="stop",
            interactive=True,
        )

    status_text = gr.Markdown(
        "**Ready.** Waiting to start from a confirmed charging dock."
    )
    gr.Markdown(
        "**Legend:** 🔵 initial mapping pose · 🟩 charging dock · "
        "🔴 current robot pose"
    )
    gr.Markdown(
        "If the UI was restarted while a map build was running, use **Stop "
        "Existing Mapping** before starting a replacement build. This pauses "
        "mapping but does not clear or save its current in-memory map."
    )

    with gr.Row():
        map_image = gr.Image(
            label="Live map",
            type="numpy",
            image_mode="RGB",
            interactive=False,
            height=700,
            scale=2,
        )
        with gr.Column(scale=1):
            initial_pose = gr.JSON(label="Initial pose")
            current_pose = gr.JSON(label="Current pose")
            power_status = gr.JSON(label="Power status")
            home_dock = gr.JSON(label="Registered charging dock")

    start_button.click(
        fn=start_build_map,
        inputs=[filename, dock_name, confirmed, session],
        outputs=[
            session,
            map_image,
            status_text,
            initial_pose,
            current_pose,
            power_status,
            home_dock,
            saved_map,
            filename,
            dock_name,
            start_button,
            finish_button,
            stop_existing_button,
        ],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    finish_button.click(
        fn=finish_build_map,
        inputs=[session],
        outputs=[
            session,
            map_image,
            status_text,
            current_pose,
            power_status,
            home_dock,
            saved_map,
            filename,
            dock_name,
            start_button,
            finish_button,
            confirmed,
            stop_existing_button,
        ],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    timer.tick(
        fn=refresh_build_map,
        inputs=[session],
        outputs=[map_image, status_text, current_pose, power_status, home_dock],
        concurrency_id="guide-robot",
        concurrency_limit=1,
        trigger_mode="always_last",
    )
    stop_existing_button.click(
        fn=stop_existing_mapping,
        inputs=[session],
        outputs=[
            session,
            map_image,
            status_text,
            current_pose,
            power_status,
            home_dock,
            start_button,
            finish_button,
            stop_existing_button,
        ],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    save_button.click(
        fn=save_map_to_output,
        inputs=[backup_filename, overwrite_backup],
        outputs=[saved_map, map_operation_status],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    refresh_identity_button.click(
        fn=refresh_current_map_ui,
        inputs=[asset_map],
        outputs=[current_map_summary, current_map_details, asset_map],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    switch_button.click(
        fn=switch_asset_map,
        inputs=[asset_map, switch_confirmed],
        outputs=[
            current_map_summary,
            current_map_details,
            asset_map,
            map_image,
            status_text,
            map_operation_status,
            switch_confirmed,
        ],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    sync_button.click(
        fn=sync_current_map,
        inputs=[sync_confirmed],
        outputs=[
            current_map_summary,
            current_map_details,
            asset_map,
            map_image,
            status_text,
            map_operation_status,
            sync_confirmed,
        ],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )

    return {
        "session": session,
        "map_image": map_image,
        "status_text": status_text,
        "start_button": start_button,
        "finish_button": finish_button,
        "stop_existing_button": stop_existing_button,
        "saved_map": saved_map,
        "identity_outputs": [
            current_map_summary,
            current_map_details,
            asset_map,
        ],
    }


def demo():
    with gr.Blocks(title="Guide Map Building") as ui:
        components = build_map_building_tab()
        ui.load(
            fn=refresh_current_map_ui,
            outputs=components["identity_outputs"],
            concurrency_id="guide-robot",
            concurrency_limit=1,
        )

    return ui


def main():
    demo().queue(default_concurrency_limit=1).launch(server_name="0.0.0.0")


if __name__ == "__main__":
    main()
