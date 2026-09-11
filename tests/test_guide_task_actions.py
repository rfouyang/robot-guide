import unittest
from uuid import uuid4

from component.common.guide_task import GuideTask


class GuideTaskActionTests(unittest.TestCase):
    def test_action_round_trips_with_stop(self):
        value = {
            "id": str(uuid4()),
            "name": "Concierge tour",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                    "action": {
                        "action_id": "concierge_welcome",
                        "phase": "before_speech",
                        "required": True,
                    },
                }
            ],
        }

        task = GuideTask.from_dict(value, require_stops=True)

        self.assertEqual(task.to_dict()["stops"][0]["action"], value["stops"][0]["action"])

    def test_existing_stop_without_action_remains_valid(self):
        value = {
            "id": str(uuid4()),
            "name": "Speech-only tour",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                }
            ],
        }

        task = GuideTask.from_dict(value, require_stops=True)

        self.assertNotIn("action", task.to_dict()["stops"][0])

    def test_unknown_action_phase_is_rejected(self):
        value = {
            "id": str(uuid4()),
            "name": "Unsafe concurrency",
            "stops": [
                {
                    "poi_id": str(uuid4()),
                    "poi_name": "Reception",
                    "content": "Welcome",
                    "action": {
                        "action_id": "concierge_welcome",
                        "phase": "during_navigation",
                    },
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "Unsupported guide body action phase"):
            GuideTask.from_dict(value, require_stops=True)


if __name__ == "__main__":
    unittest.main()
