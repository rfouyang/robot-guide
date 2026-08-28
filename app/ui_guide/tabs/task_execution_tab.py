from functools import partial

import gradio as gr
from loguru import logger

from app.ui_guide.context import GUIDE


PROGRESS_HEADERS = ["Order", "POI", "Status"]


def _task_choices(tasks):
    return [(task["name"], task["id"]) for task in tasks]


def _progress_rows(task, stop_states):
    return [
        [index, stop["poi_name"], stop_states[index - 1]]
        for index, stop in enumerate(task["stops"], start=1)
    ]


def _apply_progress_event(stop_states, event):
    stop_index = event.get("stop_index")
    status = event.get("status")
    if stop_index and 1 <= stop_index <= len(stop_states):
        labels = {
            "preparing": "Preparing speech",
            "navigating": "Navigating",
            "speaking": "Speaking",
            "stop_completed": "Completed",
        }
        if status in labels:
            stop_states[stop_index - 1] = labels[status]
    if status == "completed":
        stop_states[:] = ["Completed"] * len(stop_states)
    elif status in {"failed", "cancelled"}:
        replacement = "Failed" if status == "failed" else "Cancelled"
        for index, value in enumerate(stop_states):
            if value != "Completed":
                stop_states[index] = replacement
                break


def initialize_task_execution():
    return gr.update(choices=_task_choices(GUIDE.task_design.list_tasks()))


def _execute_task_ui(task_id, resume=False):
    if not task_id:
        yield (
            "**Cannot run:** Select and save a task first.",
            [],
            {"status": "failed", "message": "No saved task selected"},
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(interactive=False),
        )
        return

    try:
        task = GUIDE.task_design.get_task(task_id)
        checkpoint = GUIDE.task_execution.get_resume_checkpoint(task_id)
        if resume and checkpoint is None:
            raise RuntimeError("No resumable execution exists for the selected task")
    except Exception as exc:
        yield (
            f"**Cannot run task:** {exc}",
            [],
            {"status": "failed", "message": str(exc)},
            gr.update(interactive=True),
            gr.update(interactive=False),
            gr.update(interactive=False),
        )
        return

    start_stop_index = checkpoint["next_stop_index"] if resume else 0
    stop_states = (
        ["Completed"] * start_stop_index
        + ["Pending"] * (len(task["stops"]) - start_stop_index)
    )
    terminal_statuses = {"completed", "cancelled", "failed"}
    try:
        events = (
            GUIDE.task_execution.resume_events(task_id)
            if resume
            else GUIDE.task_execution.run_events(task_id)
        )
        for event in events:
            _apply_progress_event(stop_states, event)
            terminal = event["status"] in terminal_statuses
            yield (
                f"**{event['status'].replace('_', ' ').title()}:** "
                f"{event['message']}",
                _progress_rows(task, stop_states),
                event,
                gr.update(interactive=terminal),
                gr.update(interactive=not terminal),
                gr.update(
                    interactive=(
                        terminal
                        and GUIDE.task_execution.get_resume_checkpoint(task_id)
                        is not None
                    )
                ),
            )
    except Exception as exc:
        logger.exception("Guide task execution failed")
        event = {"status": "failed", "message": str(exc), "error": str(exc)}
        _apply_progress_event(stop_states, event)
        yield (
            f"**Task failed:** {exc}",
            _progress_rows(task, stop_states),
            event,
            gr.update(interactive=True),
            gr.update(interactive=False),
            gr.update(
                interactive=GUIDE.task_execution.get_resume_checkpoint(task_id)
                is not None
            ),
        )


def run_task_ui(task_id):
    yield from _execute_task_ui(task_id)


def resume_task_ui(task_id):
    yield from _execute_task_ui(task_id, resume=True)


def cancel_task_ui():
    if GUIDE.task_execution.cancel():
        return (
            "**Cancellation requested.** Waiting for the robot to stop and return safely.",
            gr.update(interactive=False),
        )
    return "**No task is currently running.**", gr.update(interactive=False)


def _manual_action_ui(action, label):
    try:
        result = action()
        return f"**{label} complete.**", result
    except Exception as exc:
        logger.exception("Guide manual action failed")
        return f"**{label} failed:** {exc}", {
            "status": "failed",
            "action": label,
            "error": str(exc),
        }


def undock_ui():
    return _manual_action_ui(GUIDE.task_execution.undock, "Undock")


def go_home_ui():
    return _manual_action_ui(GUIDE.task_execution.return_home, "Go home")


