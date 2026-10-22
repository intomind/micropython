"""IntoMind devices from MicroPython, on a Raspberry Pi Pico 2 W.

    import asyncio
    import intomind

    async def main():
        device = await intomind.connect()
        print("Connected to", device.name, "with", device.info.channels, "channels")
        device.on_packet = lambda device, packet: print(packet.index, packet.n_samples)
        await device.start()
        await asyncio.sleep(5)
        await device.stop()
        await device.disconnect()

    asyncio.run(main())

The names are the published intomind package's for Python, for what a
board can do with an IntoMind device. intomind.protocol is the protocol on
its own, in plain Python.
"""

from . import protocol
from .client import Device, Found, Refused, connect, forget_pairings, scan
from .protocol import Battery, DeviceInfo, Head, ModelInfo, Packet, Prediction, Status
