"""An IntoMind device over Bluetooth, from a board: find it, connect, pair
with LE Secure Connections and keep the pairing in a file on the board, and
speak the protocol. The names are the published intomind package's for
Python. Nothing here assumes a particular device: the channels, the rates
and what the device can do all come from what it reports."""

import asyncio
import sys
from collections import deque

import aioble
import bluetooth
from aioble import security
from micropython import const

from . import protocol as P

_INDICATE = const(0x20)
CONNECT_MS = const(10000)
PAIR_MS = const(20000)
ANSWER_MS = const(5000)
# The largest packet this board asks for, the same as the published package.
MTU = const(247)
# Where aioble keeps the pairings.
PAIRINGS = "ble_secrets.json"
_FORGOTTEN = "If this device has forgotten the board, call intomind.forget_pairings() and connect again."

_SERVICE = bluetooth.UUID(P.uuid(P.SERVICE))
_loaded = False


def _load_pairings():
    global _loaded
    if not _loaded:
        security.load_secrets(PAIRINGS)
        _loaded = True


class Refused(Exception):
    """The device answered a request with a status other than ok. `status`
    is the number and `status_name` its name in the protocol."""

    def __init__(self, op, status):
        self.op = op
        self.status = status
        self.status_name = P.STATUS_CODES.get(status, "undefined status %d" % status)
        text = "op 0x%02x -> status %d (%s)" % (op, status, self.status_name)
        if status == P.STATUS_USB_POWER:
            text += ": the device does not record while plugged in. Unplug it to record"
        super().__init__(text)


class Found:
    """A device heard advertising: the name it goes by, how strongly it was
    heard in dBm, and what connect() takes."""

    def __init__(self, name, rssi, device):
        self.name = name
        self.rssi = rssi
        self.device = device

    def __repr__(self):
        return "<Found %r %d dBm>" % (self.name, self.rssi)


def _scanning(seconds):
    return aioble.scan(int(seconds * 1000), interval_us=30000, window_us=30000, active=True)


async def scan(seconds=5):
    """Every IntoMind device heard advertising in `seconds`, the strongest
    first, each by its own name, numbered where two share one."""
    heard = {}
    async with _scanning(seconds) as scanner:
        async for result in scanner:
            if _SERVICE in list(result.services()):
                heard[(result.device.addr_type, bytes(result.device.addr))] = result
    results = sorted(heard.values(), key=lambda r: r.rssi, reverse=True)
    names = P.display_names([r.name() or "" for r in results])
    return [Found(n, r.rssi, r.device) for n, r in zip(names, results)]


async def connect(name="", seconds=5):
    """Connect to the first IntoMind device heard in `seconds` whose name
    starts with `name`, or to one scan() found. Pairs the first time and
    keeps the pairing on the board. Returns a connected Device."""
    if isinstance(name, Found):
        device = Device(name.device, name.name)
    else:
        device = None
        async with _scanning(seconds) as scanner:
            async for result in scanner:
                if _SERVICE not in list(result.services()):
                    continue
                heard = result.name() or ""
                if name and not heard.startswith(name):
                    continue
                device = Device(result.device, heard or P.PRODUCT_NAME)
                break
        if device is None:
            raise OSError("no IntoMind device heard" + (" whose name starts with " + name if name else ""))
    await device.connect()
    return device


def forget_pairings():
    """Forget every device this board has paired with, for one that has
    forgotten the board: the next connection pairs from the start. Bluetooth
    restarts, so connect afresh after this."""
    import os

    try:
        os.remove(PAIRINGS)
    except OSError:
        pass
    security.load_secrets(PAIRINGS)
    bluetooth.BLE().active(False)