def debug_poi_ui(poi_id, poi_name, content):
    try:
        result = GUIDE.task_execution.debug_poi(
            poi_id,
            content=content,
        )
    except Exception as exc:
        logger.exception("Guide POI debug navigation failed")
        return f"**POI debug failed:** {exc}", {
            "status": "failed",
            "poi_id": poi_id,
            "poi_name": poi_name,
            "error": str(exc),
        }

    if result.get("status") == "stopped":
        return "**POI debug navigation stopped; the robot remains there.**", result
    return f"**Arrived at {poi_name} and completed the TTS.**", result


def stop_robot_ui():
    if GUIDE.task_execution.stop():
        return "**Stop requested. All robot movement is being cancelled.**"
    return "**No active robot movement was detected.**"


def build_task_execution_tab():
    task_selector = gr.Dropdown(label="Saved guide task", choices=[])
    refresh_button = gr.Button("Refresh Tasks")
    with gr.Row():
        run_button = gr.Button("Run Selected Task", variant="primary")
        cancel_button = gr.Button(
            "Cancel & Return to Dock",
            variant="stop",
            interactive=False,
        )
    with gr.Row():
        undock_button = gr.Button("Undock")
        go_home_button = gr.Button("Go Home")
        stop_button = gr.Button("Stop Robot", variant="stop")
        resume_button = gr.Button("Resume Task", variant="primary", interactive=False)
    manual_status = gr.Markdown("**Manual robot controls idle.**")
    manual_result = gr.JSON(label="Latest manual robot action")

    with gr.Accordion("Debug Individual POIs", open=True):
        gr.Markdown(
            "Click a POI button to navigate there and speak its configured "
            "arrival content. Select a saved task above first. "
            "The robot will stay at the POI until you stop or move it."
        )
        debug_status = gr.Markdown("**No POI debug navigation running.**")
        debug_result = gr.JSON(label="Latest POI debug action")

        @gr.render(inputs=task_selector)
        def render_debug_poi_buttons(task_id):
            if not task_id:
                gr.Markdown("**Select a saved task to show its POI buttons.**")
                return

            try:
                task = GUIDE.task_design.get_task(task_id)
            except Exception as exc:
                logger.warning(f"Could not load task for POI debugging: {exc}")
                gr.Markdown(f"**Could not load the selected task:** {exc}")
                return

            stops = []
            seen_pois = set()
            for stop in task.get("stops", []):
                if stop["poi_id"] in seen_pois:
                    continue
                seen_pois.add(stop["poi_id"])
                stops.append(stop)
            if not stops:
                gr.Markdown("**The selected task has no POIs.**")
                return

            for stop in stops:
                poi_id = stop["poi_id"]
                poi_name = stop["poi_name"]
                with gr.Row():
                    gr.Markdown(f"**{poi_name}**")
                    button = gr.Button(f"Go to {poi_name} & Speak")
                    button.click(
                        fn=partial(debug_poi_ui, poi_id, poi_name, stop["content"]),
                        outputs=[debug_status, debug_result],
                        queue=False,
                    )

    run_status = gr.Markdown("**Idle.**")
    progress_table = gr.Dataframe(
        headers=PROGRESS_HEADERS,
        datatype=["number", "str", "str"],
        type="array",
        label="Execution progress",
        interactive=False,
        wrap=True,
    )
    last_event = gr.JSON(label="Latest task event")

    run_outputs = [
        run_status,
        progress_table,
        last_event,
        run_button,
        cancel_button,
        resume_button,
    ]
    refresh_button.click(
        fn=initialize_task_execution,
        outputs=[task_selector],
        concurrency_id="guide-task-execution",
        concurrency_limit=1,
    )
    run_button.click(
        fn=run_task_ui,
        inputs=[task_selector],
        outputs=run_outputs,
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    resume_button.click(
        fn=resume_task_ui,
        inputs=[task_selector],
        outputs=run_outputs,
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    cancel_button.click(
        fn=cancel_task_ui,
        outputs=[run_status, cancel_button],
        queue=False,
    )
    undock_button.click(
        fn=undock_ui,
        outputs=[manual_status, manual_result],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    go_home_button.click(
        fn=go_home_ui,
        outputs=[manual_status, manual_result],
        concurrency_id="guide-robot",
        concurrency_limit=1,
    )
    stop_button.click(
        fn=stop_robot_ui,
        outputs=[manual_status],
        queue=False,
    )

    return {
        "task_selector": task_selector,
        "run_outputs": run_outputs,
        "manual_outputs": [manual_status, manual_result],
    }


def demo():
    with gr.Blocks(title="Guide Task Execution") as ui:
        build_task_execution_tab()
    return ui


def main():
    demo().queue(default_concurrency_limit=1).launch(server_name="0.0.0.0")


if __name__ == "__main__":
    main()
