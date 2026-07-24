"""SRS voice client -- registers with a SimpleRadio Standalone server and
TRANSMITS voice, independent of DCS-gRPC.

Implements the DCS-SimpleRadioStandalone wire protocol (transmit path), ported
from SkyEye's Go `simpleradio` client:

- Transport: TCP (control, newline-delimited JSON) + UDP (voice + ping) on the
  SAME host:port (default 5002). The UDP socket is `connect()`ed to the server.
- Register: TCP Sync (MsgType 2) with full ClientInfo, then a UDP ping (the bare
  22-byte GUID) so the server learns our UDP source and will relay our voice.
- Transmit: for each 40 ms Opus frame, one UDP voice packet, paced ~40 ms.

External AWACS Mode (MsgType 7) auth is sent only if an EAM password is given;
with the server's security features off it is not needed to be relayed.

    uv run --extra voice python -m marshall.srs.client 192.168.0.35 124.0 \
        "Kobuleti Departure, radio check, how do you read?"
"""

from __future__ import annotations

import json
import secrets
import socket
import struct
import threading
import time

from marshall.srs import tts

SRS_VERSION = "2.1.0.2"
DEFAULT_PORT = 5002
GUID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"  # base57
GUID_LEN = 22
UNIT_ID = 100_000_002
PING_INTERVAL = 15.0

# MessageType enum (types/message.go)
MSG_PING = 1
MSG_SYNC = 2
MSG_EAM_PASSWORD = 7

# Modulation (types/radio.go)
AM = 0
FM = 1

# Coalition (types/coalition.go): 1=Red, 2=Blue, other=Spectator
BLUE = 2


def new_guid() -> str:
    return "".join(secrets.choice(GUID_ALPHABET) for _ in range(GUID_LEN))


def radio(freq_hz: float, modulation: int = AM) -> dict:
    return {"freq": float(freq_hz), "modulation": modulation, "enc": False,
            "encKey": 0, "secFreq": 0.0, "retransmit": False}


class SRSClient:
    """A transmit-only SRS client. Not the brain -- just a mouth on the radio."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, name: str = "Marshall",
                 coalition: int = BLUE, eam_password: str | None = None):
        self.host, self.port = host, port
        self.name, self.coalition = name, coalition
        self.eam_password = eam_password
        self.guid = new_guid()
        self.radios: list[dict] = []
        self.packet_id = 1
        self.tcp: socket.socket | None = None
        self.udp: socket.socket | None = None
        self._stop = threading.Event()

    # --- registration ---------------------------------------------------
    def connect(self, radios: list[dict]) -> "SRSClient":
        self.radios = radios
        self.tcp = socket.create_connection((self.host, self.port), timeout=10)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.connect((self.host, self.port))

        self._send_tcp(MSG_SYNC)
        if self.eam_password is not None:
            self._send_tcp(MSG_EAM_PASSWORD, ExternalAWACSModePassword=self.eam_password)
        self._udp_ping()            # registers our UDP source with the server
        self._send_tcp(MSG_PING)

        threading.Thread(target=self._drain_tcp, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()
        return self

    def _client_info(self) -> dict:
        return {
            "ClientGuid": self.guid, "Name": self.name, "Seat": 0,
            "Coalition": self.coalition, "AllowRecord": True,
            "RadioInfo": {
                "radios": self.radios, "unit": "External AWACS", "unitId": UNIT_ID,
                "iff": {"control": 2, "status": 0, "mode1": -1, "mode2": -1,
                        "mode3": -1, "mode4": False, "mic": -1},
                "ambient": {"vol": 1.0, "abType": ""},
            },
            "LatLngPosition": {"lat": 0.0, "lng": 0.0, "alt": 0.0},
        }

    def _send_tcp(self, msg_type: int, **extra) -> None:
        msg = {"Version": SRS_VERSION, "Client": self._client_info(),
               "MsgType": msg_type, **extra}
        self.tcp.sendall(json.dumps(msg).encode("utf-8") + b"\n")

    def _udp_ping(self) -> None:
        self.udp.send(self.guid.encode("ascii"))   # bare 22-byte GUID

    def _ping_loop(self) -> None:
        while not self._stop.wait(PING_INTERVAL):
            try:
                self._udp_ping()
                self._send_tcp(MSG_PING)
            except OSError:
                break

    def _drain_tcp(self) -> None:
        # Read and discard server chatter (client lists, settings) so the socket
        # buffer never wedges. We are transmit-only; nothing to parse yet.
        try:
            while not self._stop.is_set():
                if not self.tcp.recv(4096):
                    break
        except OSError:
            pass

    # --- voice ----------------------------------------------------------
    def transmit(self, opus_frames: list[bytes], freq_hz: float, modulation: int = AM,
                 settle: float = 0.4) -> None:
        """Send one transmission: a run of Opus frames, paced at 40 ms."""
        freqs = [(float(freq_hz), modulation, 0)]
        time.sleep(settle)          # let the server register our UDP source
        start = time.monotonic()
        for i, frame in enumerate(opus_frames):
            self.udp.send(self._voice_packet(frame, freqs))
            self.packet_id += 1
            nxt = start + (i + 1) * (tts.FRAME_MS / 1000)
            dt = nxt - time.monotonic()
            if dt > 0:
                time.sleep(dt)

    def _voice_packet(self, audio: bytes, freqs) -> bytes:
        audio = audio[:65535]
        freq_seg = b"".join(struct.pack("<dBB", f, m, e) for (f, m, e) in freqs)
        packet_len = 6 + len(audio) + len(freq_seg) + 58
        header = struct.pack("<HHH", packet_len, len(audio), len(freq_seg))
        guid = self.guid.encode("ascii")
        fixed = (b"\x00"                              # leading pad byte of fixed seg
                 + struct.pack("<I", UNIT_ID)
                 + struct.pack("<Q", self.packet_id)
                 + struct.pack("<B", 0)               # hops
                 + guid                               # relay GUID
                 + guid)                              # origin GUID
        return header + audio + freq_seg + fixed

    def listen(self, duration: float) -> tuple[int, int]:
        """Count relayed voice packets (>22 bytes) seen on our UDP socket.

        A receiver tuned to a frequency gets every transmission relayed to it;
        counting them proves the server is relaying our audio without needing a
        human in the cockpit. (A 22-byte datagram is a ping, not voice.)
        """
        self.udp.settimeout(0.5)
        end = time.monotonic() + duration
        packets = total = 0
        while time.monotonic() < end:
            try:
                data = self.udp.recv(1500)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) > GUID_LEN:
                packets += 1
                total += len(data)
        return packets, total

    def close(self) -> None:
        self._stop.set()
        for s in (self.tcp, self.udp):
            try:
                s and s.close()
            except OSError:
                pass


if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.35"
    freq_mhz = float(sys.argv[2]) if len(sys.argv) > 2 else 124.0
    text = " ".join(sys.argv[3:]) or "Kobuleti Departure, radio check, how do you read?"

    freq_hz = freq_mhz * 1_000_000
    print(f"synthesizing: \"{text}\"")
    frames = tts.Voice().frames(text)
    print(f"  {len(frames)} Opus frames, {len(frames) * tts.FRAME_MS / 1000:.2f}s")

    c = SRSClient(host, name="Batumi ATC")
    c.connect([radio(freq_hz, AM)])
    print(f"connected as GUID {c.guid} -> {host}:{DEFAULT_PORT}, tx on {freq_mhz:.3f} AM")
    c.transmit(frames, freq_hz, AM)
    print("transmission sent; holding 3s for tail")
    time.sleep(3)
    c.close()
    print("done")
