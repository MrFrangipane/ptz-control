import logging
import os
from typing import Callable

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Grid, Vertical
from textual.timer import Timer
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from visca_over_ip import Camera


class RichLogHandler(logging.Handler):
    def __init__(self, app: "PTZControlApp") -> None:
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        try:
            self.app.call_from_thread(self.app._write_richlog, message)
        except RuntimeError:
            # Fallback if already on app thread
            self.app._write_richlog(message)


class PTZButtons(Grid):
    """Simple PTZ control pad."""

    SCOPED_CSS = """
    Label {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label()
        yield Button("↑", id="tilt_up", action="tilt_up", variant="primary")
        yield Label()

        yield Button("←", id="pan_left", action="pan_left", variant="primary")
        yield Label()
        yield Button("→", id="pan_right", action="pan_right", variant="primary")

        yield Label()
        yield Button("↓", id="tilt_down", action="tilt_down", variant="primary")
        yield Label()

        yield Button("Zoom -", id="zoom_out", action="zoom_out", variant="error")
        yield Button("Force AF", id="force_autofocus", action="force_autofocus")
        yield Button("Zoom +", id="zoom_in", action="zoom_in", variant="success")

        yield Button("Preset 1", id="recall_preset_1", action="recall_preset_1", variant="warning")
        yield Button("Preset 2", id="recall_preset_2", action="recall_preset_2", variant="warning")
        yield Button("Preset 3", id="recall_preset_3", action="recall_preset_3", variant="warning")

        yield Button("Preset 4", id="recall_preset_4", action="recall_preset_4", variant="warning")
        yield Button("Preset 5", id="recall_preset_5", action="recall_preset_5", variant="warning")
        yield Button("Preset 6", id="recall_preset_6", action="recall_preset_6", variant="warning")

        yield Button("Speed slow", id="speed_slow", action="speed_slow", variant="primary")
        yield Button("Speed normal", id="speed_normal", action="speed_slow", variant="primary")
        yield Button("Speed fast", id="speed_fast", action="speed_slow", variant="primary")

        yield Button("Save 1", id="save_preset_1", action="save_preset_1")
        yield Button("Save 2", id="save_preset_2", action="save_preset_2")
        yield Button("Save 3", id="save_preset_3", action="save_preset_3")

        yield Button("Save 4", id="save_preset_4", action="save_preset_4")
        yield Button("Save 5", id="save_preset_5", action="save_preset_5")
        yield Button("Save 6", id="save_preset_6", action="save_preset_6")


class PTZControlApp(App):
    CSS = """
    Screen {
        align: center middle;
    }

    TabbedContent {
        width: 1fr;
        height: 1fr;
    }

    #root {
        border: round $accent;
        padding: 1 2;
    }

    #status {
        height: 3;
        content-align: center middle;
        border: solid $primary;
        margin-top: 1;
    }

    #richlog {
        border: solid $primary;
    }

    PTZButtons {
        grid-size: 3 9;
        grid-gutter: 1 1;
    }

    PTZButtons Button {
        width: 100%;
    }
    """

    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("up", "tilt_up", "Tilt up"),
        ("down", "tilt_down", "Tilt down"),
        ("left", "pan_left", "Pan left"),
        ("right", "pan_right", "Pan right"),
        ("plus", "zoom_in", "Zoom in"),
        ("minus", "zoom_out", "Zoom out"),
    ]

    HOLDABLE_BUTTONS = {
        "pan_left",
        "pan_right",
        "tilt_up",
        "tilt_down",
        "zoom_in",
        "zoom_out",
    }

    HOLD_REPEAT_SECONDS = 0.2

    def __init__(self) -> None:
        super().__init__()
        self.theme = "textual-light"
        self.camera: Camera | None = None
        self.camera_host = os.getenv("PTZ_CAMERA_HOST", "192.168.20.173")
        self.logger = logging.getLogger("ptz")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self._richlog_handler: RichLogHandler | None = None
        self._hold_button_id: str | None = None
        self._hold_timer: Timer | None = None

        self._offset_factor: float = 1.0

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="controls"):
            with TabPane("Controls", id="controls"):
                with Vertical(id="root"):
                    yield Static(f"Camera: {self.camera_host}")
                    yield PTZButtons()
                    yield Static("Not connected", id="status")
            with TabPane("Logs", id="logs"):
                yield RichLog(id="richlog", wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self._setup_richlog_logging()
        self._connect_camera()

    def _setup_richlog_logging(self) -> None:
        handler = RichLogHandler(self)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        self.logger.addHandler(handler)
        self._richlog_handler = handler

    def _write_richlog(self, message: str) -> None:
        self.query_one("#richlog", RichLog).write(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if not button_id:
            return

        # Holdable actions are driven by mouse down/up + timer.
        # Keep click fallback for keyboard/quick click behavior.
        if button_id in self.HOLDABLE_BUTTONS and self._hold_button_id != button_id:
            self._invoke_action_by_id(button_id)
            return

        self._invoke_action_by_id(button_id)

    def _resolve_button_from_mouse_event(self, event: events.MouseDown) -> Button | None:
        # App-level MouseDown may have widget=None, so resolve target by screen coordinates.
        try:
            target, _region = self.screen.get_widget_at(event.screen_x, event.screen_y)
        except Exception:
            return None

        node = target
        while node is not None and not isinstance(node, Button):
            node = node.parent
        return node if isinstance(node, Button) else None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        button = self._resolve_button_from_mouse_event(event)
        if button is None:
            return

        button_id = button.id
        if not button_id or button_id not in self.HOLDABLE_BUTTONS:
            self.on_button_pressed(Button.Pressed(button))
            return

        self._start_hold(button_id)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._stop_hold()

    def action_stop(self) -> None:
        self._stop_hold()
        self._set_status("Stopped (local hold ended)")
        self.logger.info("Stopped (local hold ended)")

    def _invoke_action_by_id(self, button_id: str) -> None:
        action_name = f"action_{button_id}"
        action = getattr(self, action_name, None)
        if callable(action):
            action()
        else:
            self._set_status(f"No handler for: {button_id}")

    def _start_hold(self, button_id: str) -> None:
        if self._hold_button_id == button_id and self._hold_timer is not None:
            return

        self._stop_hold()
        self._hold_button_id = button_id

        # Fire immediately, then repeat while mouse is held.
        self._invoke_action_by_id(button_id)
        self._hold_timer = self.set_interval(
            self.HOLD_REPEAT_SECONDS,
            lambda: self._invoke_action_by_id(button_id),
        )

    def _stop_hold(self) -> None:
        self._hold_button_id = None
        if self._hold_timer is not None:
            self._hold_timer.stop()
            self._hold_timer = None

    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _connect_camera(self) -> None:
        try:
            self.camera = Camera(self.camera_host)
            self._set_status("Connected")
            self.logger.info("Connected to camera at %s", self.camera_host)
        except Exception:
            self.camera = None
            self._set_status("Connection failed")
            self.logger.exception("Connection failed")

    def _run_camera_cmd(self, label: str, fn: Callable[[], None]) -> None:
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

    def _pan_tilt_offset(self, pan_offset:int=0, tilt_offset:int=0, speed:int =20):
        pan, tilt = self.camera.get_pantilt_position()
        self.camera.pantilt(
            pan_speed=speed, tilt_speed=speed,
            pan_position=pan + int(pan_offset * self._offset_factor),
            tilt_position=tilt + int(tilt_offset * self._offset_factor)
        )

    def _zoom_offset(self, zoom_offset: int):
        zoom = self.camera.get_zoom_position()
        new_value = max(0, min(zoom + zoom_offset, 16384))
        self.logger.info("Zooming to %d", new_value)
        self.camera.zoom_to(new_value / 16384.0)

    def action_pan_left(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self._pan_tilt_offset(pan_offset=-30))

    def action_pan_right(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self._pan_tilt_offset(pan_offset=+30))

    def action_tilt_up(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self._pan_tilt_offset(tilt_offset=+30))

    def action_tilt_down(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self._pan_tilt_offset(tilt_offset=-30))

    def action_zoom_in(self) -> None:
        self._run_camera_cmd("Zoom in", lambda: self._zoom_offset(zoom_offset=+100))

    def action_zoom_out(self) -> None:
        self._run_camera_cmd("Zoom out", lambda: self._zoom_offset(zoom_offset=-100))

    def action_recall_preset_1(self) -> None:
        self._run_camera_cmd("Recall preset 1", lambda: self.camera.recall_preset(1))

    def action_recall_preset_2(self) -> None:
        self._run_camera_cmd("Recall preset 2", lambda: self.camera.recall_preset(2))

    def action_recall_preset_3(self) -> None:
        self._run_camera_cmd("Recall preset 3", lambda: self.camera.recall_preset(3))

    def action_recall_preset_4(self) -> None:
        self._run_camera_cmd("Recall preset 4", lambda: self.camera.recall_preset(4))

    def action_recall_preset_5(self) -> None:
        self._run_camera_cmd("Recall preset 5", lambda: self.camera.recall_preset(5))

    def action_recall_preset_6(self) -> None:
        self._run_camera_cmd("Recall preset 6", lambda: self.camera.recall_preset(6))

    def action_save_preset_1(self) -> None:
        self._run_camera_cmd("Save preset 1", lambda: self.camera.save_preset(1))

    def action_save_preset_2(self) -> None:
        self._run_camera_cmd("Save preset 2", lambda: self.camera.save_preset(2))

    def action_save_preset_3(self) -> None:
        self._run_camera_cmd("Save preset 3", lambda: self.camera.save_preset(3))

    def action_save_preset_4(self) -> None:
        self._run_camera_cmd("Save preset 4", lambda: self.camera.save_preset(4))

    def action_save_preset_5(self) -> None:
        self._run_camera_cmd("Save preset 5", lambda: self.camera.save_preset(5))

    def action_save_preset_6(self) -> None:
        self._run_camera_cmd("Save preset 6", lambda: self.camera.save_preset(6))

    def action_speed_slow(self) -> None:
        self._offset_factor = 0.25

    def action_speed_fast(self) -> None:
        self._offset_factor = 2.0

    def action_speed_normal(self) -> None:
        self._offset_factor = 1.0

    def action_force_autofocus(self) -> None:
        self._run_camera_cmd("Force autofocus", lambda: self._focus())

    def _focus(self):
        self.camera.set_focus_mode("manual")
        self.camera.set_focus_mode("auto")


if __name__ == "__main__":
    PTZControlApp().run()
