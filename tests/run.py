"""The tests, with any Python 3 and no board:

    python3 tests/run.py

- every message the package reads, made by the published @intomind/sdk in
  fixtures/messages.json, reads as the SDK reads it, and every malformed
  one fails as it fails there;
- every request has the SDK's bytes;
- the client finds, connects, pairs, streams, runs a head and reports what
  it refuses, against the devices in fake.py, one operation at a time.
"""

import asyncio
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
M = json.loads((HERE / "fixtures" / "messages.json").read_text())

sys.path.insert(0, str(ROOT / "intomind"))
import protocol as P  # noqa: E402

failures = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def plain(v):
    """A decoded value in JSON's terms, to compare with what the SDK read."""
    if isinstance(v, tuple):
        return [plain(x) for x in v]
    if isinstance(v, list):
        return [plain(x) for x in v]
    return v


def same(obj, expect, big=()):
    for k, want in expect.items():
        got = getattr(obj, k)
        if k in big:
            got = str(got)
        if plain(got) != want:
            return "%s is %r, the SDK reads %r" % (k, got, want)
    return None


def raises(f, name):
    try:
        f()
    except P.ProtocolError as e:
        return type(e).__name__ == name
    return False


# --- the protocol, against the published SDK ---------------------------------------------

for fill, want in M["uuids"].items():
    check(P.uuid(int(fill)) == want, "the identifier for 0x%04x is %s" % (int(fill), want))
for r in M["requests"]:
    arg = bytes(r["arg"]) if isinstance(r["arg"], list) else r["arg"]
    check(P.encode_request(r["name"], arg).hex() == r["hex"], "%s is %s" % (r["name"], r["hex"]))
for r in M["bad_requests"]:
    check(raises(lambda: P.encode_request(r["name"], r["arg"]), r["error"]), "%s with %r is refused" % (r["name"], r["arg"]))
for c in M["responses"]:
    a = P.decode_response(bytes.fromhex(c["hex"]))
    got = {"opcode": a.opcode, "status": a.status, "payload": a.payload.hex(), "ok": a.ok, "status_name": a.status_name}
    check(got == c["expect"], "a response, %s, reads as the SDK reads it" % c["name"])
for c in M["device_info"]:
    d = P.decode_device_info(bytes.fromhex(c["hex"]))
    why = same(d, c["expect"])
    check(why is None, "device info, %s, reads as the SDK reads it%s" % (c["name"], "" if why is None else ": " + why))
    check(all(d.can(k) == v for k, v in c["can"].items()), "device info, %s, claims what the SDK says it claims" % c["name"])
    check(d.rates == c["rates"], "device info, %s, has the SDK's rates" % c["name"])
    check(all(d.microvolts_per_count(int(g)) == v for g, v in c["microvolts_per_count"].items()),
          "device info, %s, scales a count as the SDK does" % c["name"])
for c in M["status"]:
    why = same(P.decode_status(bytes.fromhex(c["hex"])), c["expect"])
    check(why is None, "status, %s, reads as the SDK reads it%s" % (c["name"], "" if why is None else ": " + why))
for c in M["packets"]:
    why = same(P.decode_packet(bytes.fromhex(c["hex"]), c["channels"]), c["expect"], big=("device_time",))
    check(why is None, "samples, %s, read as the SDK reads them%s" % (c["name"], "" if why is None else ": " + why))
for c in M["predictions"]:
    why = same(P.decode_prediction(bytes.fromhex(c["hex"])), c["expect"], big=("device_time",))
    check(why is None, "a prediction, %s, reads as the SDK reads it%s" % (c["name"], "" if why is None else ": " + why))
for c in M["battery"]:
    why = same(P.decode_battery(bytes.fromhex(c["hex"])), c["expect"])
    check(why is None, "the battery, %s, reads as the SDK reads it%s" % (c["name"], "" if why is None else ": " + why))
for c in M["heads"]:
    active, heads = P.decode_heads(bytes.fromhex(c["hex"]))
    whys = [same(h, e) for h, e in zip(heads, c["expect"]["heads"])]
    ok = active == c["expect"]["active"] and len(heads) == len(c["expect"]["heads"]) and whys == [None] * len(whys)
    check(ok, "a head list, %s, reads as the SDK reads it" % c["name"])
for c in M["head_encoders"]:
    got = P.decode_head_encoders(bytes.fromhex(c["hex"]))
    check({str(k): v for k, v in got.items()} == c["expect"], "the heads' encoders, %s, read as the SDK reads them" % c["name"])
for c in M["model_info"]:
    why = same(P.decode_model_info(bytes.fromhex(c["hex"])), c["expect"])
    check(why is None, "model info, %s, reads as the SDK reads it%s" % (c["name"], "" if why is None else ": " + why))
for c in M["display_names"]:
    check(P.display_names(c["names"]) == c["expect"], "names in a list are the SDK's: %s" % ", ".join(c["expect"]))
for c in M["microvolts"]:
    check(P.microvolts(c["raw"], c["vref"], c["gain"], c["bits"]) == c["expect"], "%d counts at gain %d are the SDK's microvolts" % (c["raw"], c["gain"]))
for c in M["int24"]:
    check(P.int24(bytes.fromhex(c["hex"])) == c["expect"], "%s is %d" % (c["hex"], c["expect"]))
