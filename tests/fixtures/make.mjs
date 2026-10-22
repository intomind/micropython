// Writes messages.json: every message the intomind library reads, made by
// the published @intomind/sdk's own encoders, with what the SDK's own
// decoders read from it, in the names of the published Python package.
//
//     node tests/fixtures/make.mjs [path to the SDK's index.js]
//
// The SDK's path defaults to the package name, for an SDK installed with npm.

import { writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

const where = process.argv[2] ? pathToFileURL(process.argv[2]).href : "@intomind/sdk";
const { protocol: P } = await import(where);

const hex = (b) => Buffer.from(b).toString("hex");
const big = (v) => v.toString();
const thrown = (f) => {
  try { f(); } catch (e) { return e.name; }
  return null;
};

// --- device info -------------------------------------------------------------
const fullInfo = new P.DeviceInfo({
  protocol: [1, 4], firmware: [1, 2, 3], channels: 4, adcBits: 24, tickHz: 1000000,
  vrefUv: 1234567, capabilities: P.CAPABILITIES.battery_voltage | P.CAPABILITIES.leadoff |
    P.CAPABILITIES.model | P.CAPABILITIES.heads | P.CAPABILITIES.embeddings,
  supportedRates: 0b111, deviceId: "0123456789abcdef", hardware: [4, 5, 6],
  buildId: "fedcba9876543210", modelEmbedDim: 11, modelNativeSps: 222,
  modelWindowSamples: 3333, headSlots: 4, headMaxOutputs: 5, headSlotBytes: 6666,
  updateChunkMax: 77, appSlotBytes: 888888, weightsImageBytes: 9999999,
  capabilitiesHigh: P.CAPABILITIES_HIGH.synthetic,
});
const oldInfo = new P.DeviceInfo({
  protocol: [0, 1], firmware: [7, 8, 9], channels: 4, adcBits: 24, tickHz: 1000,
  vrefUv: 7654321, capabilities: P.CAPABILITIES.leadoff, supportedRates: 0b010,
  deviceId: "a1a2a3a4a5a6a7a8",
});
const capabilityNames = [...Object.keys(P.CAPABILITIES), ...Object.keys(P.CAPABILITIES_HIGH), "not a capability"];
const infoCase = (name, bytes) => {
  const d = P.decodeDeviceInfo(bytes);
  return {
    name, hex: hex(bytes),
    expect: {
      protocol: d.protocol, firmware: d.firmware, channels: d.channels, adc_bits: d.adcBits,
      tick_hz: d.tickHz, vref_uv: d.vrefUv, capabilities: d.capabilities,
      supported_rates: d.supportedRates, device_id: d.deviceId, hardware: d.hardware,
      build_id: d.buildId, model_embed_dim: d.modelEmbedDim, model_native_sps: d.modelNativeSps,
      model_window_samples: d.modelWindowSamples, head_slots: d.headSlots,
      head_max_outputs: d.headMaxOutputs, head_slot_bytes: d.headSlotBytes,
      update_chunk_max: d.updateChunkMax, app_slot_bytes: d.appSlotBytes,
      weights_image_bytes: d.weightsImageBytes, capabilities_high: d.capabilitiesHigh,
    },
    can: Object.fromEntries(capabilityNames.map((c) => [c, d.can(c)])),
    rates: d.rates,
    microvolts_per_count: Object.fromEntries([1, 6, 24].map((g) => [g, d.microvoltsPerCount(g)])),
  };
};
const full = P.encodeDeviceInfo(fullInfo);
const shortLength = full.slice(); shortLength[27] = 60;
const cutShort = full.slice(0, 50);

// --- status ------------------------------------------------------------------
const statusCase = (name, s) => {
  const bytes = P.encodeStatus(s);
  const d = P.decodeStatus(bytes);
  return {
    name, hex: hex(bytes),
    expect: {
      streaming: d.streaming, mode: d.modeName, gain: d.gain, sample_rate_hz: d.sps,
      charger: d.chargerName, battery_percent: d.batteryPercent, leadoff: d.loffStatp,
      usb_present: d.usbPresent, buffer_high_watermark: d.bufferHighWatermark,
      dropped_total: d.droppedTotal, buffer_fill: d.bufferFill,
    },
  };
};

// --- samples ---------------------------------------------------------------------
const packetCase = (name, p, channels) => {
  const bytes = P.encodePacket(p);
  const d = P.decodePacket(bytes, channels);
  return {
    name, channels, hex: hex(bytes),
    expect: {
      discontinuity: d.discontinuity, leadoff_active: d.leadoffActive, mode: d.modeName,
      usb_present: d.usbPresent, samples_lost_before: d.samplesLostBefore, index: d.index,
      device_time: big(d.deviceTime), leadoff: d.loffStatp, gain: d.gain, sample_rate_hz: d.sps,
      counts: d.counts, synthetic: d.synthetic,
    },
  };
};
const eeg = {
  discontinuity: true, leadoffActive: true, mode: 1, usbPresent: true, samplesLostBefore: 17,
  index: 0xfffffffe, deviceTime: (1n << 40n) + 5n, loffStatp: 0b1010, gainCode: 6, rateCode: 5,
  counts: [[0, 1, -1, 8388607], [-8388608, 123456, -654321, 42], [7, -7, 70000, -70000]],
};
const eegBytes = P.encodePacket(eeg);
const eegWrongGain = eegBytes.slice(); eegWrongGain[18] = 7;
const eegNotSamples = eegBytes.slice(); eegNotSamples[0] = P.PACKET_PREDICTION;

// --- predictions -----------------------------------------------------------------
const predictionCase = (name, p) => {
  const bytes = P.encodePrediction(p);
  const d = P.decodePrediction(bytes);
  return {
    name, hex: hex(bytes),
    expect: {
      head_slot: d.headSlot, head_id: d.headId, index: d.index, device_time: big(d.deviceTime),
      window_samples: d.windowSamples, gap_in_window: d.gapInWindow, duty_reduced: d.dutyReduced,
      leadoff_in_window: d.leadoffInWindow, outputs: d.outputs,
      input_source: P.INPUT_SOURCE_NAMES[d.inputSource] ?? `source ${d.inputSource}`,
    },
  };
};
const prediction = (over) => ({
  headSlot: 2, headId: "0123456789abcdef", index: 1234, deviceTime: 5678901234n, windowSamples: 1500,
  gapInWindow: false, dutyReduced: false, leadoffInWindow: false, outputs: [0.75], inputSource: 0, ...over,
});
const onePrediction = P.encodePrediction(prediction({}));
const notPrediction = onePrediction.slice(); notPrediction[0] = P.PACKET_EEG;

// --- the battery, the heads and the model ------------------------------------------
const batteryCase = (name, b) => {
  const bytes = P.encodeBattery(b);
  const d = P.decodeBattery(bytes);
  return { name, hex: hex(bytes), expect: { millivolts: d.millivolts, percent: d.percent, charger: d.chargerName } };
};
const heads = [
  { slot: 0, state: 1, outDim: 1, headId: "1111111111111111", name: "built in" },
  { slot: 1, state: 1, outDim: 2, headId: "2222222222222222", name: "head two" },
  { slot: 2, state: 1, outDim: 1, headId: "3333333333333333", name: "sixteen bytes ok" },
  { slot: 3, state: 0, outDim: 0, headId: "0000000000000000", name: "" },
  { slot: 4, state: 2, outDim: 1, headId: "4444444444444444", name: "bad" },
];
const headsCase = (name, bytes) => {
  const d = P.decodeHeads(bytes);
  return {
    name, hex: hex(bytes),
    expect: {
      active: d.activeSlot,
      heads: d.heads.map((h) => ({ slot: h.slot, state: h.stateName, out_dim: h.outDim, head_id: h.headId,
        name: h.name, encoder_id: h.encoderId, usable: h.usable })),
    },
  };
};
const headList = P.encodeHeads(2, heads);
const withIds = new Uint8Array([...P.encodeHeads(null, heads.slice(0, 2)), ...Buffer.from("aaaaaaaaaaaaaaaabbbbbbbbbbbbbbbb", "hex")]);
const encoders = P.encodeHeadEncoders([{ slot: 1, encoderId: "0102030405060708" }, { slot: 2, encoderId: "0000000000000000" }]);
const modelCase = (name, m) => {
  const bytes = P.encodeModelInfo(m);
  const d = P.decodeModelInfo(bytes);
  return {
    name, hex: hex(bytes),
    expect: {
      state: d.modelStateName, active_head: d.activeHead, predictions_on: d.predictionsOn,
      encoder_id: d.encoderId, weights_version: d.weightsVersion, input_classes: d.inputClasses,
      tokens_per_channel: d.tokensPerChannel, pass_ms: d.passMs, interval_s: d.intervalS,
      generator: d.generator, ready: d.ready,
    },
  };
};
const responseCase = (name, opcode, status, payload) => {
  const bytes = P.encodeResponse(opcode, status, new Uint8Array(payload));
  const d = P.decodeResponse(bytes);
  return { name, hex: hex(bytes), expect: { opcode: d.opcode, status: d.status, payload: hex(d.payload), ok: d.ok, status_name: d.statusName } };
};

const out = {
  made: "by tests/fixtures/make.mjs with the published @intomind/sdk, protocol " + P.VERSION.join("."),
  uuids: Object.fromEntries(Object.entries(P.FILL).map(([k, v]) => [v, P.uuid(v)])),
  requests: Object.keys(P.OPCODES).map((name) => {
    const arg = P.TAKES_PAYLOAD.has(name) ? [1, 2] : P.TAKES_ARG.has(name) ? 1 : null;
    return { name, arg, hex: hex(P.encodeRequest(name, Array.isArray(arg) ? new Uint8Array(arg) : arg)) };
  }),
  bad_requests: [
    { name: "select_head", arg: null, error: thrown(() => P.encodeRequest("select_head")) },
    { name: "start_stream", arg: 1, error: thrown(() => P.encodeRequest("start_stream", 1)) },
    { name: "not an opcode", arg: null, error: thrown(() => P.encodeRequest("not an opcode")) },
  ],
  responses: [
    responseCase("ok with a payload", 0x82, 0, [1, 2, 3]),
    responseCase("refused on USB power", 0x01, 7, []),
    responseCase("a status no version defines", 0x80, 9, []),
  ],
  device_info: [infoCase("the current layout", full), infoCase("the first layout", P.encodeDeviceInfo(oldInfo))],
  status: [
    statusCase("streaming", { state: 1, mode: 0, gainCode: 6, rateCode: 5, chargerState: 0, batteryPercent: 87,
      loffStatp: 0b0101, usbPresent: false, bufferHighWatermark: true, droppedTotal: 3, bufferFill: 77 }),
    statusCase("charging, codes no version defines", { state: 0, mode: 2, gainCode: 9, rateCode: 1, chargerState: 9,
      batteryPercent: null, loffStatp: 0, usbPresent: true, bufferHighWatermark: false, droppedTotal: 65535, bufferFill: 0 }),
  ],
  packets: [
    packetCase("four channels, every flag, the index about to wrap", eeg, 4),
    packetCase("three channels, generated by the device", { synthetic: true, mode: 3, index: 7, deviceTime: 9n,
      gainCode: 0, rateCode: 6, counts: [[1, 2, 3], [4, 5, 6]] }, 3),
    packetCase("no samples", { index: 0, deviceTime: 0n, gainCode: 3, rateCode: 4, counts: [] }, 4),
  ],
  predictions: [
    predictionCase("one output", prediction({})),
    predictionCase("a gap in the window", prediction({ gapInWindow: true, outputs: [0.25] })),
    predictionCase("an electrode off, duty reduced", prediction({ leadoffInWindow: true, dutyReduced: true, outputs: [0.5] })),
    predictionCase("two outputs, another slot", prediction({ headSlot: 1, outputs: [0.125, -3.5] })),
    predictionCase("no outputs", prediction({ outputs: [] })),
    predictionCase("from the natural signal", prediction({ inputSource: 1, index: 0xffffffff })),
  ],
  battery: [
    batteryCase("charging", { millivolts: 3912, percent: 64, chargerState: 1 }),
    batteryCase("no reading", { millivolts: 0, percent: null, chargerState: 7 }),
  ],
  heads: [headsCase("five slots, slot 2 selected", headList), headsCase("encoder ids after the records", withIds)],
  head_encoders: [{ name: "two slots", hex: hex(encoders), expect: Object.fromEntries(P.decodeHeadEncoders(encoders)) }],
  model_info: [
    modelCase("the 1.0 length", { modelState: 2, activeHead: 2, predictionsOn: true, encoderId: "0102030405060708", weightsVersion: [3, 2, 1], inputClasses: 0 }),
    modelCase("tokens", { modelState: 1, activeHead: null, predictionsOn: false, encoderId: "0000000000000000", weightsVersion: [0, 0, 0], inputClasses: 2, tokensPerChannel: 4 }),
    modelCase("the 1.3 length", { modelState: 3, activeHead: 0, predictionsOn: false, encoderId: "0102030405060708", weightsVersion: [6, 5, 4], inputClasses: 3, tokensPerChannel: 1, passMs: 123, intervalS: 2, generator: true }),
  ],
  display_names: [
    { names: ["Ada's IntoMind One", "", "Ada's IntoMind One", "", "Bo's Blue IntoMind One"], expect: P.displayNames(["Ada's IntoMind One", "", "Ada's IntoMind One", "", "Bo's Blue IntoMind One"]) },
  ],
  microvolts: [[1, 1234567, 24, 24], [-8388608, 1234567, 1, 24], [8388607, 7654321, 6, 24]].map(([raw, vref, gain, bits]) => ({ raw, vref, gain, bits, expect: P.microvolts(raw, vref, gain, bits) })),
  int24: [[0x7f, 0xff, 0xff], [0x80, 0, 0], [0xff, 0xff, 0xff], [0, 0, 1]].map((b) => ({ hex: hex(b), expect: P.int24(new Uint8Array(b), 0) })),
  malformed: [
    { decoder: "decode_device_info", hex: hex(full.slice(0, 26)), error: thrown(() => P.decodeDeviceInfo(full.slice(0, 26))) },
    { decoder: "decode_device_info", hex: hex(shortLength), error: thrown(() => P.decodeDeviceInfo(shortLength)) },
    { decoder: "decode_device_info", hex: hex(cutShort), error: thrown(() => P.decodeDeviceInfo(cutShort)) },
    { decoder: "decode_status", hex: "00".repeat(11), error: thrown(() => P.decodeStatus(new Uint8Array(11))) },
    { decoder: "decode_packet", channels: 4, hex: hex(eegBytes.slice(0, eegBytes.length - 1)), error: thrown(() => P.decodePacket(eegBytes.slice(0, eegBytes.length - 1), 4)) },
    { decoder: "decode_packet", channels: 4, hex: hex(eegWrongGain), error: thrown(() => P.decodePacket(eegWrongGain, 4)) },
    { decoder: "decode_packet", channels: 4, hex: hex(eegNotSamples), error: thrown(() => P.decodePacket(eegNotSamples, 4)) },
    { decoder: "decode_packet", channels: 3, hex: hex(eegBytes), error: thrown(() => P.decodePacket(eegBytes, 3)) },
    { decoder: "decode_prediction", hex: hex(onePrediction.slice(0, 27)), error: thrown(() => P.decodePrediction(onePrediction.slice(0, 27))) },
    { decoder: "decode_prediction", hex: hex(onePrediction.slice(0, 31)), error: thrown(() => P.decodePrediction(onePrediction.slice(0, 31))) },
    { decoder: "decode_prediction", hex: hex(notPrediction), error: thrown(() => P.decodePrediction(notPrediction)) },
    { decoder: "decode_battery", hex: "010203", error: thrown(() => P.decodeBattery(new Uint8Array([1, 2, 3]))) },
    { decoder: "decode_heads", hex: "02", error: thrown(() => P.decodeHeads(new Uint8Array([2]))) },
    { decoder: "decode_heads", hex: hex(headList.slice(0, headList.length - 1)), error: thrown(() => P.decodeHeads(headList.slice(0, headList.length - 1))) },
    { decoder: "decode_head_encoders", hex: hex(encoders.slice(0, 5)), error: thrown(() => P.decodeHeadEncoders(encoders.slice(0, 5))) },
    { decoder: "decode_model_info", hex: "00".repeat(15), error: thrown(() => P.decodeModelInfo(new Uint8Array(15))) },
    { decoder: "decode_response", hex: "01", error: thrown(() => P.decodeResponse(new Uint8Array([1]))) },
  ],
};
const here = fileURLToPath(new URL("messages.json", import.meta.url));
writeFileSync(here, JSON.stringify(out, null, 1) + "\n");
console.log("wrote", here);