class Device:
    """One IntoMind device. connect() returns one already connected.

    Set on_prediction(device, prediction) for what the head running on the
    device says of every window, and on_packet(device, packet) before
    start() for the EEG. Each runs as its message arrives."""

    def __init__(self, ble_device, name=P.PRODUCT_NAME):
        self.ble_device = ble_device
        self.name = name
        self.info = None
        self.connection = None
        self.mtu = 23
        self.streaming = False
        self.on_prediction = None
        self.on_packet = None
        # The board's Bluetooth runs one operation on a link at a time, so
        # every write, read and subscription goes through this lock.
        self._lock = asyncio.Lock()
        self._following_eeg = False

    @property
    def connected(self):
        return self.connection is not None and self.connection.is_connected()

    def can(self, capability):
        """Whether the device claims a capability, from its own info."""
        return self.info.can(capability)

    async def connect(self):
        """Connect, pair the first time and encrypt with the kept pairing
        every time after, and read what the device says about itself."""
        _load_pairings()
        self.connection = await self.ble_device.connect(timeout_ms=CONNECT_MS)
        try:
            try:
                await self.connection.pair(bond=True, le_secure=True, mitm=False, timeout_ms=PAIR_MS)
            except Exception as e:
                raise OSError("pairing failed (%r). %s" % (e, _FORGOTTEN))
            if not self.connection.encrypted:
                raise OSError("the link is not encrypted. " + _FORGOTTEN)
            try:
                self.mtu = await self.connection.exchange_mtu(MTU)
            except Exception:
                pass
            service = await self.connection.service(_SERVICE)
            if service is None:
                raise OSError("this device does not offer the IntoMind service")
            c = {}
            for fill in (P.DEVICE_INFO, P.CONTROL, P.CONTROL_RESPONSE, P.STATUS, P.EEG_DATA, P.PREDICTIONS):
                c[fill] = await service.characteristic(bluetooth.UUID(P.uuid(fill)))
            self._control = c[P.CONTROL]
            self._answers = c[P.CONTROL_RESPONSE]
            self._status = c[P.STATUS]
            self._eeg = c[P.EEG_DATA]
            self._predictions = c[P.PREDICTIONS]
            self.info = P.decode_device_info(await c[P.DEVICE_INFO].read())
            await self._subscribe(self._answers)
            if self._predictions is not None:
                await self._follow(self._predictions, 4, self._prediction)
        except Exception:
            await self.disconnect()
            raise

    async def _subscribe(self, characteristic):
        indicate = bool(characteristic.properties & _INDICATE)
        async with self._lock:
            await characteristic.subscribe(notify=not indicate, indicate=indicate)

    async def _follow(self, characteristic, room, handle):
        # aioble keeps only the newest message. Keep a few, for the ones that
        # arrive while a program is busy.
        indicate = bool(characteristic.properties & _INDICATE)
        if indicate:
            characteristic._indicate_queue = deque((), room)
        else:
            characteristic._notify_queue = deque((), room)
        await self._subscribe(characteristic)
        asyncio.create_task(self._dispatch(characteristic, indicate, handle))

    async def _dispatch(self, characteristic, indicate, handle):
        while self.connected:
            try:
                data = await (characteristic.indicated() if indicate else characteristic.notified())
            except Exception:
                return
            try:
                handle(data)
            except Exception as e:
                sys.print_exception(e)

    def _prediction(self, data):
        if self.on_prediction is not None:
            self.on_prediction(self, P.decode_prediction(data))

    def _packet(self, data):
        if self.on_packet is not None:
            self.on_packet(self, P.decode_packet(data, self.info.channels))

    async def command(self, op, arg=None, timeout_ms=ANSWER_MS):
        """Send one control request, by name or number, and wait for its
        answer. Returns what the answer carries. Raises Refused when the
        device says no."""
        request = P.encode_request(op, arg)
        code = request[0]
        indicate = bool(self._answers.properties & _INDICATE)
        async with self._lock:
            await self._control.write(request, response=True)
            while True:
                if indicate:
                    data = await self._answers.indicated(timeout_ms=timeout_ms)
                else:
                    data = await self._answers.notified(timeout_ms=timeout_ms)
                answer = P.decode_response(data)
                if answer.opcode != code:
                    continue
                if not answer.ok:
                    raise Refused(code, answer.status)
                return answer.payload

    def _require(self, capability, what):
        if not self.can(capability):
            raise OSError("this device cannot " + what)

    async def start(self, samples_per_packet=None, new_epoch=True):
        """Start the stream. Set on_packet first to receive the EEG.
        `samples_per_packet` is a preference, held to what fits one packet on
        this link, and the default is as many as fit. Restarts the sample
        index unless `new_epoch` is false."""
        if self.on_packet is not None and not self._following_eeg:
            await self._follow(self._eeg, 16, self._packet)
            self._following_eeg = True
        fit = min(255, max(1, (self.mtu - 3 - P.DATA_HEADER_LEN) // (3 * max(1, self.info.channels))))
        n = fit if samples_per_packet is None else max(1, min(samples_per_packet, fit))
        await self.command("set_samples_per_packet", n)
        if new_epoch:
            await self.command("reset_epoch")
        await self.command("start_stream")
        self.streaming = True

    async def stop(self):
        """Stop the stream."""
        try:
            await self.command("stop_stream")
        finally:
            self.streaming = False

    async def read_status(self):
        """The Status characteristic, read now."""
        async with self._lock:
            data = await self._status.read()
        return P.decode_status(data)

    async def battery(self):
        """The battery's voltage, charge and charger."""
        self._require("battery_voltage", "report its battery")
        return P.decode_battery(await self.command("get_battery"))

    async def model_info(self):
        """What the device's model can do and is doing."""
        self._require("model", "run a model")
        return P.decode_model_info(await self.command("get_model_info"))

    async def heads(self):
        """The head slots and which one is selected, as (active, heads)."""
        self._require("heads", "hold heads")
        active, heads = P.decode_heads(await self.command("list_heads"))
        if self.info.protocol >= (1, 4):
            try:
                encoders = P.decode_head_encoders(await self.command("list_head_encoders"))
            except Refused:
                encoders = {}
            for h in heads:
                h.encoder_id = encoders.get(h.slot, h.encoder_id)
        return active, heads

    async def select_head(self, slot):
        """Select the head in `slot` as the one that makes predictions."""
        self._require("heads", "hold heads")
        await self.command("select_head", slot)

    async def set_predictions(self, on):
        """Turn predictions on or off. A device refuses this until a head is
        selected."""
        self._require("model", "run a model")
        await self.command("set_predictions", 1 if on else 0)

    async def disconnected(self, timeout_ms=None):
        """Wait until the link drops."""
        if self.connected:
            await self.connection.disconnected(timeout_ms=timeout_ms)

    async def disconnect(self):
        """End the link. The pairing stays on the board."""
        connection, self.connection = self.connection, None
        self.streaming = False
        self._following_eeg = False
        if connection is not None:
            try:
                await connection.disconnect()
            except Exception:
                pass
