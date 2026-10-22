"""Stand-ins for MicroPython's micropython, bluetooth and aioble modules,
with devices behind them that answer as the protocol says, so the client
runs under any Python 3 with no board and no radio. What the devices send
is what the published SDK made in fixtures/messages.json.

A link here also counts operations that overlap, which a board's Bluetooth
does not allow."""

import asyncio
import sys
import types
from collections import deque

NOTIFY, INDICATE, READ, WRITE = 0x10, 0x20, 0x02, 0x08


def uuid(fill):
    return "f3a1%04x-2c4b-4d1e-9a6f-1b2c3d4e5f60" % fill


class UUID:
    def __init__(self, s):
        self.s = str(s).lower()

    def __eq__(self, other):
        return isinstance(other, UUID) and other.s == self.s

    def __hash__(self):
        return hash(self.s)


class DeviceDisconnectedError(Exception):
    pass


class Characteristic:
    def __init__(self, link, fill, properties, value=b""):
        self.link = link
        self.uuid = UUID(uuid(fill))
        self.fill = fill
        self.properties = properties
        self.value = value
        self.subscribed = None
        self._event = asyncio.Event()
        if properties & NOTIFY:
            self._notify_queue = deque((), 1)
        if properties & INDICATE:
            self._indicate_queue = deque((), 1)

    async def read(self, timeout_ms=1000):
        await self.link.operation()
        return self.value

    async def write(self, data, response=False, timeout_ms=1000):
        await self.link.operation()
        self.link.device.written(self, bytes(data))

    async def subscribe(self, notify=True, indicate=False):
        await self.link.operation()
        self.subscribed = (notify, indicate)

    def deliver(self, data):
        # A device sends only to a host that subscribed.
        if not self.subscribed or not self.link.connected:
            return
        (self._indicate_queue if self.subscribed[1] else self._notify_queue).append(bytes(data))
        self._event.set()

    async def _wait(self, queue_name, timeout_ms):
        while not getattr(self, queue_name):
            if not self.link.connected:
                raise DeviceDisconnectedError()
            self._event.clear()
            if timeout_ms:
                await asyncio.wait_for(self._event.wait(), timeout_ms / 1000)
            else:
                await self._event.wait()
        if not self.link.connected:
            raise DeviceDisconnectedError()
        return getattr(self, queue_name).popleft()

    async def notified(self, timeout_ms=None):
        return await self._wait("_notify_queue", timeout_ms)

    async def indicated(self, timeout_ms=None):
        return await self._wait("_indicate_queue", timeout_ms)


class Service:
    def __init__(self, link):
        self.link = link

    async def characteristic(self, u):
        await self.link.operation()
        return next((c for c in self.link.characteristics if c.uuid == u), None)


class Connection:
    def __init__(self, device):
        self.device = device
        self.connected = True
        self.encrypted = False
        self.paired_with = None
        self.busy = False
        self.overlaps = 0
        self._dropped = asyncio.Event()
        self.characteristics = [
            Characteristic(self, 0x0002, READ, device.info),
            Characteristic(self, 0x0003, WRITE),
            Characteristic(self, 0x0004, INDICATE),
            Characteristic(self, 0x0005, NOTIFY),
            Characteristic(self, 0x0006, READ | NOTIFY, device.status),
            Characteristic(self, 0x000A, NOTIFY),
        ]

    def char(self, fill):
        return next(c for c in self.characteristics if c.fill == fill)

    async def operation(self):
        if not self.connected:
            raise DeviceDisconnectedError()
        if self.busy:
            self.overlaps += 1
        self.busy = True
        await asyncio.sleep(0.001)
        self.busy = False

    def is_connected(self):
        return self.connected

    async def pair(self, **kwargs):
        self.paired_with = kwargs
        self.encrypted = self.device.encrypts

    async def exchange_mtu(self, mtu=None, timeout_ms=1000):
        if self.device.mtu is None:
            raise asyncio.TimeoutError()
        return min(mtu, self.device.mtu)

    async def service(self, u):
        return Service(self) if u == UUID(uuid(0x0001)) else None

    def drop(self):
        self.connected = False
        self._dropped.set()
        for c in self.characteristics:
            c._event.set()

    async def disconnect(self, timeout_ms=2000):
        self.drop()

    async def disconnected(self, timeout_ms=None):
        await self._dropped.wait()


