from __future__ import annotations

import os
import threading
import time

import requests

from .errors import GuideTaskCancelled


class BodyActionClient:
    """Client for the localhost Tianyi action execution service."""

    TERMINAL_STATUSES = {"completed", "cancelled", "failed"}

    def __init__(self, base_url: str | None = None, session=None) -> None:
        self.base_url = (
            base_url
            or os.getenv("ROBOT_ACTION_BASE_URL", "http://127.0.0.1:8765")
        ).rstrip("/")
        self.session = session or requests.Session()
        self._lock = threading.Lock()
        self._active_execution_id: str | None = None
        self._active_operation = False

    def list_actions(self, *, ready_only: bool = True) -> list[dict]:
        actions = self._request("GET", "/actions", timeout=1.5).get("actions", [])
        if not isinstance(actions, list):
            raise RuntimeError("Robot Action returned an invalid action catalog")
        return [
            action
            for action in actions
            if isinstance(action, dict)
            and (not ready_only or action.get("ready") is True)
        ]

    def health(self) -> dict:
        return self._request("GET", "/health", timeout=5)

    def arm(self, action_ids: list[str], *, confirmed: bool) -> str:
        result = self._request(
            "POST",
            "/arm",
            json={"action_ids": action_ids, "confirmed": confirmed},
        )
        token = str(result.get("arm_token") or "")
        if not token:
            raise RuntimeError("Robot Action did not return an authorization token")
        return token

    def prepare(self, arm_token: str) -> dict:
        with self._lock:
            self._active_operation = True
        try:
            return self._request(
                "POST",
                "/prepare",
                json={"arm_token": arm_token},
                timeout=30,
            )
        finally:
            with self._lock:
                self._active_operation = False

    def execute(
        self,
        action_id: str,
        arm_token: str,
        cancel_event: threading.Event,
        *,
        timeout: float = 120.0,
        poll_interval: float = 0.2,
    ) -> dict:
        execution = self._request(
            "POST",
            "/executions",
            json={"action_id": action_id, "arm_token": arm_token},
        )
        execution_id = str(execution.get("execution_id") or "")
        if not execution_id:
            raise RuntimeError("Robot Action did not return an execution ID")
        with self._lock:
            self._active_execution_id = execution_id
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel_event.is_set():
                    self.cancel_current()
                    raise GuideTaskCancelled("Task was cancelled during body action")
                execution = self._request("GET", f"/executions/{execution_id}")
                status = execution.get("status")
                if status == "completed":
                    return execution
                if status == "cancelled":
                    raise GuideTaskCancelled("Tianyi body action was cancelled")
                if status == "failed":
                    raise RuntimeError(
                        str(execution.get("error") or "Tianyi body action failed")
                    )
                if time.monotonic() >= deadline:
                    self.cancel_current()
                    raise TimeoutError(
                        f"Tianyi body action timed out after {timeout:.1f} seconds"
                    )
                cancel_event.wait(poll_interval)
        finally:
            with self._lock:
                if self._active_execution_id == execution_id:
                    self._active_execution_id = None

    def cancel_current(self) -> bool:
        with self._lock:
            execution_id = self._active_execution_id
            operation_active = self._active_operation
        if execution_id is None and not operation_active:
            return False
        if execution_id is None:
            try:
                result = self._request("DELETE", "/current")
            except Exception:
                return False
            return result.get("status") != "idle"
        try:
            self._request("DELETE", f"/executions/{execution_id}")
        except Exception:
            return False
        return True

    def _request(self, method: str, path: str, **kwargs) -> dict:
        timeout = kwargs.pop("timeout", 5)
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Robot Action service is unavailable at {self.base_url}: {exc}"
            ) from exc
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"Robot Action returned invalid JSON (HTTP {response.status_code})"
            ) from exc
        if not response.ok:
            detail = payload.get("error") if isinstance(payload, dict) else payload
            raise RuntimeError(
                f"Robot Action request failed (HTTP {response.status_code}): {detail}"
            )
        if not isinstance(payload, dict):
            raise RuntimeError("Robot Action response must be a JSON object")
        return payload
