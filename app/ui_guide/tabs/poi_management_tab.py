import sys
from pathlib import Path

import gradio as gr
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.ui_guide.context import GUIDE


POI_MANAGER = GUIDE.poi_management


def _poi_rows(pois):
    rows = []
    for poi in sorted(
        pois,
        key=lambda item: str(
            item.get("metadata", {}).get("display_name") or ""
        ).casefold(),
    ):
        pose = poi.get("pose", {})
        metadata = poi.get("metadata", {})
        rows.append(
            [
                metadata.get("display_name", "Unnamed"),
                metadata.get("type", ""),
                pose.get("x"),
                pose.get("y"),
                pose.get("yaw"),
                poi.get("id", ""),
            ]
        )

    return rows


def _status_text(map_status, quality, poi_count, message=None):
    load_status = map_status.get("map_load_status", "unknown")
    status = (
        f"**Map:** {load_status}  \n"
        f"**Localization quality:** {quality}/100  \n"
        f"**Recorded POIs:** {poi_count}"
    )
    if message:
        status = f"**{message}**  \n" + status

    return status


def _get_map_view():
    view = POI_MANAGER.get_view()
    view["rows"] = _poi_rows(view["pois"])
    view["status"] = _status_text(
        view["map_status"],
        view["quality"],
        len(view["pois"]),
    )
    return view


def refresh_map_view():
    try:
        view = _get_map_view()
    except Exception as exc:
        logger.warning(f"Failed to refresh map and POIs: {exc}")
        return (
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            f"**Refresh failed:** {exc}",
        )

    return (
        view["image"],
        view["rows"],
        view["robot_pose"],
        view["start_pose"],
        view["status"],
    )


def refresh_robot_view():
    """Refresh only the map marker and pose while the robot is moving."""
    try:
        view = POI_MANAGER.get_live_view()
    except Exception as exc:
        logger.warning(f"Failed to refresh robot position: {exc}")
        return gr.skip(), gr.skip()

    return view["image"], view["robot_pose"]


def record_poi(name):
    try:
        poi = POI_MANAGER.create(name)
        view = _get_map_view()
    except Exception as exc:
        logger.exception("Failed to record POI")
        raise gr.Error(str(exc)) from exc

    poi_name = poi["metadata"]["display_name"]
    view["status"] = _status_text(
        view["map_status"],
        view["quality"],
        len(view["rows"]),
        message=f"Recorded POI: {poi_name}",
    )

    return (
        view["image"],
        view["rows"],
        view["robot_pose"],
        view["start_pose"],
        view["status"],
        "",
    )


def select_poi(evt: gr.SelectData):
    row = evt.row_value
    if not evt.selected or not row or len(row) < 6 or not row[5]:
        return (
            None,
            "Select a POI row to delete it.",
            gr.update(interactive=False),
        )

    selected_poi = {"name": str(row[0]), "id": str(row[5])}
    return (
        selected_poi,
        f"Selected POI: **{selected_poi['name']}**",
        gr.update(interactive=True),
    )


def delete_selected_poi(selected_poi):
    if not selected_poi or not selected_poi.get("id"):
        raise gr.Error("Select a POI row first")

    poi_name = selected_poi.get("name") or selected_poi["id"]
    try:
        POI_MANAGER.delete(selected_poi["id"])
        view = _get_map_view()
    except Exception as exc:
        logger.exception("Failed to delete POI")
        raise gr.Error(str(exc)) from exc

    view["status"] = _status_text(
        view["map_status"],
        view["quality"],
        len(view["rows"]),
        message=f"Deleted POI: {poi_name}",
    )

    return (
        view["image"],
        view["rows"],
        view["robot_pose"],
        view["start_pose"],
        view["status"],
        None,
        "Select a POI row to delete it.",
        gr.update(interactive=False),
    )


def build_poi_management_tab():
    selected_poi = gr.State(None)
    timer = gr.Timer(1.5, active=True)

    gr.Markdown(
        "Use your remote control to position the robot, enter a name, and "
        "record its current localized pose as a POI."
    )

    with gr.Row():
        poi_name = gr.Textbox(
            label="New POI name",
            placeholder="Example: Reception desk",
            scale=3,
        )
        record_button = gr.Button("Record POI", variant="primary", scale=1)

    status_text = gr.Markdown("**Loading the current map...**")
    gr.Markdown(
        "**Legend:** 🔵 starting pose · 🟩 charging dock · "
        "🔴 current robot pose · 🟣 recorded POIs"
    )

    with gr.Row():
        poi_table = gr.Dataframe(
            headers=["Name", "Type", "X", "Y", "Yaw", "ID"],
            datatype=["str", "str", "number", "number", "number", "str"],
            type="array",
            label="Recorded POIs",
            interactive=False,
            wrap=True,
            show_search="search",
            scale=3,
        )
        with gr.Column(scale=1):
            selected_poi_text = gr.Markdown("Select a POI row to delete it.")
            delete_poi_button = gr.Button(
                "Delete Selected POI",
                variant="stop",
                interactive=False,
            )

    with gr.Row():
        map_image = gr.Image(
            label="Live map and POIs",
            type="numpy",
            image_mode="RGB",
            interactive=False,
            height=700,
            scale=2,
        )
        with gr.Column(scale=1):
            current_pose = gr.JSON(label="Current robot pose")
            start_pose = gr.JSON(label="Starting / charging pose")

    refresh_outputs = [
        map_image,
        poi_table,
        current_pose,
        start_pose,
        status_text,
    ]
    live_outputs = [map_image, current_pose]
    record_outputs = [*refresh_outputs, poi_name]

    record_button.click(
        fn=record_poi,
        inputs=[poi_name],
        outputs=record_outputs,
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    poi_name.submit(
        fn=record_poi,
        inputs=[poi_name],
        outputs=record_outputs,
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    poi_table.select(
        fn=select_poi,
        outputs=[selected_poi, selected_poi_text, delete_poi_button],
        queue=False,
    )
    delete_poi_button.click(
        fn=delete_selected_poi,
        inputs=[selected_poi],
        outputs=[
            *refresh_outputs,
            selected_poi,
            selected_poi_text,
            delete_poi_button,
        ],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    timer.tick(
        fn=refresh_robot_view,
        outputs=live_outputs,
        concurrency_id="guide-live-pose",
        concurrency_limit=1,
        trigger_mode="always_last",
    )

    return {
        "refresh_outputs": refresh_outputs,
        "map_image": map_image,
        "poi_table": poi_table,
        "record_button": record_button,
        "delete_poi_button": delete_poi_button,
    }


def demo():
    with gr.Blocks(title="Guide POI Management") as ui:
        components = build_poi_management_tab()
        ui.load(
            fn=refresh_map_view,
            outputs=components["refresh_outputs"],
            concurrency_id="guide-robot",
            concurrency_limit=1,
        )

    return ui


def main():
    demo().queue(default_concurrency_limit=1).launch(server_name="0.0.0.0")


if __name__ == "__main__":
    main()
