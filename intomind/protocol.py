"""The IntoMind Bluetooth protocol, version 1.4: the identifiers, the
requests, and what a device sends, read into plain objects. The names are
the published intomind package's for Python. Plain Python, so it runs on a
board and its tests run anywhere."""

import struct
from binascii import hexlify

try:
    from micropython import const
except ImportError:
    def const(x):
        return x

VERSION = (1, 4)
# What the published SDKs call a device heard before its own name.
PRODUCT_NAME = "IntoMind One"


class ProtocolError(Exception):
    """Bytes that are not what the protocol says they should be."""


class Truncated(ProtocolError):
    """A message shorter than its layout."""


class Invalid(ProtocolError):
    """A message, or a request, the protocol does not allow."""


# --- identifiers -------------------------------------------------------------

# The sixteen bits of each identifier that differ from the service's.
SERVICE = const(0x0001)
DEVICE_INFO = const(0x0002)
CONTROL = const(0x0003)
CONTROL_RESPONSE = const(0x0004)
EEG_DATA = const(0x0005)
STATUS = const(0x0006)
UPDATE_CONTROL = const(0x0008)
UPDATE_DATA = const(0x0009)
PREDICTIONS = const(0x000A)
EMBEDDINGS = const(0x000B)


def uuid(fill):
    """A characteristic's full identifier, from its sixteen bits."""
    return "f3a1%04x-2c4b-4d1e-9a6f-1b2c3d4e5f60" % fill


def _hex(b):
    return hexlify(bytes(b)).decode()


def _text(b):
    b = bytes(b).rstrip(b"\0")
    try:
        return b.decode("utf-8")
    except UnicodeError:
        return "".join(chr(c) if c < 0x80 else "?" for c in b)


# --- the control point -------------------------------------------------------

OPCODES = {
    "start_stream": 0x01, "stop_stream": 0x02, "set_rate": 0x10, "set_gain": 0x11,
    "set_mode": 0x20, "set_leadoff": 0x30, "time_sync": 0x40,
    "set_samples_per_packet": 0x41, "get_battery": 0x42, "get_boot_info": 0x43,
    "reset_epoch": 0x50, "clear_bonds": 0x53, "set_predictions": 0x80,
    "select_head": 0x81, "list_heads": 0x82, "remove_head": 0x83,
    "get_model_info": 0x84, "set_prediction_input": 0x85,
    "get_prediction_input": 0x86, "set_bias": 0x32, "get_bias_diagnostic": 0x33,
    "get_pipeline_catalog": 0x90, "get_pipeline": 0x91, "set_pipeline": 0x92,
    "clear_pipeline": 0x93, "restore_pipeline_default": 0x94,
    "get_converter_registers": 0x34, "get_indicator": 0x44, "set_indicator": 0x45,
    "identify": 0x46, "set_embeddings": 0x87, "set_model_interval": 0x88,
    "get_model_interval": 0x89, "get_name": 0x47, "set_name": 0x48,
    "list_head_encoders": 0x8A, "soft_reset": 0xF0,
}
NAME_BY_OPCODE = {v: k for k, v in OPCODES.items()}
# Requests that take one argument byte, and require it.
TAKES_ARG = ("set_rate", "set_gain", "set_mode", "set_leadoff", "set_samples_per_packet",
             "set_predictions", "select_head", "remove_head", "set_bias", "set_indicator",
             "identify", "set_embeddings")
# Requests that carry bytes after the opcode.
TAKES_PAYLOAD = ("set_pipeline", "set_prediction_input", "set_model_interval", "set_name")

STATUS_CODES = {0: "ok", 1: "invalid argument", 2: "unsupported", 3: "busy",
                4: "not streaming", 5: "hardware", 7: "usb power"}
STATUS_OK = const(0)
STATUS_INVALID_ARGUMENT = const(1)
STATUS_UNSUPPORTED = const(2)
STATUS_BUSY = const(3)
STATUS_NOT_STREAMING = const(4)
STATUS_HARDWARE = const(5)
# A stream of the natural signal, refused while the device is on USB power.
STATUS_USB_POWER = const(7)

