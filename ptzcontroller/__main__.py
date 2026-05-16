import logging
import os
from typing import Callable

from textual.app import App, ComposeResult
from textual.containers import Grid, Vertical
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

        yield Button("Zoom +", id="zoom_in", action="zoom_in", variant="success")
        yield Label()
        yield Button("Zoom -", id="zoom_out", action="zoom_out", variant="error")

        yield Button("Preset 1", id="recall_preset_1", action="recall_preset_1", variant="warning")
        yield Button("Preset 2", id="recall_preset_2", action="recall_preset_2", variant="warning")
        yield Button("Preset 3", id="recall_preset_3", action="recall_preset_3", variant="warning")

        yield Button("Preset 4", id="recall_preset_4", action="recall_preset_4", variant="warning")
        yield Button("Preset 5", id="recall_preset_5", action="recall_preset_5", variant="warning")
        yield Button("Preset 6", id="recall_preset_6", action="recall_preset_6", variant="warning")

        yield Label()
        yield Label()
        yield Label()

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
        ("s", "stop", "Stop"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.theme = "textual-light"
        self.camera: Camera | None = None
        self.camera_host = os.getenv("PTZ_CAMERA_HOST", "192.168.20.173")
        self.logger = logging.getLogger("ptz")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self._richlog_handler: RichLogHandler | None = None

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
        action_name = f"action_{button_id}"
        action = getattr(self, action_name, None)
        if callable(action):
            action()
        else:
            self._set_status(f"No handler for: {button_id}")

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

    def action_pan_left(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self.camera.pantilt(0, 0, 0))

    def action_pan_right(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self.camera.pantilt(0, 0, 0))

    def action_tilt_up(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self.camera.pantilt(0, 0, 0))

    def action_tilt_down(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self.camera.pantilt(0, 0, 0))

    def action_zoom_in(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self.camera.zoom(0))

    def action_zoom_out(self) -> None:
        self._run_camera_cmd("Pan left", lambda: self.camera.zoom(0))

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


if __name__ == "__main__":
    PTZControlApp().run()
