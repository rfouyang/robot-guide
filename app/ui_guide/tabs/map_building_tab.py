import sys
from pathlib import Path

import gradio as gr
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.ui_guide.context import GUIDE


MAP_BUILD_SERVICE = GUIDE.map_building


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


def save_map_to_output(filename):
    try:
        output_path = MAP_BUILD_SERVICE.save_map(filename, overwrite=True)
    except Exception as exc:
        logger.exception("Failed to save local map backup")
        raise gr.Error(str(exc)) from exc
    return str(output_path), f"**Saved local map:** `{output_path}`"


def upload_map_to_robot(map_file):
    if not map_file:
        raise gr.Error("Choose an STCM map file first")

    map_path = Path(map_file)
    if map_path.suffix.lower() != ".stcm":
        raise gr.Error("Map file must use the .stcm extension")

    try:
        MAP_BUILD_SERVICE.upload_map(map_path)
        image, status = _get_view(None)
    except Exception as exc:
        logger.exception("Failed to upload and load map")
        raise gr.Error(str(exc)) from exc

    return image, _status_text(status), None


def build_map_building_tab():
    session = gr.State({"active": False})
    timer = gr.Timer(2.0, active=True)

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

    status_text = gr.Markdown(
        "**Ready.** Waiting to start from a confirmed charging dock."
    )
    gr.Markdown(
        "**Legend:** 🔵 initial mapping pose · 🟩 charging dock · "
        "🔴 current robot pose"
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
            saved_map = gr.File(label="Saved STCM map", interactive=False)

    with gr.Row():
        backup_filename = gr.Textbox(
            label="Local map backup filename",
            value="office2.stcm",
            scale=3,
        )
        save_button = gr.Button("Save Local Map", scale=1)

    with gr.Row():
        map_upload = gr.File(
            label="STCM map to use on the robot",
            file_types=[".stcm"],
            type="filepath",
            scale=3,
        )
        upload_button = gr.Button("Upload & Use Map", variant="primary", scale=1)

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
    save_button.click(
        fn=save_map_to_output,
        inputs=[backup_filename],
        outputs=[saved_map, status_text],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    upload_button.click(
        fn=upload_map_to_robot,
        inputs=[map_upload],
        outputs=[map_image, status_text, map_upload],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )

    return {
        "session": session,
        "map_image": map_image,
        "status_text": status_text,
        "start_button": start_button,
        "finish_button": finish_button,
        "saved_map": saved_map,
    }


def demo():
    with gr.Blocks(title="Guide Map Building") as ui:
        build_map_building_tab()

    return ui


def main():
    demo().queue(default_concurrency_limit=1).launch(server_name="0.0.0.0")


if __name__ == "__main__":
    main()
