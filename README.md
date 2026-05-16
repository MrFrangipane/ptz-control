# PTZ Controller

A small Textual TUI app for VISCA-over-IP PTZ cameras.

## Run

```bash
bash uv run python -m ptzcontroller
```

## Configure camera IP

Set `PTZ_CAMERA_HOST`:

```bash
PTZ_CAMERA_HOST=192.168.20.173 uv run python -m ptzcontroller
```

## Controls

- Arrow keys: pan/tilt
- `+` / `-`: zoom in/out
- `s`: stop
- `d`: toggle dark mode
