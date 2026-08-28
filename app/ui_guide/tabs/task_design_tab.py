import sys
from pathlib import Path

import gradio as gr
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.ui_guide.context import GUIDE

if __package__:
    from ..state.task_design_state import GuideTaskDesignState
else:
    from app.ui_guide.state.task_design_state import GuideTaskDesignState


TASK_EDITOR_STATE = GuideTaskDesignState(GUIDE.task_design)
SEQUENCE_HEADERS = ["Order", "POI", "Arrival content"]

_empty_draft = TASK_EDITOR_STATE.empty_draft
_task_choices = TASK_EDITOR_STATE.task_choices
_poi_choices = TASK_EDITOR_STATE.poi_choices
_sequence_rows = TASK_EDITOR_STATE.sequence_rows
_selection_buttons = TASK_EDITOR_STATE.selection_buttons
_editor_state = TASK_EDITOR_STATE.editor_state
_resolve_poi = TASK_EDITOR_STATE.resolve_poi
_draft_edit_state = TASK_EDITOR_STATE.draft_edit_state
add_stop_ui = TASK_EDITOR_STATE.add_stop
select_stop_ui = TASK_EDITOR_STATE.select_stop
update_stop_ui = TASK_EDITOR_STATE.update_stop
move_stop_ui = TASK_EDITOR_STATE.move_stop
move_stop_up_ui = lambda draft, selected_index: TASK_EDITOR_STATE.move_stop(
    draft, selected_index, -1
)
move_stop_down_ui = lambda draft, selected_index: TASK_EDITOR_STATE.move_stop(
    draft, selected_index, 1
)
remove_stop_ui = TASK_EDITOR_STATE.remove_stop
save_task_ui = TASK_EDITOR_STATE.save_task
delete_task_ui = TASK_EDITOR_STATE.delete_task


def initialize_task_ui():
    try:
        return TASK_EDITOR_STATE.workspace_state()
    except Exception as exc:
        logger.exception("Failed to initialize task editor")
        raise gr.Error(str(exc)) from exc


def refresh_task_ui(selected_task_id):
    try:
        return TASK_EDITOR_STATE.workspace_state(
            selected_task_id,
            message="Refreshed saved tasks and current-map POIs.",
        )
    except Exception as exc:
        logger.exception("Failed to refresh task editor")
        raise gr.Error(str(exc)) from exc


def new_task_ui():
    return (
        gr.update(value=None),
        *TASK_EDITOR_STATE.editor_state(
            None,
            "New task. Add POIs in the required visit order.",
        ),
    )


def load_task_ui(task_id):
    if not task_id:
        return TASK_EDITOR_STATE.editor_state(
            None,
            "Create a task or select a saved task.",
        )

    try:
        task = GUIDE.task_design.get_task(task_id)
    except Exception as exc:
        logger.exception("Failed to load task")
        raise gr.Error(str(exc)) from exc
    return TASK_EDITOR_STATE.editor_state(task, f"Loaded task: {task['name']}")


def mark_task_unsaved():
    return "Task name changed. Save the task before running it."


