from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from util.slam_helper import SLAM

from .map_identity import MapIdentityRegistry, StcmIdentity, inspect_stcm


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ASSET_DIR = BASE_DIR / "asset"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"


class GuideMapBuilder:
    """Own the Guide workflow for building and saving a map."""

    def __init__(
        self,
        slam: SLAM,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        asset_dir: Path = DEFAULT_ASSET_DIR,
        registry_path: Path | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.asset_dir = Path(asset_dir)
        self.slam = slam
        self.registry = MapIdentityRegistry(
            Path(registry_path) if registry_path else self.output_dir / "map_registry.json"
        )

    def list_asset_maps(self) -> list[dict]:
        """List deployable maps; generated output maps are deliberately excluded."""
        maps = []
        for path in sorted(self.asset_dir.glob("*.stcm"), key=lambda item: item.name):
            if path.is_file() and not path.is_symlink():
                maps.append(
                    {
                        "name": path.name,
                        "path": str(path),
                        "source": f"asset/{path.name}",
                        "size": path.stat().st_size,
                    }
                )
        return maps

    def resolve_asset_map(self, selection: str | Path) -> Path:
        """Resolve a UI choice to a direct child of the authoritative asset folder."""
        selected = Path(str(selection))
        if selected.is_absolute() or selected.parent != Path("."):
            raise ValueError("Select a map by name from the asset map catalog")
        if selected.suffix.lower() != ".stcm":
            raise ValueError("Map filename must use the .stcm extension")

        candidates = {
            Path(item["path"]).resolve(): item for item in self.list_asset_maps()
        }
        resolved = (self.asset_dir / selected.name).resolve()
        if resolved not in candidates:
            raise FileNotFoundError(f"Asset map does not exist: asset/{selected.name}")
        return resolved

    def get_output_path(self, filename: str) -> Path:
        name = Path(filename).name
        if Path(name).suffix.lower() != ".stcm":
            raise ValueError("Map filename must use the .stcm extension")
        return self.output_dir / name

    def get_map_view(self, session: dict | None = None, pois=None) -> dict:
        status = self.get_status(session)
        map_info = self.slam.map_client.explore_map(status["pose"])
        map_info["start_pose"] = (session or {}).get("start_pose")
        map_info["home_dock"] = status.get("home_dock") or (session or {}).get("home_dock")
        map_info["pois"] = pois or []
        return {
            "image": self.slam.renderer.render_explore_map(map_info),
            "status": status,
        }

    def save_map(self, filename: str, **kwargs: Any) -> Path:
        output_path = self.get_output_path(filename)
        return self.slam.map_client.save_map(
            filename=output_path.name,
            output_dir=self.output_dir,
            overwrite=kwargs.get("overwrite", False),
        )

    def _map_operation_preflight(self) -> dict:
        if self.slam.mapping.is_enabled():
            raise RuntimeError("Stop map building before changing the active map")

        map_status = self.slam.map_client.get_map_status()
        if map_status.get("is_managed_by_cloud"):
            raise RuntimeError(
                "Local map changes are blocked while the robot map is managed by cloud"
            )

        health = self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if (
            current_action is not None
            and current_action.get("state", {}).get("status") != 4
        ):
            raise RuntimeError(
                f"Robot has an active action: {current_action.get('action_id')}"
            )

        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        return {"map_status": map_status, "health": health, "power": power}

    @staticmethod
    def _inspect_path(path: Path) -> StcmIdentity:
        return inspect_stcm(path.read_bytes())

    def _asset_identities(self) -> list[tuple[dict, StcmIdentity]]:
        candidates = []
        for item in self.list_asset_maps():
            try:
                candidates.append((item, self._inspect_path(Path(item["path"]))))
            except (OSError, ValueError) as exc:
                logger.warning(f"Cannot inspect asset map {item['source']}: {exc}")
        return candidates

    def get_current_map_identity(self) -> dict:
        """Identify the loaded robot map against asset maps without changing it."""
        map_status = self.slam.map_client.get_map_status()
        load_status = map_status.get("map_load_status", "UNKNOWN")
        try:
            floor = self.slam.map_client.get_robot_current_floor()
        except Exception as exc:
            logger.warning(f"Cannot read current map floor: {exc}")
            floor = {}

        map_id = floor.get("map_id") or map_status.get("current_map_id")
        result = {
            "display_name": "Unknown",
            "source": None,
            "match": "unknown",
            "verified": False,
            "map_id": map_id,
            "load_status": load_status,
            "building": floor.get("building"),
            "floor": floor.get("floor"),
            "mapping": self.slam.mapping.is_enabled(),
            "managed_by_cloud": bool(map_status.get("is_managed_by_cloud")),
            "map_status": map_status,
            "matched_candidates": [],
        }
        try:
            home_dock = self.slam.home_dock.get_current_home_dock()
            dock_data = home_dock.get("data") or {}
            result["home_dock_bound"] = bool(
                home_dock.get("result") and dock_data.get("is_binded")
            )
        except Exception as exc:
            logger.warning(f"Cannot read current home-dock binding: {exc}")
            result["home_dock_bound"] = None

        if load_status != "LOADED":
            return result

        try:
            current = inspect_stcm(self.slam.map_client.get_composite_map())
        except Exception as exc:
            result["identity_error"] = str(exc)
            registered = self.registry.get(map_id)
            if registered:
                result.update(
                    display_name=registered.get("name", "Unknown"),
                    source=registered.get("source"),
                    match="registry",
                )
            return result

        result.update(
            sha256=current.sha256,
            canonical_sha256=current.canonical_sha256,
            dimensions={"width": current.width, "height": current.height},
            origin={"x": current.origin_x, "y": current.origin_y},
            resolution={"x": current.resolution_x, "y": current.resolution_y},
        )
        candidates = self._asset_identities()
        exact = [item for item, identity in candidates if identity.sha256 == current.sha256]
        matches = exact or [
            item
            for item, identity in candidates
            if identity.canonical_sha256 == current.canonical_sha256
        ]
        result["matched_candidates"] = [item["source"] for item in matches]
        if len(matches) == 1:
            item = matches[0]
            result.update(
                display_name=item["name"],
                source=item["source"],
                match="exact" if exact else "normalized",
                verified=True,
            )
        elif len(matches) > 1:
            result.update(
                display_name="Ambiguous asset match",
                match="ambiguous",
            )
        else:
            registered = self.registry.get(map_id)
            if registered:
                result.update(
                    display_name=registered.get("name", "Unknown"),
                    source=registered.get("source"),
                    match="registry",
                )
        return result

    def _register_verified_identity(self, identity: dict) -> None:
        if not identity.get("verified") or not identity.get("map_id"):
            return
        self.registry.set(
            identity["map_id"],
            {
                "name": identity["display_name"],
                "source": identity["source"],
                "canonical_sha256": identity["canonical_sha256"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def switch_map(self, selection: str | Path, **kwargs: Any) -> dict:
        """Persist and load one map selected strictly from the asset catalog."""
        asset_path = self.resolve_asset_map(selection)
        expected = self._inspect_path(asset_path)
        self._map_operation_preflight()
        self.slam.map_client.upload_map(asset_path)
        try:
            self.slam.map_client.reload_map(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"asset/{asset_path.name} was uploaded to robot storage, but "
                "the robot did not reload it successfully"
            ) from exc

        try:
            identity = self.get_current_map_identity()
        except Exception as exc:
            raise RuntimeError(
                f"asset/{asset_path.name} was reloaded, but its active identity "
                "could not be verified"
            ) from exc
        if identity.get("canonical_sha256") != expected.canonical_sha256:
            raise RuntimeError(
                "Robot reloaded a map, but its identity does not match "
                f"asset/{asset_path.name}"
            )
        self._register_verified_identity(identity)
        return identity

    def upload_map(self, map_path: Path, **kwargs: Any) -> dict:
        """Backward-compatible alias with the same asset-only restriction."""
        return self.switch_map(str(map_path), **kwargs)

    @staticmethod
    def _floor_count(document: Any) -> int:
        if isinstance(document, list):
            return len(document)
        if isinstance(document, dict):
            for key in ("floors", "data", "maps"):
                value = document.get(key)
                if isinstance(value, list):
                    return len(value)
                if isinstance(value, dict):
                    try:
                        return GuideMapBuilder._floor_count(value)
                    except ValueError:
                        pass
        raise ValueError("Robot returned an unrecognized floor-list response")

    def sync_current_map(self, **kwargs: Any) -> dict:
        """Persist and reload the robot's current map in single-floor mode."""
        self._map_operation_preflight()
        floor_count = self._floor_count(self.slam.map_client.get_floors())
        if floor_count != 1:
            raise RuntimeError(
                f"Map sync is allowed only with exactly one floor; found {floor_count}"
            )

        self.slam.map_client.sync_map(**kwargs)
        identity = self.get_current_map_identity()
        self._register_verified_identity(identity)
        return identity

    def preflight(self, filename: str = "office2.stcm", **kwargs: Any) -> dict:
        output_path = self.get_output_path(filename)
        if output_path.exists() and not kwargs.get("overwrite", False):
            raise FileExistsError(f"Map already exists: {output_path}")
        if self.slam.mapping.is_enabled():
            raise RuntimeError(
                "Mapping is already active on the robot. This browser session "
                "does not own that build; finish or stop the existing mapping "
                "run before starting a new one."
            )

        health = self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if current_action is not None:
            raise RuntimeError(
                f"Robot has an active action: {current_action.get('action_id')}"
            )

        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        return {
            "health": health,
            "power": power,
            "output_path": str(output_path),
        }

    def start(self, filename: str = "office2.stcm", **kwargs: Any) -> dict:
        dock_name = kwargs.get("dock_name", "office2_charger").strip()
        if not dock_name:
            raise ValueError("Charging dock name cannot be empty")

        preflight = self.preflight(filename, **kwargs)
        mapping_started = False
        self.slam.mapping.clear_map()
        try:
            self.slam.mapping.start()
            mapping_started = True
            self.slam.mapping.wait_enabled(True)
            if kwargs.get("enable_loop_closure", True):
                self.slam.mapping.set_loop_closure(True)

            settle_time = kwargs.get("settle_time", 1.0)
            if settle_time > 0:
                time.sleep(settle_time)

            start_pose = self.slam.localization.get_robot_pose()
            home_dock = self.slam.home_dock.register_home_dock(
                dock_name,
                require_charging=False,
            )
            home_pose = home_dock.get("pose")
            if home_pose:
                self.slam.home_dock.set_home_pose(home_pose)

            session = {
                "active": True,
                "filename": Path(filename).name,
                "output_path": preflight["output_path"],
                "start_pose": start_pose,
                "home_dock": home_dock,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(
                f"Started map build: filename={session['filename']}, "
                f"dock_id={home_dock.get('id')}"
            )
            return session
        except Exception:
            if mapping_started:
                try:
                    self.slam.mapping.stop()
                except Exception:
                    logger.exception("Failed to stop mapping after start error")
            raise

    def stop_active_mapping(self, **kwargs: Any) -> None:
        """Stop a mapping run whose browser session is no longer available.

        This pauses mapping only; it does not clear or save the in-memory map.
        A caller must deliberately invoke it before beginning a replacement map.
        """
        if not self.slam.mapping.is_enabled():
            raise RuntimeError("Mapping is not active")

        self.slam.mapping.stop(timeout=kwargs.get("timeout", 10))
        self.slam.mapping.wait_enabled(
            False,
            timeout=kwargs.get("timeout", 10),
            poll_interval=kwargs.get("poll_interval", 0.25),
        )
        logger.info("Stopped active mapping run without clearing its map")

    def finish(self, session: dict, **kwargs: Any) -> dict:
        if not session or not session.get("active"):
            raise RuntimeError("No active map-building session")

        self.slam.mapping.stop()
        self.slam.mapping.wait_enabled(False)
        final_pose = self.slam.localization.get_robot_pose()

        dock_id = session.get("home_dock", {}).get("id")
        home_dock = self.slam.home_dock.find_home_dock(dock_id) if dock_id else None
        if home_dock is None:
            raise RuntimeError("Registered home dock is missing from the completed map")

        output_path = self.save_map(
            session["filename"],
            overwrite=kwargs.get("overwrite", False),
        )
        result = {
            **session,
            "active": False,
            "home_dock": home_dock,
            "final_pose": final_pose,
            "output_path": str(output_path),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"Finished map build: {output_path}")
        return result

    def get_status(self, session: dict | None = None, **kwargs: Any) -> dict:
        dock_id = (session or {}).get("home_dock", {}).get("id")
        return {
            "mapping": self.slam.mapping.is_enabled(),
            "pose": self.slam.localization.get_robot_pose(),
            "power": self.slam.power.get_status(),
            "home_dock": (
                self.slam.home_dock.find_home_dock(dock_id) if dock_id else None
            ),
        }


def demo_map_build_preflight():
    """Run only non-destructive map-building preflight checks."""
    return GuideMapBuilder(SLAM()).preflight(overwrite=True)


def main():
    print(demo_map_build_preflight())


if __name__ == "__main__":
    main()
