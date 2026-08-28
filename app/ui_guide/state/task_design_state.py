from __future__ import annotations

import copy

import gradio as gr
from loguru import logger


class GuideTaskDesignState:
    """Own task-editor state transitions independently from Gradio layout."""

    def __init__(self, task_designer) -> None:
        self.task_designer = task_designer

    @staticmethod
    def empty_draft():
        return {"id": None, "name": "", "stops": []}

    @staticmethod
    def task_choices(tasks):
        return [(task["name"], task["id"]) for task in tasks]

    @staticmethod
    def poi_choices(pois):
        return [
            (
                f"{poi['name']} ({poi['type']})" if poi["type"] else poi["name"],
                poi["id"],
            )
            for poi in pois
        ]

    @staticmethod
    def sequence_rows(draft):
        return [
            [index, stop["poi_name"], stop["content"]]
            for index, stop in enumerate(draft.get("stops", []), start=1)
        ]

    @staticmethod
    def selection_buttons(selected_index, stop_count):
        selected = selected_index is not None and 0 <= selected_index < stop_count
        return (
            gr.update(interactive=selected and selected_index > 0),
            gr.update(interactive=selected and selected_index < stop_count - 1),
            gr.update(interactive=selected),
            gr.update(interactive=selected),
        )

    def editor_state(self, task=None, message="Ready."):
        draft = copy.deepcopy(task) if task else self.empty_draft()
        task_exists = bool(draft.get("id"))
        move_up, move_down, remove, update = self.selection_buttons(
            None,
            len(draft["stops"]),
        )
        return (
            draft.get("name", ""),
            draft,
            self.sequence_rows(draft),
            None,
            gr.update(value=None),
            "",
            "Select a stop to edit or reorder it.",
            message,
            move_up,
            move_down,
            remove,
            update,
            gr.update(interactive=task_exists),
        )

    def workspace_state(self, selected_task_id=None, message=None):
        tasks = self.task_designer.list_tasks()
        selected_task = next(
            (task for task in tasks if task["id"] == selected_task_id),
            tasks[0] if tasks else None,
        )

        poi_error = None
        try:
            pois = self.task_designer.available_pois()
        except Exception as exc:
            logger.warning(f"Could not load POIs for task editor: {exc}")
            pois = []
            poi_error = exc

        if message is None:
            if poi_error:
                message = f"Tasks loaded, but POIs are unavailable: {poi_error}"
            elif selected_task:
                message = f"Loaded task: {selected_task['name']}"
            else:
                message = "Create a task and add at least one POI."

        editor = list(self.editor_state(selected_task, message))
        editor[4] = gr.update(choices=self.poi_choices(pois), value=None)
        return (
            gr.update(
                choices=self.task_choices(tasks),
                value=selected_task["id"] if selected_task else None,
            ),
            *editor,
        )

    def resolve_poi(self, poi_id):
        if not poi_id:
            raise gr.Error("Choose a POI first")
        try:
            poi = next(
                (
                    poi
                    for poi in self.task_designer.available_pois()
                    if poi["id"] == poi_id
                ),
                None,
            )
        except Exception as exc:
            raise gr.Error(f"Could not read the current POIs: {exc}") from exc
        if poi is None:
            raise gr.Error("The selected POI is no longer in the current map")
        return poi

    def draft_edit_state(self, draft, selected_index=None, message="Draft updated."):
        stops = draft.get("stops", [])
        selected = (
            stops[selected_index]
            if selected_index is not None and 0 <= selected_index < len(stops)
            else None
        )
        move_up, move_down, remove, update = self.selection_buttons(
            selected_index if selected else None,
            len(stops),
        )
        return (
            draft,
            self.sequence_rows(draft),
            selected_index if selected else None,
            gr.update(value=selected["poi_id"] if selected else None),
            selected["content"] if selected else "",
            (
                f"Selected stop {selected_index + 1}: **{selected['poi_name']}**"
                if selected
                else "Select a stop to edit or reorder it."
            ),
            message,
            move_up,
            move_down,
            remove,
            update,
        )

    def add_stop(self, draft, poi_id, content):
        content = str(content or "").strip()
        if not content:
            raise gr.Error("Enter the content the robot should speak at this POI")
        poi = self.resolve_poi(poi_id)
        draft = copy.deepcopy(draft or self.empty_draft())
        draft.setdefault("stops", []).append(
            {"poi_id": poi["id"], "poi_name": poi["name"], "content": content}
        )
        return (
            *self.draft_edit_state(
                draft,
                message=(
                    f"Added {poi['name']} as stop {len(draft['stops'])}. "
                    "Save the task before running it."
                ),
            ),
        )

    def select_stop(self, draft, evt: gr.SelectData):
        if not evt.selected:
            return self.draft_edit_state(draft)[2:]
        raw_index = evt.index[0] if isinstance(evt.index, (tuple, list)) else evt.index
        try:
            selected_index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise gr.Error("Could not determine the selected stop") from exc
        return self.draft_edit_state(
            draft,
            selected_index,
            message=f"Selected stop {selected_index + 1}.",
        )[2:]

    def update_stop(self, draft, selected_index, poi_id, content):
        if selected_index is None:
            raise gr.Error("Select a stop in the sequence first")
        content = str(content or "").strip()
        if not content:
            raise gr.Error("Enter the content the robot should speak at this POI")
        poi = self.resolve_poi(poi_id)
        draft = copy.deepcopy(draft or self.empty_draft())
        if not 0 <= selected_index < len(draft.get("stops", [])):
            raise gr.Error("The selected stop is no longer available")
        draft["stops"][selected_index] = {
            "poi_id": poi["id"],
            "poi_name": poi["name"],
            "content": content,
        }
        return (
            *self.draft_edit_state(
                draft,
                selected_index,
                message=(
                    f"Updated stop {selected_index + 1}. "
                    "Save the task before running it."
                ),
            ),
        )

    def move_stop(self, draft, selected_index, direction):
        draft = copy.deepcopy(draft or self.empty_draft())
        stops = draft.get("stops", [])
        if selected_index is None or not 0 <= selected_index < len(stops):
            raise gr.Error("Select a stop in the sequence first")
        new_index = selected_index + direction
        if not 0 <= new_index < len(stops):
            return (
                *self.draft_edit_state(draft, selected_index, "Stop is already at the edge."),
            )
        stops[selected_index], stops[new_index] = stops[new_index], stops[selected_index]
        return (
            *self.draft_edit_state(
                draft,
                new_index,
                message=f"Moved stop to position {new_index + 1}. Save the task before running it.",
            ),
        )

    def remove_stop(self, draft, selected_index):
        draft = copy.deepcopy(draft or self.empty_draft())
        stops = draft.get("stops", [])
        if selected_index is None or not 0 <= selected_index < len(stops):
            raise gr.Error("Select a stop in the sequence first")
        removed = stops.pop(selected_index)
        return (
            *self.draft_edit_state(
                draft,
                message=(
                    f"Removed {removed['poi_name']} from the task. "
                    "Save the task before running it."
                ),
            ),
        )

    def save_task(self, name, draft):
        try:
            task = self.task_designer.save_task(
                name,
                (draft or {}).get("stops", []),
                task_id=(draft or {}).get("id"),
            )
            tasks = self.task_designer.list_tasks()
        except Exception as exc:
            logger.exception("Failed to save task")
            raise gr.Error(str(exc)) from exc
        return (
            gr.update(choices=self.task_choices(tasks), value=task["id"]),
            *self.editor_state(task, f"Saved task: {task['name']}"),
        )

    def delete_task(self, task_id):
        if not task_id:
            raise gr.Error("Select a saved task first")
        try:
            task = self.task_designer.get_task(task_id)
            self.task_designer.delete_task(task_id)
            return self.workspace_state(message=f"Deleted task: {task['name']}")
        except Exception as exc:
            logger.exception("Failed to delete task")
            raise gr.Error(str(exc)) from exc
