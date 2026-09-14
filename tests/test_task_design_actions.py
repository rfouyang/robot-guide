import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from uuid import uuid4

import gradio as gr

from app.ui_guide.state.task_design_state import GuideTaskDesignState
from component.task_design.service import TaskDesigner


class GuideTaskDesignActionTests(unittest.TestCase):
    def setUp(self):
        designer = Mock()
        designer.available_pois.return_value = [
            {"id": "poi-1", "name": "Reception", "type": ""}
        ]
        designer.available_actions.return_value = [
            {
                "action_id": "concierge_welcome",
                "label": "Concierge welcome",
            }
        ]
        designer.list_tasks.return_value = []
        self.state = GuideTaskDesignState(designer)

    @staticmethod
    def actions(*action_ids):
        return [
            {
                "action_id": action_id,
                "phase": "with_speech",
                "required": True,
            }
            for action_id in action_ids
        ]

    def test_add_stop_persists_ordered_body_actions(self):
        result = self.state.add_stop(
            self.state.empty_draft(),
            "poi-1",
            self.actions("concierge_welcome", "concierge_point"),
            "Welcome",
        )

        actions = result[0]["stops"][0]["actions"]
        self.assertEqual(
            [action["action_id"] for action in actions],
            ["concierge_welcome", "concierge_point"],
        )

    def test_workspace_includes_action_dropdown_output(self):
        result = self.state.workspace_state()

        self.assertEqual(len(result), 22)

    def test_workspace_loads_task_without_actions(self):
        task = {
            "id": str(uuid4()),
            "name": "Legacy task",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                }
            ],
        }
        self.state.task_designer.list_tasks.return_value = [task]

        result = self.state.workspace_state()

        self.assertEqual(result[16], "Loaded task: Legacy task")

    def test_add_stop_allows_no_arm_action(self):
        result = self.state.add_stop(
            self.state.empty_draft(),
            "poi-1",
            [],
            "Welcome",
        )

        self.assertEqual(result[0]["stops"][0]["actions"], [])

    def test_action_editor_allows_duplicates_and_reordering(self):
        first = self.state.add_action([], "concierge_welcome")
        second = self.state.add_action(first[1], "concierge_point")
        third = self.state.add_action(second[1], "concierge_welcome")

        moved = self.state.move_action(third[1], 2, -1)

        self.assertEqual(
            [action["action_id"] for action in moved[0]],
            ["concierge_welcome", "concierge_welcome", "concierge_point"],
        )
        self.assertEqual(moved[2], 1)

    def test_action_editor_removes_selected_action(self):
        actions = self.actions("concierge_welcome", "concierge_point")

        result = self.state.remove_action(actions, 0)

        self.assertEqual(
            [action["action_id"] for action in result[0]],
            ["concierge_point"],
        )

    def test_task_resolution_allows_legacy_stop_without_action(self):
        poi_id = str(uuid4())
        slam = Mock()
        slam.poi.get_all.return_value = [
            {"id": poi_id, "metadata": {"display_name": "Reception"}}
        ]
        designer = TaskDesigner(slam=slam)
        task = {
            "id": str(uuid4()),
            "name": "Legacy task",
            "stops": [
                {
                    "poi_id": poi_id,
                    "poi_name": "Reception",
                    "content": "Welcome",
                }
            ],
        }

        resolved = designer.resolve_task(task)

        self.assertEqual(resolved["stops"][0]["actions"], [])

    def test_save_allows_stop_without_action(self):
        poi_id = str(uuid4())
        with TemporaryDirectory() as temporary_directory:
            designer = TaskDesigner(path=Path(temporary_directory) / "task.json")

            saved = designer.save_task(
                "Speech only task",
                [
                    {
                        "poi_id": poi_id,
                        "poi_name": "Reception",
                        "content": "Welcome",
                    }
                ],
            )

            self.assertEqual(saved["stops"][0]["actions"], [])

    def test_save_rejects_unavailable_action(self):
        poi_id = str(uuid4())
        body_actions = Mock()
        body_actions.list_actions.return_value = [
            {"action_id": "concierge_present_left", "ready": True}
        ]
        with TemporaryDirectory() as temporary_directory:
            designer = TaskDesigner(
                path=Path(temporary_directory) / "task.json",
                body_actions=body_actions,
            )

            with self.assertRaisesRegex(ValueError, "missing_action"):
                designer.save_task(
                    "Invalid action task",
                    [
                        {
                            "poi_id": poi_id,
                            "poi_name": "Reception",
                            "content": "Welcome",
                            "actions": [
                                {
                                    "action_id": "missing_action",
                                    "phase": "with_speech",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                )


if __name__ == "__main__":
    unittest.main()
