import threading
import unittest
from unittest.mock import Mock

from component.common.body_action import BodyActionClient


class BodyActionClientTests(unittest.TestCase):
    @staticmethod
    def response(payload, ok=True, status_code=200):
        response = Mock()
        response.ok = ok
        response.status_code = status_code
        response.json.return_value = payload
        return response

    def test_list_actions_keeps_only_ready_actions(self):
        session = Mock()
        session.request.return_value = self.response(
            {
                "actions": [
                    {"action_id": "ready", "ready": True},
                    {"action_id": "not-ready", "ready": False},
                ]
            }
        )
        client = BodyActionClient("http://robot-action", session=session)

        actions = client.list_actions()

        self.assertEqual([action["action_id"] for action in actions], ["ready"])

    def test_execute_waits_for_completed_status(self):
        session = Mock()
        session.request.side_effect = [
            self.response(
                {
                    "execution_id": "execution-1",
                    "status": "starting",
                },
                status_code=202,
            ),
            self.response({"execution_id": "execution-1", "status": "running"}),
            self.response({"execution_id": "execution-1", "status": "completed"}),
        ]
        client = BodyActionClient("http://robot-action", session=session)

        result = client.execute(
            "concierge_welcome",
            "token",
            threading.Event(),
            poll_interval=0.0,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(session.request.call_count, 3)


if __name__ == "__main__":
    unittest.main()