GAIN_BY_CODE = (1, 2, 4, 6, 8, 12, 24)
RATE_BY_CODE = {4: 1000, 5: 500, 6: 250}
RATE_BY_INFO_BIT = {0: 250, 1: 500, 2: 1000}
MODE_BY_CODE = {0: "normal", 1: "test", 2: "short", 3: "synthetic"}
CHARGER_STATES = {0: "no input", 1: "charging", 2: "complete", 3: "fault", 4: "standby"}
BATTERY_UNKNOWN = const(0xFF)


def encode_request(opcode, arg=None):
    """One control point write. `opcode` is a name or a number. A request
    that takes an argument requires one, and one that does not takes none,
    because the device refuses either mistake."""
    name = opcode if isinstance(opcode, str) else NAME_BY_OPCODE.get(opcode)
    if name not in OPCODES:
        raise Invalid("%r is not an opcode this protocol defines" % (opcode,))
    code = OPCODES[name]
    if name in TAKES_PAYLOAD:
        if not isinstance(arg, (bytes, bytearray)):
            raise Invalid("%s takes a payload of bytes" % name)
        return bytes((code,)) + bytes(arg)
    if (name in TAKES_ARG) != (arg is not None):
        raise Invalid("%s takes %s" % (name, "an argument" if name in TAKES_ARG else "no argument"))
    return bytes((code,)) if arg is None else bytes((code, int(arg) & 0xFF))


class Response:
    """One answer from the control point: the opcode it answers, its status,
    and what it carries."""

    def __init__(self, opcode, status, payload):
        self.opcode = opcode
        self.status = status
        self.payload = payload

    @property
    def ok(self):
        return self.status == STATUS_OK

    @property
    def status_name(self):
        return STATUS_CODES.get(self.status, "undefined status %d" % self.status)


def decode_response(data):
    if len(data) < 2:
        raise Truncated("a response is at least an opcode and a status")
    return Response(data[0], data[1], bytes(data[2:]))


# --- device info -------------------------------------------------------------

CAPABILITIES = {
    "battery_voltage": 1 << 0, "battery_low_flag": 1 << 1, "leadoff": 1 << 2,
    "test_signal": 1 << 3, "dcdc_mode": 1 << 4, "input_short": 1 << 5, "update": 1 << 6,
    "model": 1 << 7, "model_ready": 1 << 8, "heads": 1 << 9, "pipeline": 1 << 10,
    "bias_drive": 1 << 11, "embeddings": 1 << 12, "indicator": 1 << 13,
    "converter_registers": 1 << 14, "model_cadence": 1 << 15,
}
CAPABILITIES_HIGH = {"synthetic": 1 << 0, "device_name": 1 << 1}
INFO_V01_LEN = const(27)
INFO_LEN_1_0 = const(76)
INFO_LEN = const(80)


class DeviceInfo:
    """Everything a device says about itself, and nothing a host assumed."""

    def __init__(self, protocol, firmware, channels, adc_bits, tick_hz, vref_uv, capabilities,
                 supported_rates, device_id, hardware=None, build_id=None, model_embed_dim=0,
                 model_native_sps=0, model_window_samples=0, head_slots=0, head_max_outputs=0,
                 head_slot_bytes=0, update_chunk_max=0, app_slot_bytes=0, weights_image_bytes=0,
                 capabilities_high=0):
        self.protocol = protocol
        self.firmware = firmware
        self.channels = channels
        self.adc_bits = adc_bits
        self.tick_hz = tick_hz
        self.vref_uv = vref_uv
        self.capabilities = capabilities
        self.supported_rates = supported_rates
        self.device_id = device_id
        self.hardware = hardware
        self.build_id = build_id
        self.model_embed_dim = model_embed_dim
        self.model_native_sps = model_native_sps
        self.model_window_samples = model_window_samples
        self.head_slots = head_slots
        self.head_max_outputs = head_max_outputs
        self.head_slot_bytes = head_slot_bytes
        self.update_chunk_max = update_chunk_max
        self.app_slot_bytes = app_slot_bytes
        self.weights_image_bytes = weights_image_bytes
        self.capabilities_high = capabilities_high

    def can(self, capability):
        """Whether the device claims a capability. An unknown name is False,
        so a program written for a later version still runs."""
        if capability in CAPABILITIES_HIGH:
            return bool(self.capabilities_high & CAPABILITIES_HIGH[capability])
        return bool(self.capabilities & CAPABILITIES.get(capability, 0))

    @property
    def rates(self):
        """The sample rates the device supports, slowest first."""
        return sorted(sps for bit, sps in RATE_BY_INFO_BIT.items() if self.supported_rates & (1 << bit))

    def microvolts_per_count(self, gain):
        """One count, in microvolts, at a gain. From the device's own
        reference and width."""
        return (2.0 * self.vref_uv) / (gain * (1 << self.adc_bits))