def build_task_design_tab():
    draft = gr.State(_empty_draft())
    selected_stop_index = gr.State(None)

    gr.Markdown(
        "Design an ordered Guide route by selecting POIs and configuring "
        "what should be spoken at each stop."
    )

    with gr.Row():
        task_selector = gr.Dropdown(label="Saved task", choices=[], scale=3)
        refresh_button = gr.Button("Refresh Tasks & POIs", scale=1)
        new_button = gr.Button("New Task", scale=1)
        delete_task_button = gr.Button(
            "Delete Task",
            variant="stop",
            interactive=False,
            scale=1,
        )

    task_name = gr.Textbox(
        label="Task name",
        placeholder="Example: Office introduction tour",
    )

    with gr.Row():
        poi_selector = gr.Dropdown(
            label="POI",
            choices=[],
            scale=2,
        )
        stop_content = gr.Textbox(
            label="Content to speak on arrival",
            placeholder="What should the robot say at this POI?",
            lines=3,
            scale=4,
        )
        with gr.Column(scale=1):
            add_stop_button = gr.Button("Add Stop", variant="primary")
            update_stop_button = gr.Button(
                "Update Selected",
                interactive=False,
            )

    sequence_table = gr.Dataframe(
        headers=SEQUENCE_HEADERS,
        datatype=["number", "str", "str"],
        type="array",
        label="Visit sequence",
        interactive=False,
        wrap=True,
        show_row_numbers=False,
        max_height=420,
    )
    selection_text = gr.Markdown("Select a stop to edit or reorder it.")
    with gr.Row():
        move_up_button = gr.Button("Move Up", interactive=False)
        move_down_button = gr.Button("Move Down", interactive=False)
        remove_stop_button = gr.Button(
            "Remove Stop",
            variant="stop",
            interactive=False,
        )
        save_task_button = gr.Button("Save Task", variant="primary")

    editor_status = gr.Markdown("Loading tasks and POIs...")

    editor_outputs = [
        task_name,
        draft,
        sequence_table,
        selected_stop_index,
        poi_selector,
        stop_content,
        selection_text,
        editor_status,
        move_up_button,
        move_down_button,
        remove_stop_button,
        update_stop_button,
        delete_task_button,
    ]
    workspace_outputs = [task_selector, *editor_outputs]
    draft_edit_outputs = [
        draft,
        sequence_table,
        selected_stop_index,
        poi_selector,
        stop_content,
        selection_text,
        editor_status,
        move_up_button,
        move_down_button,
        remove_stop_button,
        update_stop_button,
    ]
    selection_outputs = draft_edit_outputs[2:]
    task_selector.change(
        fn=load_task_ui,
        inputs=[task_selector],
        outputs=editor_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    task_name.input(
        fn=mark_task_unsaved,
        outputs=[editor_status],
        queue=False,
    )
    refresh_button.click(
        fn=refresh_task_ui,
        inputs=[task_selector],
        outputs=workspace_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    new_button.click(
        fn=new_task_ui,
        outputs=workspace_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    delete_task_button.click(
        fn=delete_task_ui,
        inputs=[task_selector],
        outputs=workspace_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    add_stop_button.click(
        fn=add_stop_ui,
        inputs=[draft, poi_selector, stop_content],
        outputs=draft_edit_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    sequence_table.select(
        fn=select_stop_ui,
        inputs=[draft],
        outputs=selection_outputs,
        queue=False,
    )
    update_stop_button.click(
        fn=update_stop_ui,
        inputs=[draft, selected_stop_index, poi_selector, stop_content],
        outputs=draft_edit_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    move_up_button.click(
        fn=move_stop_up_ui,
        inputs=[draft, selected_stop_index],
        outputs=draft_edit_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    move_down_button.click(
        fn=move_stop_down_ui,
        inputs=[draft, selected_stop_index],
        outputs=draft_edit_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    remove_stop_button.click(
        fn=remove_stop_ui,
        inputs=[draft, selected_stop_index],
        outputs=draft_edit_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    save_task_button.click(
        fn=save_task_ui,
        inputs=[task_name, draft],
        outputs=workspace_outputs,
        concurrency_id="guide-task-design",
        concurrency_limit=1,
    )
    return {
        "workspace_outputs": workspace_outputs,
        "task_selector": task_selector,
        "sequence_table": sequence_table,
    }


def demo():
    with gr.Blocks(title="Guide Task Design") as ui:
        components = build_task_design_tab()
        ui.load(fn=initialize_task_ui, outputs=components["workspace_outputs"])
    return ui


def main():
    demo().queue(default_concurrency_limit=1).launch(server_name="0.0.0.0")


if __name__ == "__main__":
    main()
