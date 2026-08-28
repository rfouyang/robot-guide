from __future__ import annotations

from util.slam_helper import SLAM


class PoiManager:
    """Manage the Guide POI catalog."""

    def __init__(self, slam: SLAM) -> None:
        self.slam = slam
        self._pois = None
        self._start_pose = None

    def list(self):
        return self.slam.poi.get_all()

    def get_view(self):
        robot_pose = self.slam.localization.get_robot_pose()
        quality = self.slam.localization.get_localization_quality()
        start_pose = self.slam.home_dock.get_home_pose()
        pois = self.list()
        map_status = self.slam.map_client.get_map_status()
        map_info = self.slam.map_client.explore_map(robot_pose)
        map_info["start_pose"] = start_pose
        map_info["home_dock"] = {"pose": start_pose} if start_pose else None
        map_info["pois"] = pois
        self._pois = pois
        self._start_pose = start_pose
        return {
            "image": self.slam.renderer.render_explore_map(map_info),
            "robot_pose": robot_pose,
            "start_pose": start_pose,
            "map_status": map_status,
            "quality": quality,
            "pois": pois,
        }

    def get_live_view(self):
        """Redraw the current map using the robot's latest localized pose."""
        if self._pois is None:
            view = self.get_view()
            return {
                "image": view["image"],
                "robot_pose": view["robot_pose"],
            }

        robot_pose = self.slam.localization.get_robot_pose()
        map_info = self.slam.map_client.explore_map(robot_pose)
        map_info["start_pose"] = self._start_pose
        map_info["home_dock"] = (
            {"pose": self._start_pose} if self._start_pose else None
        )
        map_info["pois"] = self._pois
        return {
            "image": self.slam.renderer.render_explore_map(map_info),
            "robot_pose": robot_pose,
        }

    def create(self, name):
        return self.slam.poi.create(name)

    def delete(self, poi_id):
        return self.slam.poi.delete(poi_id)