for c in M["malformed"]:
    data = bytes.fromhex(c["hex"])
    decode = getattr(P, c["decoder"])
    f = (lambda: decode(data, c["channels"])) if "channels" in c else (lambda: decode(data))
    check(raises(f, c["error"]), "%s refuses %d bytes as %s, as the SDK does" % (c["decoder"], len(data), c["error"]))


# --- the client, against simulated devices ---------------------------------------------------

sys.path.insert(0, str(ROOT))
import fake  # noqa: E402

world = [
    fake.Device(M, "a speaker", -40, 1, services=False),
    fake.Device(M, "Ada's IntoMind One", -70, 2),
    fake.Device(M, "", -50, 3),
    fake.Device(M, "Ada's IntoMind One", -60, 4),
]
record = fake.install(world)
import intomind  # noqa: E402


async def client():
    found = await intomind.scan()
    check([(f.name, f.rssi) for f in found] == [("IntoMind One", -50), ("Ada's IntoMind One", -60), ("Ada's IntoMind One 2", -70)],
          "scan lists IntoMind devices only, the strongest first, numbered where two share a name")
    try:
        await intomind.connect("Bo")
        check(False, "connect finds no device whose name starts with Bo")
    except OSError as e:
        check("Bo" in str(e), "connect finds no device whose name starts with Bo")

    device = await intomind.connect("Ada")
    ada = world[1]
    check(device.connected and device.name == "Ada's IntoMind One", "connect takes the first device whose name starts with Ada")
    check(ada.link.paired_with == {"bond": True, "le_secure": True, "mitm": False, "timeout_ms": 20000},
          "connect pairs with LE Secure Connections and keeps the pairing")
    check(record.secrets == ["ble_secrets.json"], "the kept pairings load once, from ble_secrets.json")
    check(device.info.channels == 4 and device.mtu == 247, "the device's info is read, and the link carries 247 byte packets")

    active, heads = await device.heads()
    check(active == 2 and [h.encoder_id for h in heads[:3]] == ["0000000000000000", "0102030405060708", "0000000000000000"],
          "heads lists the slots with the encoder each names")
    check((await device.battery()).percent == 64, "battery reads the battery")
    check((await device.model_info()).ready, "model_info reads the model")
    check((await device.read_status()).streaming, "read_status reads the status")

    packets = []
    device.on_packet = lambda d, p: packets.append(p.index)
    ada.requests.clear()
    ada.stray = True
    await device.start()
    ada.stray = False
    check(ada.requests == ["4112", "50", "01"], "start asks for 18 samples a packet, as many as fit, restarts the index and starts")
    predictions = []

    def on_prediction(d, p):
        predictions.append((p.head_slot, p.outputs))
        if len(predictions) == 1:
            raise ValueError("a program's own mistake")

    device.on_prediction = on_prediction
    await device.select_head(2)
    await device.set_predictions(True)
    await asyncio.sleep(0.1)
    check(packets == [0xFFFFFFFE, 0], "on_packet hears every packet of samples")
    check(len(predictions) == len(M["predictions"]) and predictions[0] == (2, [0.75]),
          "on_prediction hears every prediction, after one of its own calls fails")
    check(len(record.printed) == 1, "a program's own mistake is printed and the rest still arrive")
    try:
        await asyncio.gather(device.read_status(), device.battery(), device.heads(), device.command("select_head", 2))
        answered = True
    except Exception:
        answered = False
    check(answered and ada.link.overlaps == 0, "requests from several tasks at once go one at a time, each answered")
    await device.stop()
    await device.disconnect()
    await asyncio.sleep(0.02)
    check(not device.connected, "disconnect ends the link")
    left = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    check(left == [], "nothing keeps running after disconnect")

    plugged = fake.Device(M, "Plugged", -50, 5, usb=True)
    device = await intomind.connect(intomind.Found("Plugged", -50, plugged))
    try:
        await device.start()
        check(False, "start on USB power is refused")
    except intomind.Refused as e:
        check(e.status == 7 and "Unplug" in str(e), "start on USB power is refused, and says to unplug")
    await device.disconnect()

    old = fake.Device(M, "Old", -50, 6, info=1, mtu=None)
    device = await intomind.connect(intomind.Found("Old", -50, old))
    check(device.mtu == 23, "a link that cannot grow keeps its 23 bytes")
    try:
        await device.battery()
        check(False, "a device that does not claim a battery is not asked for one")
    except OSError as e:
        check("cannot report its battery" in str(e), "a device that does not claim a battery is not asked for one")
    await device.start(new_epoch=False)
    check(old.requests == ["4101", "01"], "on a 23 byte link, start asks for the one sample that fits")
    await device.disconnect()

    locked = fake.Device(M, "Locked", -50, 7, encrypts=False)
    try:
        await intomind.connect(intomind.Found("Locked", -50, locked))
        check(False, "a link that stays unencrypted fails")
    except OSError as e:
        check("forget_pairings" in str(e) and not locked.link.connected, "a link that stays unencrypted fails, says what to do, and is dropped")

    here = os.getcwd()
    os.chdir(tempfile.mkdtemp())
    pathlib.Path("ble_secrets.json").write_text("[]")
    intomind.forget_pairings()
    check(not pathlib.Path("ble_secrets.json").exists() and record.ble_active[-1] is False,
          "forget_pairings deletes the kept pairings and restarts Bluetooth")
    os.chdir(here)


asyncio.run(client())

print("-" * 52)
print("every check passed" if not failures else "%d failed" % len(failures))
sys.exit(1 if failures else 0)
