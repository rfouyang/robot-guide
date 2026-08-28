import json
import math
import sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from loguru import logger


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from util.slam_helper import SLAM


def _map_metadata(map_data, slam):
    metadata, _ = slam.renderer.draw_map(map_data)
    return metadata


def _map_pixel(point, metadata):
    x = round(
        (point["x"] - metadata["origin_x"]) / metadata["resolution"]
    )
    source_y = round(
        (point["y"] - metadata["origin_y"]) / metadata["resolution"]
    )
    return int(x), int(metadata["height"] - 1 - source_y)


def _path_length(points):
    return sum(
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in zip(points, points[1:])
    )


def _check_poi(motion, poi):
    name = poi.get("metadata", {}).get("display_name", "Unnamed")
    pose = poi["pose"]

    try:
        result = motion.search_path(
            pose["x"],
            pose["y"],
            planner_timeout=1000,
            request_timeout=20,
        )
    except requests.RequestException as exc:
        response = exc.response
        detail = response.text.strip() if response is not None else str(exc)
        return {
            "name": name,
            "pose": pose,
            "reachable": False,
            "path_points": [],
            "error": detail or "SearchPath Failed",
        }

    points = result.get("path_points", [])
    return {
        "name": name,
        "pose": pose,
        "reachable": bool(points),
        "path_points": points,
        "error": None if points else "Planner returned an empty path",
    }


def _font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _label(draw, position, text, color, font):
    x, y = position
    box = draw.textbbox((x, y), text, font=font, stroke_width=1)
    draw.rounded_rectangle(
        (box[0] - 4, box[1] - 3, box[2] + 4, box[3] + 3),
        radius=3,
        fill=(255, 255, 255),
        outline=color,
        width=2,
    )
    draw.text(
        (x, y),
        text,
        fill=color,
        font=font,
        stroke_width=1,
        stroke_fill=(255, 255, 255),
    )


def demo_poi_reachability():
    """Plot mapped obstacles and run read-only planner checks for every POI."""
    slam = SLAM()
    robot_pose = slam.localization.get_robot_pose()
    map_info = slam.map_client.explore_map(robot_pose)
    map_info["start_pose"] = slam.home_dock.get_home_pose()
    map_info["home_dock"] = slam.home_dock.require_bound_home_dock()

    map_info["walls"] = slam.map_client.get_virtual_walls()

    pois = slam.poi.get_all()
    results = [_check_poi(slam.motion, poi) for poi in pois]

    image = Image.fromarray(slam.renderer.render_explore_map(map_info))
    metadata = _map_metadata(map_info["map_data"], slam)
    draw = ImageDraw.Draw(image)

    reachable_color = (15, 150, 65)
    unreachable_color = (210, 35, 35)
    label_font = _font(15)
    legend_font = _font(16)

    for result in results:
        points = result["path_points"]
        if points:
            route = [
                _map_pixel({"x": point[0], "y": point[1]}, metadata)
                for point in points
            ]
            draw.line(route, fill=reachable_color, width=4, joint="curve")

    for result in results:
        x, y = _map_pixel(result["pose"], metadata)
        color = reachable_color if result["reachable"] else unreachable_color
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill="white", outline=color, width=4)
        if not result["reachable"]:
            draw.line((x - 6, y - 6, x + 6, y + 6), fill=color, width=3)
            draw.line((x - 6, y + 6, x + 6, y - 6), fill=color, width=3)

        status = "reachable" if result["reachable"] else "no path"
        _label(draw, (x + 13, y - 10), f"{result['name']}: {status}", color, label_font)

    legend = (
        "Dark = mapped obstacle   White = free   Gray = unknown\n"
        "Green = planner path found   Red X = planner found no path"
    )
    legend_box = draw.multiline_textbbox((18, 16), legend, font=legend_font, spacing=5)
    draw.rounded_rectangle(
        (10, 8, legend_box[2] + 10, legend_box[3] + 10),
        radius=5,
        fill=(255, 255, 255),
        outline=(40, 40, 40),
        width=2,
    )
    draw.multiline_text((18, 16), legend, fill=(25, 25, 25), font=legend_font, spacing=5)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_path = OUTPUT_DIR / "poi_reachability_obstacles.png"
    report_path = OUTPUT_DIR / "poi_reachability.json"
    image.save(image_path)

    report = {
        "robot_pose": robot_pose,
        "virtual_wall_count": len(map_info["walls"]),
        "results": [
            {
                "name": result["name"],
                "pose": result["pose"],
                "reachable": result["reachable"],
                "path_point_count": len(result["path_points"]),
                "path_length_m": (
                    _path_length(result["path_points"])
                    if result["path_points"]
                    else None
                ),
                "error": result["error"],
            }
            for result in results
        ],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info(f"Saved POI reachability map: {image_path}")
    logger.info(f"Saved POI reachability report: {report_path}")
    return image_path, report_path, report


def main():
    image_path, report_path, report = demo_poi_reachability()
    print(f"Map: {image_path.resolve()}")
    print(f"Report: {report_path.resolve()}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