def decode_device_info(data):
    if len(data) < INFO_V01_LEN:
        raise Truncated("device info is at least %d bytes" % INFO_V01_LEN)
    tick_hz, vref_uv, caps = struct.unpack_from("<IIH", data, 7)
    head = (tuple(data[0:2]), tuple(data[2:5]), data[5], data[6], tick_hz, vref_uv, caps, data[17],
            _hex(data[19:27]))
    if len(data) == INFO_V01_LEN:
        return DeviceInfo(*head)
    if data[27] < INFO_LEN_1_0:
        raise Invalid("device info states it is %d bytes, shorter than the %d of the 1.0 layout"
                      % (data[27], INFO_LEN_1_0))
    if len(data) < INFO_LEN_1_0:
        raise Truncated("device info promises %d bytes and carries %d" % (data[27], len(data)))
    (embed, sps, window, slots, outs, slot_bytes, chunk, app, weights) = struct.unpack_from(
        "<HHHBBHHII", data, 40)
    high = struct.unpack_from("<I", data, 76)[0] if data[27] >= INFO_LEN and len(data) >= INFO_LEN else 0
    return DeviceInfo(*head, hardware=tuple(data[28:31]), build_id=_hex(data[32:40]),
                      model_embed_dim=embed, model_native_sps=sps, model_window_samples=window,
                      head_slots=slots, head_max_outputs=outs, head_slot_bytes=slot_bytes,
                      update_chunk_max=chunk, app_slot_bytes=app, weights_image_bytes=weights,
                      capabilities_high=high)


# --- status ------------------------------------------------------------------

STATUS_LEN = const(12)


class Status:
    """The Status characteristic: streaming, mode, gain, rate, charger,
    battery, contact, and the device's buffer."""

    def __init__(self, streaming, mode, gain, sample_rate_hz, charger, battery_percent, leadoff,
                 usb_present, buffer_high_watermark, dropped_total, buffer_fill):
        self.streaming = streaming
        self.mode = mode
        self.gain = gain
        self.sample_rate_hz = sample_rate_hz
        self.charger = charger
        # None when the device has no battery reading.
        self.battery_percent = battery_percent
        self.leadoff = leadoff
        self.usb_present = usb_present
        self.buffer_high_watermark = buffer_high_watermark
        self.dropped_total = dropped_total
        self.buffer_fill = buffer_fill


def decode_status(data):
    if len(data) < STATUS_LEN:
        raise Truncated("status is %d bytes" % STATUS_LEN)
    (state, mode, gain_code, rate_code, charger, battery, leadoff, flags, dropped,
     fill) = struct.unpack_from("<BBBBBBBBHH", data, 0)
    return Status(state == 1, MODE_BY_CODE.get(mode, "mode %d" % mode),
                  GAIN_BY_CODE[gain_code] if gain_code < len(GAIN_BY_CODE) else None,
                  RATE_BY_CODE.get(rate_code), CHARGER_STATES.get(charger, "charger state %d" % charger),
                  None if battery == BATTERY_UNKNOWN else battery, leadoff, bool(flags & 1),
                  bool(flags & 2), dropped, fill)


# --- the stream ----------------------------------------------------------------

PACKET_EEG = const(0x01)
PACKET_PREDICTION = const(0x02)
# Samples the device generated with its converter off. Never a measurement.
PACKET_SYNTHETIC = const(0x04)
DATA_HEADER_LEN = const(20)


class Packet:
    """One notification of samples, in converter counts. `counts` is a list
    of rows, each one sample across the channels.
    DeviceInfo.microvolts_per_count(packet.gain) scales a count."""

    def __init__(self, discontinuity, leadoff_active, mode, usb_present, samples_lost_before, index,
                 device_time, leadoff, gain, sample_rate_hz, counts, synthetic=False):
        self.discontinuity = discontinuity
        self.leadoff_active = leadoff_active
        self.mode = mode
        self.usb_present = usb_present
        self.samples_lost_before = samples_lost_before
        self.index = index
        self.device_time = device_time
        self.leadoff = leadoff
        self.gain = gain
        self.sample_rate_hz = sample_rate_hz
        self.counts = counts
        self.synthetic = synthetic

    @property
    def n_samples(self):
        return len(self.counts)


