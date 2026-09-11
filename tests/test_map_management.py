import json
import struct
import tempfile
import unittest
from pathlib import Path

from component.map_building.map_identity import inspect_stcm
from component.map_building.service import GuideMapBuilder


def make_stcm(
    width,
    height,
    cells,
    *,
    origin_x=0.0,
    origin_y=0.0,
    resolution=1.0,
    semantic_tail=b"semantic-data",
):
    metadata = {
        "dimension_width": str(width),
        "dimension_height": str(height),
        "origin_x": str(origin_x),
        "origin_y": str(origin_y),
        "resolution_x": str(resolution),
        "resolution_y": str(resolution),
    }
    pairs = bytearray()
    for key, value in metadata.items():
        encoded_key = key.encode()
        encoded_value = value.encode()
        pairs.extend(struct.pack("<H", len(encoded_key)))
        pairs.extend(encoded_key)
        pairs.extend(struct.pack("<H", len(encoded_value)))
        pairs.extend(encoded_value)
    layer = struct.pack("<H", len(metadata)) + pairs + bytes(cells) + b"\x00" * 4
    return b"STCM" + b"\x00" * 14 + struct.pack("<I", len(layer)) + layer + semantic_tail


def padded_map():
    return make_stcm(
        4,
        4,
        [
            0, 0, 0, 0,
            0, 10, 20, 0,
            0, 30, 40, 0,
            0, 0, 0, 0,
        ],
        origin_x=-1.0,
        origin_y=-1.0,
    )


def cropped_map():
    return make_stcm(2, 2, [10, 20, 30, 40])


class FakeMapClient:
    def __init__(self, current_map):
        self.current_map = current_map
        self.managed_by_cloud = False
        self.uploaded = []
        self.reloaded = 0
        self.synced = 0
        self.saved = []
        self.floors = [{"building": "default", "floor": "1f"}]

    def get_map_status(self):
        return {
            "map_load_status": "LOADED",
            "current_map_id": "map-123",
            "is_managed_by_cloud": self.managed_by_cloud,
        }

    def get_robot_current_floor(self):
        return {"map_id": "map-123", "building": "default", "floor": "1f"}

    def get_composite_map(self):
        return self.current_map

    def upload_map(self, path):
        self.uploaded.append(Path(path))

    def reload_map(self, **kwargs):
        self.reloaded += 1

    def get_floors(self):
        return self.floors

    def sync_map(self, **kwargs):
        self.synced += 1

    def save_map(self, **kwargs):
        output_path = Path(kwargs["output_dir"]) / kwargs["filename"]
        self.saved.append(kwargs)
        return output_path


class FakeMapping:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def is_enabled(self):
        return self.enabled


class FakeSystemStatus:
    def require_healthy(self):
        return {"healthy": True}


class FakeMotion:
    def get_current_action(self):
        return None


class FakeHomeDock:
    def require_on_dock(self):
        return {"dockingStatus": "on_dock", "isCharging": True}

    def get_current_home_dock(self):
        return {"result": True, "data": {"is_binded": True}}


class FakePower:
    def require_charging(self, **kwargs):
        return kwargs["status"]


class FakeSlam:
    def __init__(self, current_map, mapping=False):
        self.map_client = FakeMapClient(current_map)
        self.mapping = FakeMapping(mapping)
        self.system_status = FakeSystemStatus()
        self.motion = FakeMotion()
        self.home_dock = FakeHomeDock()
        self.power = FakePower()


class MapIdentityTests(unittest.TestCase):
    def test_canonical_identity_ignores_trimmed_unknown_border(self):
        padded = inspect_stcm(padded_map())
        cropped = inspect_stcm(cropped_map())

        self.assertNotEqual(padded.sha256, cropped.sha256)
        self.assertEqual(padded.canonical_sha256, cropped.canonical_sha256)

    def test_semantic_data_remains_part_of_canonical_identity(self):
        first = inspect_stcm(cropped_map())
        changed = inspect_stcm(
            make_stcm(2, 2, [10, 20, 30, 40], semantic_tail=b"other-semantic-data")
        )

        self.assertNotEqual(first.canonical_sha256, changed.canonical_sha256)


class MapManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.asset_dir = root / "asset"
        self.output_dir = root / "output"
        self.asset_dir.mkdir()
        self.output_dir.mkdir()
        (self.asset_dir / "office.stcm").write_bytes(padded_map())
        (self.output_dir / "debug.stcm").write_bytes(cropped_map())
        self.slam = FakeSlam(cropped_map())
        self.service = GuideMapBuilder(
            self.slam,
            output_dir=self.output_dir,
            asset_dir=self.asset_dir,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_only_asset_maps_are_deployable(self):
        self.assertEqual(
            [item["name"] for item in self.service.list_asset_maps()],
            ["office.stcm"],
        )
        with self.assertRaises(ValueError):
            self.service.resolve_asset_map("output/debug.stcm")

    def test_current_robot_map_matches_asset_after_border_crop(self):
        identity = self.service.get_current_map_identity()

        self.assertTrue(identity["verified"])
        self.assertEqual(identity["display_name"], "office.stcm")
        self.assertEqual(identity["source"], "asset/office.stcm")
        self.assertEqual(identity["match"], "normalized")

    def test_switch_is_blocked_while_mapping_before_upload(self):
        self.slam.mapping.enabled = True

        with self.assertRaisesRegex(RuntimeError, "Stop map building"):
            self.service.switch_map("office.stcm")

        self.assertEqual(self.slam.map_client.uploaded, [])
        self.assertEqual(self.slam.map_client.reloaded, 0)

    def test_switch_is_blocked_when_cloud_manages_the_map(self):
        self.slam.map_client.managed_by_cloud = True

        with self.assertRaisesRegex(RuntimeError, "managed by cloud"):
            self.service.switch_map("office.stcm")

        self.assertEqual(self.slam.map_client.uploaded, [])

    def test_switch_uses_asset_and_registers_verified_robot_map(self):
        identity = self.service.switch_map("office.stcm")

        self.assertEqual(
            self.slam.map_client.uploaded,
            [(self.asset_dir / "office.stcm").resolve()],
        )
        self.assertEqual(self.slam.map_client.reloaded, 1)
        self.assertTrue(identity["verified"])
        registry = json.loads((self.output_dir / "map_registry.json").read_text())
        self.assertEqual(registry["maps"]["map-123"]["source"], "asset/office.stcm")

    def test_sync_is_blocked_for_multiple_floors(self):
        self.slam.map_client.floors = [{"floor": "1f"}, {"floor": "2f"}]

        with self.assertRaisesRegex(RuntimeError, "exactly one floor"):
            self.service.sync_current_map()

        self.assertEqual(self.slam.map_client.synced, 0)

    def test_save_robot_snapshot_targets_output_only(self):
        path = self.service.save_map("snapshot.stcm")

        self.assertEqual(path, self.output_dir / "snapshot.stcm")
        self.assertEqual(self.slam.map_client.saved[0]["output_dir"], self.output_dir)


if __name__ == "__main__":
    unittest.main()