class Device:
    """A device as aioble finds it, and the IntoMind device behind it."""

    def __init__(self, messages, name, rssi, addr, info=0, services=True, encrypts=True, mtu=247, usb=False):
        m = messages
        self.messages = m
        self.name = name
        self.rssi = rssi
        self.addr_type = 0
        self.addr = bytes([addr] * 6)
        self.services = [UUID(uuid(0x0001))] if services else [UUID("0000180f-0000-1000-8000-00805f9b34fb")]
        self.info = bytes.fromhex(m["device_info"][info]["hex"])
        self.status = bytes.fromhex(m["status"][0]["hex"])
        self.encrypts = encrypts
        self.mtu = mtu
        self.usb = usb
        self.stray = False
        self.requests = []
        self.link = None

    async def connect(self, timeout_ms=10000):
        self.link = Connection(self)
        return self.link

    def later(self, char, data, delay=0.002):
        asyncio.get_running_loop().call_later(delay, char.deliver, data)

    def written(self, characteristic, data):
        if characteristic.fill != 0x0003:
            return
        self.requests.append(data.hex())
        m, op = self.messages, data[0]
        answers = self.link.char(0x0004)
        if self.stray:
            self.later(answers, bytes((0x99, 0)), 0.001)
        payload = {
            0x82: m["heads"][0]["hex"], 0x8A: m["head_encoders"][0]["hex"],
            0x42: m["battery"][0]["hex"], 0x84: m["model_info"][0]["hex"],
        }
        if op == 0x01 and self.usb:
            self.later(answers, bytes((op, 7)))
            return
        if op in payload or op in (0x01, 0x02, 0x41, 0x50, 0x80, 0x81):
            self.later(answers, bytes((op, 0)) + bytes.fromhex(payload.get(op, "")))
        else:
            self.later(answers, bytes((op, 2)))
            return
        if op == 0x01:
            for i, p in enumerate(c for c in m["packets"] if c["channels"] == 4):
                self.later(self.link.char(0x0005), bytes.fromhex(p["hex"]), 0.01 + i * 0.002)
        if op == 0x80 and data[1] == 1:
            for i, p in enumerate(m["predictions"]):
                self.later(self.link.char(0x000A), bytes.fromhex(p["hex"]), 0.01 + i * 0.002)


class ScanResult:
    def __init__(self, device):
        self.device = device
        self.rssi = device.rssi

    def name(self):
        return self.device.name or None

    def services(self):
        return iter(self.device.services)


class Scan:
    def __init__(self, world):
        self.world = world

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for d in self.world:
            await asyncio.sleep(0)
            yield ScanResult(d)


def install(world):
    """Put the stand-ins where the client imports them from. Returns what
    they record."""
    record = types.SimpleNamespace(secrets=[], ble_active=[], printed=[])
    micropython = types.ModuleType("micropython")
    micropython.const = lambda x: x
    bluetooth = types.ModuleType("bluetooth")
    bluetooth.UUID = UUID

    class BLE:
        def active(self, on=None):
            record.ble_active.append(on)

    bluetooth.BLE = BLE
    aioble = types.ModuleType("aioble")
    aioble.scan = lambda duration_ms, interval_us=None, window_us=None, active=False: Scan(world)
    aioble.DeviceDisconnectedError = DeviceDisconnectedError
    security = types.ModuleType("aioble.security")
    security.load_secrets = lambda path=None: record.secrets.append(path)
    aioble.security = security
    sys.modules.update({"micropython": micropython, "bluetooth": bluetooth, "aioble": aioble,
                        "aioble.security": security})
    sys.print_exception = record.printed.append
    return record
