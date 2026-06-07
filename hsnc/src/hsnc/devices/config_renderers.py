"""Renderer factory routing devices to their platform-native config renderer.

The renderers themselves live with their platform code:

* :class:`~hsnc.devices.openwrt.config_renderer.UciConfigRenderer`
* :class:`~hsnc.devices.jetstream.config_renderer.JetStreamCliRenderer`

They are re-exported here for convenience so existing import sites keep working.
"""

from __future__ import annotations

from ..entities import Device
from ..enums import DeviceKind
from ..interfaces import DeviceConfigRenderer, DeviceConfigRendererFactory
from .jetstream.config_renderer import JetStreamCliRenderer
from .openwrt.config_renderer import UciConfigRenderer

__all__ = [
    "DefaultConfigRendererFactory",
    "JetStreamCliRenderer",
    "UciConfigRenderer",
]


class DefaultConfigRendererFactory(DeviceConfigRendererFactory):
    """Routes devices to the UCI or JetStream renderer by platform.

    Any device whose model advertises OpenWrt is rendered with ``uci``; other
    managed switches use the JetStream CLI. Gateways and access points in this
    project are OpenWrt-based and default to ``uci``.
    """

    def __init__(self) -> None:
        self._uci = UciConfigRenderer()
        self._jetstream = JetStreamCliRenderer()

    def for_device(self, device: Device) -> DeviceConfigRenderer:
        if "openwrt" in device.model.lower():
            return self._uci
        if device.kind is DeviceKind.SWITCH:
            return self._jetstream
        return self._uci
