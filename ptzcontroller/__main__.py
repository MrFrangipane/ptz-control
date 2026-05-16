import logging
import os
import threading
from collections import deque
from datetime import datetime
from typing import Callable

from flask import Flask, jsonify, render_template_string, request
from visca_over_ip import Camera


PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>PTZ Controller</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #111827;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --border: #374151;
      --primary: #2563eb;
      --success: #16a34a;
      --warn: #d97706;
      --danger: #dc2626;
    }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      padding: 20px;
    }
    .wrap {
      max-width: 980px;
      margin: 0 auto;
      display: grid;
      gap: 16px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
    }
    h1 { margin: 0 0 8px 0; font-size: 1.3rem; }
    .muted { color: var(--muted); }
    #status {
      margin-top: 8px;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
    }
    .grid {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    button {
      border: 1px solid var(--border);
      background: #1f2937;
      color: var(--text);
      border-radius: 8px;
      padding: 10px 8px;
      cursor: pointer;
      font-size: 0.95rem;
    }
    button:hover { filter: brightness(1.1); }
    .primary { background: #1d4ed8; }
    .success { background: #15803d; }
    .warning { background: #b45309; }
    .danger { background: #b91c1c; }
    .logs {
      margin-top: 8px;
      height: 280px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      background: #0b1220;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.85rem;
      white-space: pre-wrap;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>PTZ Controller</h1>
      <div class="muted">Camera: {{ camera_host }}</div>
      <div id="status">{{ status }}</div>

      <div class="grid">
        <div></div><button class="primary holdable" data-action="tilt_up">↑</button><div></div>
        <button class="primary holdable" data-action="pan_left">←</button><div></div><button class="primary holdable" data-action="pan_right">→</button>
        <div></div><button class="primary holdable" data-action="tilt_down">↓</button><div></div>

        <button class="danger holdable" data-action="zoom_out">Zoom -</button>
        <button data-action="force_autofocus">Force AF</button>
        <button class="success holdable" data-action="zoom_in">Zoom +</button>

        <button class="warning" data-action="recall_preset_1">Preset 1</button>
        <button class="warning" data-action="recall_preset_2">Preset 2</button>
        <button class="warning" data-action="recall_preset_3">Preset 3</button>

        <button class="warning" data-action="recall_preset_4">Preset 4</button>
        <button class="warning" data-action="recall_preset_5">Preset 5</button>
        <button class="warning" data-action="recall_preset_6">Preset 6</button>

        <button class="primary" data-action="speed_slow">Speed slow</button>
        <button class="primary" data-action="speed_normal">Speed normal</button>
        <button class="primary" data-action="speed_fast">Speed fast</button>

        <button data-action="save_preset_1">Save 1</button>
        <button data-action="save_preset_2">Save 2</button>
        <button data-action="save_preset_3">Save 3</button>

        <button data-action="save_preset_4">Save 4</button>
        <button data-action="save_preset_5">Save 5</button>
        <button data-action="save_preset_6">Save 6</button>
      </div>
    </div>

    <div class="card">
      <h1>Logs</h1>
      <div id="logs" class="logs"></div>
    </div>
  </div>

  <script>
    const statusEl = document.getElementById("status");
    const logsEl = document.getElementById("logs");
    let holdTimer = null;

    async function runAction(action) {
      const resp = await fetch("/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action })
      });
      const data = await resp.json();
      statusEl.textContent = data.status || "OK";
      logsEl.textContent = (data.logs || []).join("\\n");
      logsEl.scrollTop = logsEl.scrollHeight;
    }

    function startHold(action) {
      runAction(action);
      holdTimer = setInterval(() => runAction(action), 200);
    }

    function stopHold() {
      if (holdTimer) {
        clearInterval(holdTimer);
        holdTimer = null;
      }
    }

    document.querySelectorAll("button[data-action]").forEach((btn) => {
      const action = btn.dataset.action;
      const holdable = btn.classList.contains("holdable");

      if (!holdable) {
        btn.addEventListener("click", () => runAction(action));
        return;
      }

      btn.addEventListener("mousedown", () => startHold(action));
      btn.addEventListener("mouseup", stopHold);
      btn.addEventListener("mouseleave", stopHold);

      btn.addEventListener("touchstart", (e) => {
        e.preventDefault();
        startHold(action);
      }, { passive: false });
      btn.addEventListener("touchend", stopHold);
      btn.addEventListener("touchcancel", stopHold);
    });
  </script>
</body>
</html>
"""


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
            "logs": list(controller.logs),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)