def int24(b, at=0):
    """One big endian, two's complement 24 bit number."""
    v = (b[at] << 16) | (b[at + 1] << 8) | b[at + 2]
    return v - 0x1000000 if v & 0x800000 else v


def microvolts(raw, vref_uv, gain, adc_bits):
    """One count in microvolts, from the device's reference, the packet's
    gain and the converter's width."""
    return raw * (2.0 * vref_uv) / (gain * (1 << adc_bits))


def decode_packet(data, channels):
    """One EEG notification. `channels` comes from the device's info."""
    if len(data) < DATA_HEADER_LEN:
        raise Truncated("a data packet is at least its header")
    (kind, flags, lost, index, device_time, n, leadoff, gain_code,
     rate_code) = struct.unpack_from("<BBHIQBBBB", data, 0)
    if kind != PACKET_EEG and kind != PACKET_SYNTHETIC:
        raise Invalid("packet type 0x%02x is not samples" % kind)
    if gain_code >= len(GAIN_BY_CODE):
        raise Invalid("gain code %d is not one this protocol defines" % gain_code)
    if len(data) - DATA_HEADER_LEN != n * channels * 3:
        raise Truncated("%d samples of %d channels is %d bytes, and this packet carries %d"
                        % (n, channels, n * channels * 3, len(data) - DATA_HEADER_LEN))
    counts = []
    at = DATA_HEADER_LEN
    for _ in range(n):
        row = []
        for _ in range(channels):
            row.append(int24(data, at))
            at += 3
        counts.append(row)
    return Packet(bool(flags & 1), bool(flags & 2), MODE_BY_CODE.get((flags >> 2) & 3, "unknown"),
                  bool(flags & 0x10), lost, index, device_time, leadoff, GAIN_BY_CODE[gain_code],
                  RATE_BY_CODE.get(rate_code), counts, kind == PACKET_SYNTHETIC)


# --- predictions ---------------------------------------------------------------

PREDICTION_HEADER_LEN = const(28)
INPUT_SOURCE_NAMES = {0: "stream", 1: "natural", 2: "own_chain", 3: "synthetic"}


class Prediction:
    """One head's output for one window. The window's signal had a gap when
    gap_in_window is set, and an electrode off the skin when
    leadoff_in_window is."""

    def __init__(self, head_slot, head_id, index, device_time, window_samples, gap_in_window,
                 duty_reduced, leadoff_in_window, outputs, input_source="stream"):
        self.head_slot = head_slot
        self.head_id = head_id
        self.index = index
        self.device_time = device_time
        self.window_samples = window_samples
        self.gap_in_window = gap_in_window
        self.duty_reduced = duty_reduced
        self.leadoff_in_window = leadoff_in_window
        self.outputs = outputs
        self.input_source = input_source


def decode_prediction(data):
    if len(data) < PREDICTION_HEADER_LEN:
        raise Truncated("a prediction is at least its header")
    (kind, flags, slot, n, index, device_time, window) = struct.unpack_from("<BBBBIQH", data, 0)
    if kind != PACKET_PREDICTION:
        raise Invalid("packet type 0x%02x is not a prediction" % kind)
    if len(data) - PREDICTION_HEADER_LEN != n * 4:
        raise Truncated("%d outputs is %d bytes, and this packet carries %d"
                        % (n, n * 4, len(data) - PREDICTION_HEADER_LEN))
    outputs = list(struct.unpack_from("<%df" % n, data, PREDICTION_HEADER_LEN)) if n else []
    return Prediction(slot, _hex(data[18:26]), index, device_time, window, bool(flags & 1),
                      bool(flags & 2), bool(flags & 4), outputs,
                      INPUT_SOURCE_NAMES.get(data[26], "source %d" % data[26]))


# --- the battery, the heads and the model --------------------------------------

class Battery:
    """The battery's voltage, its charge, and what the charger is doing."""

    def __init__(self, millivolts, percent, charger):
        self.millivolts = millivolts
        self.percent = percent
        self.charger = charger


