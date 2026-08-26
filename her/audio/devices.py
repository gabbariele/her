"""Accesso a sounddevice, importato pigramente: `her render` non ne ha bisogno."""
from __future__ import annotations

from typing import Any


class AudioUnavailable(RuntimeError):
    pass


def sd() -> Any:
    try:
        import sounddevice  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - dipende dalla macchina
        raise AudioUnavailable(
            "sounddevice non disponibile: installa `pip install sounddevice` "
            "(su Linux serve anche PortAudio: `apt install libportaudio2`)"
        ) from exc
    return sounddevice


def list_devices() -> list[dict]:
    module = sd()
    default_in, default_out = module.default.device
    devices = []
    for index, dev in enumerate(module.query_devices()):
        devices.append(
            {
                "index": index,
                "name": dev["name"],
                "max_input_channels": dev["max_input_channels"],
                "max_output_channels": dev["max_output_channels"],
                "default_samplerate": dev["default_samplerate"],
                "default_input": index == default_in,
                "default_output": index == default_out,
            }
        )
    return devices


def format_devices() -> str:
    rows = []
    for dev in list_devices():
        io = []
        if dev["max_input_channels"]:
            io.append(f"in:{dev['max_input_channels']}")
        if dev["max_output_channels"]:
            io.append(f"out:{dev['max_output_channels']}")
        marks = "".join(["*" if dev["default_input"] else "", "^" if dev["default_output"] else ""])
        rows.append(f"  [{dev['index']:>2}] {dev['name']}  ({', '.join(io)}) {marks}")
    return "\n".join(rows) + "\n  (* input di default, ^ output di default)"
