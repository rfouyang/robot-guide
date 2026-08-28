import requests
from loguru import logger

try:
    from .base import Base
except ImportError:
    from util.slam_helper.base import Base


class LocalizationClient:
    def get_robot_pose(self):
        url = f"{Base.BASE_URL}/api/core/slam/v1/localization/pose"

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        pose = response.json()

        logger.info(f"(x, y, z): {pose['x']} {pose['y']} {pose['z']}")
        logger.info(f"(yaw, pitch roll): {pose['yaw']} {pose['pitch']} {pose['roll']})")

        return pose

    def get_localization_quality(self):
        url = f"{Base.BASE_URL}/api/core/slam/v1/localization/quality"

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        quality = int(response.text)

        logger.info(f"Localization quality: {quality}")

        return quality

    def get_home_pose(self):
        """Get the pose of the currently registered charging dock."""
        url = f"{Base.BASE_URL}/api/core/slam/v1/homepose"

        response = requests.get(url, timeout=5)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def demo_localization():
    localization = LocalizationClient()
    return {
        "pose": localization.get_robot_pose(),
        "quality": localization.get_localization_quality(),
    }


def main():
    print(demo_localization())


if __name__ == "__main__":
    main()