def decode_battery(payload):
    if len(payload) < 4:
        raise Truncated("a battery reading is four bytes")
    mv, pct, charger = struct.unpack_from("<HBB", payload, 0)
    return Battery(mv, None if pct == BATTERY_UNKNOWN else pct,
                   CHARGER_STATES.get(charger, "charger state %d" % charger))


HEAD_STATES = {0: "empty", 1: "valid", 2: "invalid", 3: "width mismatch"}
MODEL_STATES = {0: "no runtime", 1: "no weights", 2: "ready", 3: "updating"}
NO_HEAD = const(0xFF)
NO_ENCODER_ID = "0000000000000000"
HEAD_ENTRY_LEN = const(30)


class Head:
    """One head slot: its state, how many numbers it gives, its id, its
    name, and the encoder it was trained beside."""

    def __init__(self, slot, state, out_dim, head_id, name, encoder_id=NO_ENCODER_ID):
        self.slot = slot
        self.state = state
        self.out_dim = out_dim
        self.head_id = head_id
        self.name = name
        self.encoder_id = encoder_id

    @property
    def usable(self):
        return self.state == "valid"


def decode_heads(payload):
    """The head slots, and which one is selected, as (active, heads). None
    means no head is selected."""
    if len(payload) < 2:
        raise Truncated("a head list is at least its count")
    active, n = payload[0], payload[1]
    end = 2 + n * HEAD_ENTRY_LEN
    if len(payload) != end and len(payload) != end + n * 8:
        raise Invalid("a list of %d heads is %d bytes, or %d with its encoder ids, and this one is %d"
                      % (n, end, end + n * 8, len(payload)))
    heads = []
    for i in range(n):
        at = 2 + i * HEAD_ENTRY_LEN
        encoder = _hex(payload[end + i * 8:end + i * 8 + 8]) if len(payload) > end else NO_ENCODER_ID
        heads.append(Head(payload[at], HEAD_STATES.get(payload[at + 1], "state %d" % payload[at + 1]),
                          struct.unpack_from("<H", payload, at + 2)[0], _hex(payload[at + 4:at + 12]),
                          _text(payload[at + 12:at + 28]), encoder))
    return (None if active == NO_HEAD else active), heads


def decode_head_encoders(payload):
    """The encoder each head names, by slot."""
    if len(payload) < 1:
        raise Truncated("a list of head encoders is at least its count")
    n = payload[0]
    if len(payload) != 1 + n * 9:
        raise Invalid("a list of %d head encoders is %d bytes, and this one is %d"
                      % (n, 1 + n * 9, len(payload)))
    return {payload[1 + i * 9]: _hex(payload[2 + i * 9:10 + i * 9]) for i in range(n)}


class ModelInfo:
    """What the device's model can do and is doing."""

    def __init__(self, state, active_head, predictions_on, encoder_id, weights_version,
                 input_classes=1, tokens_per_channel=0, pass_ms=0, interval_s=0, generator=False):
        self.state = state
        self.active_head = active_head
        self.predictions_on = predictions_on
        self.encoder_id = encoder_id
        self.weights_version = weights_version
        self.input_classes = input_classes
        self.tokens_per_channel = tokens_per_channel
        self.pass_ms = pass_ms
        self.interval_s = interval_s
        self.generator = generator

    @property
    def ready(self):
        return self.state == "ready"


def decode_model_info(payload):
    if len(payload) < 16:
        raise Truncated("model information is at least sixteen bytes")
    long = len(payload) >= 22
    pass_ms, interval_s = struct.unpack_from("<HH", payload, 17) if long else (0, 0)
    return ModelInfo(MODEL_STATES.get(payload[0], "state %d" % payload[0]),
                     None if payload[1] == NO_HEAD else payload[1], payload[2] != 0,
                     _hex(payload[4:12]), tuple(payload[12:15]), payload[15] or 1,
                     payload[16] if len(payload) >= 17 else 0, pass_ms, interval_s,
                     long and payload[21] != 0)


# --- names -----------------------------------------------------------------------

def display_names(names):
    """Labels for a list to pick a device from, in the list's order: each
    device's own name, with a number after the later ones where two share
    it. A device heard before its name is the product's name."""
    seen = {}
    out = []
    for n in names:
        name = n or PRODUCT_NAME
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else "%s %d" % (name, seen[name]))
    return out
