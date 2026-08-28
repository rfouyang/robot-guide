import sys
from pathlib import Path

import gradio as gr

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if __package__:
    from .tabs.map_building_tab import build_map_building_tab
    from .tabs.poi_management_tab import (
        build_poi_management_tab,
        refresh_map_view,
    )
    from .tabs.task_design_tab import (
        build_task_design_tab,
        initialize_task_ui,
    )
    from .tabs.task_execution_tab import (
        build_task_execution_tab,
        initialize_task_execution,
    )
else:
    from app.ui_guide.tabs.map_building_tab import build_map_building_tab
    from app.ui_guide.tabs.poi_management_tab import (
        build_poi_management_tab,
        refresh_map_view,
    )
    from app.ui_guide.tabs.task_design_tab import (
        build_task_design_tab,
        initialize_task_ui,
    )
    from app.ui_guide.tabs.task_execution_tab import (
        build_task_execution_tab,
        initialize_task_execution,
    )


def create_ui():
    with gr.Blocks(title="Robot Guide") as ui:
        gr.Markdown("# Robot Guide")
        with gr.Tabs():
            with gr.Tab("Map Building"):
                build_map_building_tab()
            with gr.Tab("POI Management"):
                poi_components = build_poi_management_tab()
            with gr.Tab("Task Design"):
                design_components = build_task_design_tab()
            with gr.Tab("Task Execution"):
                execution_components = build_task_execution_tab()

        ui.load(
            fn=refresh_map_view,
            outputs=poi_components["refresh_outputs"],
            concurrency_id="guide-robot",
            concurrency_limit=1,
        )
        ui.load(
            fn=initialize_task_ui,
            outputs=design_components["workspace_outputs"],
            concurrency_id="guide-task-design",
            concurrency_limit=1,
        )
        ui.load(
            fn=initialize_task_execution,
            outputs=[execution_components["task_selector"]],
            concurrency_id="guide-task-execution",
            concurrency_limit=1,
        )

    return ui


def main():
    create_ui().queue(default_concurrency_limit=1).launch(server_name="0.0.0.0")


if __name__ == "__main__":
    main()
