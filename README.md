# MicroPython for IntoMind devices

MicroPython for the Raspberry Pi Pico 2 W, with the `intomind` library
built in. It does everything stock MicroPython does on the Pico 2 W, and it
connects to an IntoMind device and talks to it.

## Why a build of its own

IntoMind devices accept commands and send data only over an encrypted,
bonded link, paired with LE Secure Connections. MicroPython as released for the Pico 2 W cannot pair,
and pairing lives in MicroPython's C code, so a library alone cannot add
it. This is MicroPython 1.29.0 with two changes:

- Pairing and bonding on the Pico's Bluetooth library, BTstack, from
  MicroPython pull request 17469, which MicroPython has not merged yet.
  The pairing is kept in a file on the board.
- LE Secure Connections, with the elliptic curve arithmetic from micro-ecc.

Everything else is MicroPython as it ships for the Pico 2 W, Wi-Fi
included. Once MicroPython for the Pico 2 W can pair with LE Secure
Connections, the `intomind` library runs on it as it is.

## Putting it on a board

1. Download `firmware/intomind-micropython-pico-2-w.uf2`.
2. Hold the white BOOTSEL button while you plug the board into your
   computer, then let go. Drag the file onto the drive that appears.
3. The board restarts into MicroPython, and its banner reads
   `v1.29.0-intomind`. In Thonny, choose MicroPython (Raspberry Pi Pico) at
   the bottom right, and the prompt is the board's.

## A first program

```python
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
```

The first time, the board pairs with the device, and from then on it
remembers it. A device that does not stream on USB power refuses `start()`
while it is plugged in, and the refusal says so.

## The library

The names are the published `intomind` package's for Python, for what a
board can do. Nothing in it assumes a particular device: the channels, the
rates and what a device can do all come from what the device reports.

| | |
|---|---|
| `await intomind.scan(seconds=5)` | every IntoMind device heard advertising, the strongest first, each a `Found` with its `name`, `rssi` and `device` |
| `await intomind.connect(name="", seconds=5)` | connect to the first device whose name starts with `name`, or to a `Found`, pairing the first time, and return a `Device` |
| `device.info` | what the device says about itself: channels, converter resolution and reference, rates, head slots, and capabilities, which `device.can("heads")` reads |
| `await device.read_status()` | streaming, mode, gain, rate, charger, battery and contact |
| `await device.battery()` | the battery's voltage, charge and charger |
| `device.on_packet = f`, then `await device.start()` | the EEG: `f(device, packet)` for every packet, with `packet.counts` one row per sample and one count per channel, and `device.info.microvolts_per_count(packet.gain)` to scale a count |
| `await device.stop()` | stop the stream |
| `await device.heads()` | the head slots and which one is selected, as `(active, heads)` |
| `await device.model_info()` | what the device's model can do and is doing |
| `await device.select_head(slot)` | select the head that makes predictions |
| `device.on_prediction = f`, then `await device.set_predictions(True)` | `f(device, prediction)` for every window, with `prediction.outputs`, `prediction.head_slot`, and whether the window had a gap or an electrode off the skin |
| `await device.command(name, arg=None)` | any request in the protocol, by name, returning what the answer carries, or raising `Refused` with its `status` |
| `await device.disconnected()` | wait until the link drops |
| `await device.disconnect()` | end the link, keeping the pairing |
| `intomind.forget_pairings()` | forget every device the board has paired with |
| `intomind.protocol` | the protocol on its own, in plain Python |

## Pairing

The pairing lives in `ble_secrets.json` on the board. If a device has
forgotten the board, connecting fails and says to call
`intomind.forget_pairings()`, and the next connection pairs from the start.

## Building it

```
./build.sh
```

It needs git, make, CMake, Python 3 and the Arm compiler
`arm-none-eabi-gcc`. It clones MicroPython 1.29.0 into `build/micropython`,
or uses the one `MICROPYTHON` names, applies the two patches in `patches/`,
builds the board in `board/INTOMIND_PICO2_W` with the library frozen in,
and writes the file and its checksum to `firmware/`. It builds only from
MicroPython's own v1.29.0 commit and stamps that release's date, so the
file carries no commit and no date from the machine that built it. The
file here was built this way.

## Tests

```
python3 tests/run.py
```

They need no board. `tests/fixtures/messages.json` holds every message the
library reads, made by the published `@intomind/sdk`, and the library reads
each as the SDK does and refuses each malformed one as the SDK does.
`node tests/fixtures/make.mjs` makes the file again, with `@intomind/sdk`
installed from npm. The client runs against the simulated devices in
`tests/fake.py`: finding, pairing, streaming, running a head, refusals, and
one Bluetooth operation at a time.

## License

Free software under the GNU Affero General Public License, version 3, with
one added permission in `LICENSING.md`: it may be combined with MicroPython
and the libraries the firmware carries. We also license it commercially, on
fair terms shaped by your use case: write to contact@intomind.com. See
`LICENSING.md`, and `CONTRIBUTING.md` before a first pull request.

`patches/0001` is MicroPython's, from pull request 17469, under
MicroPython's MIT license. The firmware file contains these, under their
own licenses, in `licenses/`:

| | |
|---|---|
| `micropython.txt`, `micropython-lib.txt` | MicroPython, and the libraries it freezes in, aioble among them |
| `pico-sdk.txt`, `tinyusb.txt` | the Raspberry Pi Pico SDK, and TinyUSB for USB |
| `btstack.txt`, `btstack-raspberry-pi.txt` | BTstack, the Bluetooth library, used under Raspberry Pi's license for its chips |
| `cyw43-driver.txt`, `cyw43-driver-raspberry-pi.txt` | the driver and firmware for the wireless chip, used under Raspberry Pi's license for its chips |
| `micro-ecc.txt` | micro-ecc, the elliptic curve arithmetic for secure pairing |
| `lwip.txt`, `mbedtls.txt` | lwIP and Mbed TLS, for Wi-Fi |

IntoMind is a trademark of IntoMind, Inc. The license covers the code, not
the name.
