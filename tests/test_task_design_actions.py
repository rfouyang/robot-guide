import unittest
from unittest.mock import Mock

from app.ui_guide.state.task_design_state import GuideTaskDesignState


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

    def test_add_stop_persists_selected_body_action(self):
        result = self.state.add_stop(
            self.state.empty_draft(),
            "poi-1",
            "concierge_welcome",
            "Welcome",
        )

        action = result[0]["stops"][0]["action"]
        self.assertEqual(action["action_id"], "concierge_welcome")
        self.assertEqual(action["phase"], "before_speech")
        self.assertTrue(action["required"])

    def test_workspace_includes_action_dropdown_output(self):
        result = self.state.workspace_state()

        self.assertEqual(len(result), 15)


if __name__ == "__main__":
    unittest.main()
