# Hardware and network

Everything here runs on consumer hardware with **no discrete GPU**. Numbers are
measured, not estimated.

## Speaker

**Home Assistant Voice Preview Edition** (Nabu Casa).
ESP32-S3, XMOS audio front-end, dual microphones, 2.4 GHz Wi-Fi only,
USB-C for power only, 3.5 mm line out, Grove port, hardware mute switch,
rotary dial, centre button, LED ring. Runs the stock ESPHome firmware;
Wi-Fi was provisioned over Improv BLE from the laptop (`tools/improv_provision.py`).

## Server

**Beelink GTR7 mini PC** — AMD Ryzen 7 7840HS (8C/16T, AVX-512), Radeon 780M
iGPU (unused), 27 GB RAM visible to the OS, 2× NVMe, 2× USB4, wired 100 Mbit
(the router's ports negotiate 100 Mbit). Debian 13, Docker 26 from the Debian
repo, nftables default-drop firewall.

Runs: Home Assistant (host network), wyoming-whisper, wyoming-piper,
wyoming-langproxy, Applio (RVC) in a CPU container.

Measured on this CPU:

| Task | Time |
|---|---|
| Whisper `large-v3-turbo` int8, 2 s utterance | ~2.6 s |
| Whisper `medium` int8, same | ~1.9 s |
| Whisper `small` int8, same | ~0.6 s (Russian accuracy poor) |
| Language ID with `tiny` in the proxy | ~0.15 s |
| Piper synthesis | well under a second |
| RVC (Applio) conversion of 8.5 s audio, one-shot `core.py infer` | ~9.5 s + ~9 s process start-up |
| RVC training, 11 min dataset, batch 8, 48 kHz | ~3.5 min per epoch |

End-to-end from end of speech to first sound of the reply, no LLM: about 3 s.

## Laptop (development)

**Lenovo ThinkPad P14s Gen 7 AMD** — Ryzen AI 7 PRO 450, 64 GB DDR5 SODIMM,
MediaTek MT7925 Wi-Fi (see `docs/wifi-cs1-drop.md`), 2× USB4. Arch Linux,
Hyprland. Used for tooling, listening to probes, and driving the server over SSH.

## Network

TP-Link router, 2.4 GHz and 5 GHz. The speaker lives on 2.4 GHz (it has no
5 GHz radio). The server is wired. Whisper/Piper/proxy ports are bound to
`127.0.0.1` on the server; only Home Assistant's 8123 is opened to the LAN in
nftables.

## What a GPU would change

Whisper would drop to ~0.3 s, RVC conversion to real time, and training from a
night to under an hour. The mini PC has no PCIe slot; an eGPU over USB4 works
for this kind of workload (compute-bound, model loaded once).
