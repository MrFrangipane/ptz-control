import logging
import os
import threading
from collections import deque
from datetime import datetime
from typing import Callable

from flask import Flask, jsonify, render_template_string, request
from visca_over_ip import Camera


PAGE_TEMPLATE = ""
with open(os.path.join(os.path.dirname(__file__), "page.html"), "r", encoding="utf-8") as f:
    PAGE_TEMPLATE = f.read()


class PTZController:
    HOLD_REPEAT_SECONDS = 0.2

    def __init__(self) -> None:
        self.camera_host = os.getenv("PTZ_CAMERA_HOST", "192.168.20.173")
        self.camera: Camera | None = None
        self.status = "Not connected"
        self._offset_factor = 1.0

        self._lock = threading.RLock()
        self.logs: deque[str] = deque(maxlen=300)

        self.logger = logging.getLogger("ptz")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.logger.addHandler(self._build_log_handler())

        self._connect_camera()

    def _build_log_handler(self) -> logging.Handler:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

        original_emit = handler.emit

        def emit(record: logging.LogRecord) -> None:
            original_emit(record)
            self.logs.append(handler.format(record))

        handler.emit = emit  # type: ignore[method-assign]
        return handler

    def _set_status(self, message: str) -> None:
        self.status = message

    def _connect_camera(self) -> None:
        with self._lock:
            try:
                self.camera = Camera(self.camera_host)
                self._set_status("Connected")
                self.logger.info("Connected to camera at %s", self.camera_host)
            except Exception:
                self.camera = None
                self._set_status("Connection failed")
                self.logger.exception("Connection failed")

    def set_camera_host(self, camera_host: str) -> None:
        camera_host = camera_host.strip()
        if not camera_host:
            self._set_status("Camera host is required")
            self.logger.warning("Camera host change skipped: empty value")
            return

        with self._lock:
            self.camera_host = camera_host
            self.camera = None
            self._set_status("Connecting")
            self.logger.info("Changing camera to %s", self.camera_host)

        self._connect_camera()

    def _run_camera_cmd(self, label: str, fn: Callable[[], None]) -> None:
        with self._lock:
            if self.camera is None:
                self._set_status("Camera not connected")
                self.logger.warning("%s skipped: camera not connected", label)
                return
            try:
                fn()
                self._set_status(label)
                self.logger.info("%s", label)
            except Exception:
                self._set_status(f"{label} failed")
                self.logger.exception("%s failed", label)

    def _pan_tilt_offset(self, pan_offset: int = 0, tilt_offset: int = 0, speed: int = 20) -> None:
        assert self.camera is not None
        pan, tilt = self.camera.get_pantilt_position()
        print(pan, tilt)
        self.camera.pantilt(
            pan_speed=speed,
            tilt_speed=speed,
            pan_position=pan + int(pan_offset * self._offset_factor),
            tilt_position=tilt + int(tilt_offset * self._offset_factor),
        )

    def _zoom_offset(self, zoom_offset: int) -> None:
        assert self.camera is not None
        zoom = self.camera.get_zoom_position()
        new_value = max(0, min(zoom + zoom_offset, 16384))
        self.logger.info("Zooming to %d", new_value)
        self.camera.zoom_to(new_value / 16384.0)

    def _focus(self) -> None:
        assert self.camera is not None
        self.camera.set_focus_mode("manual")
        self.camera.set_focus_mode("auto")

    def handle_action(self, action: str) -> None:
        actions: dict[str, Callable[[], None]] = {
            "pan_left": lambda: self._run_camera_cmd("Pan left", lambda: self._pan_tilt_offset(pan_offset=-30)),
            "pan_right": lambda: self._run_camera_cmd("Pan right", lambda: self._pan_tilt_offset(pan_offset=+30)),
            "tilt_up": lambda: self._run_camera_cmd("Tilt up", lambda: self._pan_tilt_offset(tilt_offset=+30)),
            "tilt_down": lambda: self._run_camera_cmd("Tilt down", lambda: self._pan_tilt_offset(tilt_offset=-30)),
            "zoom_in": lambda: self._run_camera_cmd("Zoom in", lambda: self._zoom_offset(zoom_offset=+100)),
            "zoom_out": lambda: self._run_camera_cmd("Zoom out", lambda: self._zoom_offset(zoom_offset=-100)),
            "recall_preset_1": lambda: self._run_camera_cmd("Recall preset 1", lambda: self.camera.recall_preset(1)),
            "recall_preset_2": lambda: self._run_camera_cmd("Recall preset 2", lambda: self.camera.recall_preset(2)),
            "recall_preset_3": lambda: self._run_camera_cmd("Recall preset 3", lambda: self.camera.recall_preset(3)),
            "recall_preset_4": lambda: self._run_camera_cmd("Recall preset 4", lambda: self.camera.recall_preset(4)),
            "recall_preset_5": lambda: self._run_camera_cmd("Recall preset 5", lambda: self.camera.recall_preset(5)),
            "recall_preset_6": lambda: self._run_camera_cmd("Recall preset 6", lambda: self.camera.recall_preset(6)),
            "save_preset_1": lambda: self._run_camera_cmd("Save preset 1", lambda: self.camera.save_preset(1)),
            "save_preset_2": lambda: self._run_camera_cmd("Save preset 2", lambda: self.camera.save_preset(2)),
            "save_preset_3": lambda: self._run_camera_cmd("Save preset 3", lambda: self.camera.save_preset(3)),
            "save_preset_4": lambda: self._run_camera_cmd("Save preset 4", lambda: self.camera.save_preset(4)),
            "save_preset_5": lambda: self._run_camera_cmd("Save preset 5", lambda: self.camera.save_preset(5)),
            "save_preset_6": lambda: self._run_camera_cmd("Save preset 6", lambda: self.camera.save_preset(6)),
            "speed_slow": lambda: self._set_speed(0.25, "Speed slow"),
            "speed_normal": lambda: self._set_speed(1.0, "Speed normal"),
            "speed_fast": lambda: self._set_speed(2.0, "Speed fast"),
            "force_autofocus": lambda: self._run_camera_cmd("Force autofocus", self._focus),
        }

        fn = actions.get(action)
        if fn is None:
            self._set_status(f"No handler for: {action}")
            self.logger.warning("No handler for action '%s'", action)
            return
        fn()

    def _set_speed(self, value: float, label: str) -> None:
        with self._lock:
            self._offset_factor = value
            self._set_status(label)
            self.logger.info("%s", label)


controller = PTZController()
app = Flask(__name__)


@app.get("/")
def index():
    return render_template_string(
        PAGE_TEMPLATE,
        camera_host=controller.camera_host,
        status=controller.status,
        now=datetime.now(),
    )


@app.post("/action")
def action():
    payload = request.get_json(silent=True) or {}
    action_name = str(payload.get("action", "")).strip()
    if action_name:
        controller.handle_action(action_name)

    return jsonify(
        {
            "ok": True,
            "status": controller.status,
            "camera_host": controller.camera_host,
            "logs": list(controller.logs),
        }
    )


@app.post("/camera")
def camera():
    payload = request.get_json(silent=True) or {}
    camera_host = str(payload.get("camera_host", "")).strip()

    if camera_host:
        controller.set_camera_host(camera_host)
    else:
        controller._set_status("Camera host is required")

    return jsonify(
        {
            "ok": bool(camera_host),
            "status": controller.status,
            "camera_host": controller.camera_host,
            "logs": list(controller.logs),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
