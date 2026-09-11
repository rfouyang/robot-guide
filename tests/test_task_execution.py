import unittest
from unittest.mock import Mock

from component.task_execution.executor import GuideTaskExecutor


class GuideTaskExecutionTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "id": "task-1",
            "name": "guide",
            "stops": [
                {
                    "poi_id": "poi-1",
                    "poi_name": "Welcome",
                    "content": "Hello",
                    "poi": {
                        "id": "poi-1",
                        "pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
                    },
                }
            ],
        }

    def make_executor(self, docking_status="not_on_dock"):
        task_designer = Mock()
        task_designer.get_task.return_value = self.task
        slam = Mock()
        slam.power.get_status.return_value = {
            "dockingStatus": docking_status,
        }
        body_actions = Mock()
        body_actions.arm.return_value = "arm-token"
        body_actions.cancel_current.return_value = False
        executor = GuideTaskExecutor(
            task_designer,
            slam=slam,
            body_actions=body_actions,
        )
        executor.preflight = Mock(return_value={"task": self.task})
        executor.speech = Mock()
        executor.speech.prepare.return_value = "welcome.mp3"
        executor.navigation = Mock()
        executor._perform_undock = Mock()
        executor._return_home = Mock()
        return executor

    def task_with_body_action(self):
        task = {
            **self.task,
            "stops": [{**self.task["stops"][0]}],
        }
        task["stops"][0]["action"] = {
            "action_id": "concierge_welcome",
            "phase": "before_speech",
            "required": True,
        }
        return task

    def test_fresh_task_departs_with_first_navigation(self):
        executor = self.make_executor()

        events = list(executor.run_events("task-1"))

        executor._perform_undock.assert_not_called()
        executor.navigation.navigate.assert_called_once()
        executor._return_home.assert_called_once()
        self.assertEqual(events[-1]["status"], "completed")
        self.assertIn("planned navigation", events[2]["message"])

    def test_navigation_failure_on_dock_does_not_run_recovery(self):
        executor = self.make_executor(docking_status="on_dock")
        executor.navigation.navigate.side_effect = RuntimeError("move rejected")

        events = list(executor.run_events("task-1"))

        executor._perform_undock.assert_not_called()
        executor._return_home.assert_not_called()
        self.assertNotIn("recovering", [event["status"] for event in events])
        self.assertEqual(events[-1]["status"], "failed")
        self.assertNotIn("returned to the dock", events[-1]["message"])

    def test_navigation_failure_after_departure_runs_recovery(self):
        executor = self.make_executor(docking_status="not_on_dock")
        executor.navigation.navigate.side_effect = RuntimeError("path blocked")

        events = list(executor.run_events("task-1"))

        executor._return_home.assert_called_once()
        self.assertIn("recovering", [event["status"] for event in events])
        self.assertIn("returned to the dock", events[-1]["message"])

    def test_body_action_runs_after_navigation_and_before_speech(self):
        executor = self.make_executor()
        task = self.task_with_body_action()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}
        calls = []
        executor.navigation.navigate.side_effect = lambda *args, **kwargs: calls.append(
            "navigate"
        )
        executor.body_actions.prepare.side_effect = lambda *args, **kwargs: calls.append(
            "prepare"
        )
        executor.body_actions.execute.side_effect = lambda *args, **kwargs: calls.append(
            "action"
        )
        executor.speech.play.side_effect = lambda *args, **kwargs: calls.append("speech")

        events = list(
            executor.run_events("task-1", body_actions_confirmed=True)
        )

        self.assertEqual(calls, ["navigate", "prepare", "action", "speech"])
        executor.body_actions.arm.assert_called_once_with(
            ["concierge_welcome"],
            confirmed=True,
        )
        self.assertIn("body_preparing", [event["status"] for event in events])
        self.assertIn("body_action", [event["status"] for event in events])
        self.assertEqual(events[-1]["status"], "completed")

    def test_body_action_requires_run_confirmation(self):
        executor = self.make_executor()
        task = self.task_with_body_action()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}

        events = list(executor.run_events("task-1"))

        executor.navigation.navigate.assert_not_called()
        executor.body_actions.arm.assert_not_called()
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("Confirm physical Tianyi body actions", events[-1]["message"])

    def test_body_action_failure_keeps_base_at_poi(self):
        executor = self.make_executor()
        task = self.task_with_body_action()
        executor.task_designer.get_task.return_value = task
        executor.preflight.return_value = {"task": task}
        executor.body_actions.execute.side_effect = RuntimeError("arm controller failed")

        events = list(
            executor.run_events("task-1", body_actions_confirmed=True)
        )

        executor._return_home.assert_not_called()
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("remains at its current location", events[-1]["message"])


if __name__ == "__main__":
    unittest.main()
