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

    uv run --extra voice python -m marshall.radio.client $SRS_HOST 124.0 \
        "Kobuleti Departure, radio check, how do you read?"
"""

from __future__ import annotations

import json
import secrets
import socket
import struct
import threading
import time

from marshall.radio import tts
from marshall import config

SRS_VERSION = "2.1.0.2"
DEFAULT_PORT = 5002
GUID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"  # base57
GUID_LEN = 22
UNIT_ID = 100_000_002
PING_INTERVAL = 15.0

# MessageType enum (types/message.go)
MSG_PING = 1
MSG_SYNC = 2
MSG_RADIO_UPDATE = 3
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
        # A unique unit id per client -- reusing one id makes the server collide
        # stale clients and drop radio registrations.
        self.unit_id = UNIT_ID + secrets.randbelow(1_000_000)
        self.last_rx = 0.0        # when voice last arrived, on ANY frequency
        # When voice last arrived on EACH frequency, keyed by whole Hz. A
        # controller must stand off for a pilot on HIS channel and nobody
        # else's -- see `someone_is_talking`.
        self.last_rx_hz: dict[int, float] = {}
        # OUR OWN VOICES, to be ignored when they come back.
        #
        # With one client this could not happen: SRS does not echo a client to
        # itself. With a POOL it does -- the listener and the transmitters are
        # different clients, so every word Marshall-3 says arrives at the ear
        # and looks exactly like a pilot. The controller would then stand off
        # for his own voice for a second and a half after every transmission:
        # the metronome skips beats, back-to-back calls jitter, and nothing in
        # any log says why.
        #
        # Proved by accident while measuring the settle -- a separate listener
        # heard all 87 frames of the transmitter beside it.
        self.ignore_guids: set[str] = set()
        self.radios: list[dict] = []
        self.packet_id = 1
        self.tcp: socket.socket | None = None
        self.udp: socket.socket | None = None
        self.server = (host, port)
        self._stop = threading.Event()
        # SRS identity of whoever transmitted -- the free, per-packet anchor that
        # ties a voice to a person before they say a callsign. roster maps client
        # GUID -> friendly name ("Sockeye"), learned from the server's client list.
        self.roster: dict[str, str] = {}
        # Why roster tracking stopped, if it has. "" while healthy.
        self.roster_ended = ""
        self.last_sender_guid: str | None = None

    # --- registration ---------------------------------------------------
    def connect(self, radios: list[dict]) -> SRSClient:
        self.radios = radios
        self.tcp = socket.create_connection((self.host, self.port), timeout=10)
        # ...and then CLEAR it. create_connection's timeout is meant to bound
        # the connect, but it stays on the socket afterwards, and `_drain_tcp`
        # blocks on recv waiting for a server that is quiet whenever nobody is
        # joining. Ten seconds of quiet raised, the drain loop caught it as an
        # OSError and exited, and the GUID -> name roster froze for the rest of
        # the session -- so every client that joined later was a six-character
        # GUID stub forever.
        #
        # That is not cosmetic. The strongest identity evidence in the system is
        # the radio's NAME matched against the name radar prints (identity.py);
        # with a stub it can never match, and every pilot silently falls through
        # to the weaker rungs. Measured: a fresh client learns a late joiner in
        # two seconds, and one that had been quiet for twenty never learns it at
        # all.
        self.tcp.settimeout(None)
        # Unconnected UDP: the server relays voice from its own socket, which may
        # not be the same source port we send to -- a connect()ed socket would
        # drop those. Bind an ephemeral port and accept from any source.
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("0.0.0.0", 0))

        self._send_tcp(MSG_SYNC)
        if self.eam_password is not None:
            self._send_tcp(MSG_EAM_PASSWORD, ExternalAWACSModePassword=self.eam_password)
        # The server registers our radios from a RadioUpdate, NOT from the Sync.
        # Without this our client shows radios=[] server-side and no voice is ever
        # relayed to us -- we appear tuned to nothing.
        self._send_tcp(MSG_RADIO_UPDATE)
        self._udp_ping()            # registers our UDP source with the server
        self._send_tcp(MSG_PING)

        threading.Thread(target=self._drain_tcp, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()
        threading.Thread(target=self._warmup, daemon=True).start()
        return self

    def _warmup(self) -> None:
        # Re-assert the radio + UDP registration a few times over the first
        # seconds. A single RadioUpdate can land before the server has finished
        # setting the client up, and then the first transmission is dropped.
        for _ in range(4):
            if self._stop.wait(0.8):
                return
            try:
                self._send_tcp(MSG_RADIO_UPDATE)
                self._udp_ping()
            except OSError:
                return

    def _client_info(self) -> dict:
        return {
            "ClientGuid": self.guid, "Name": self.name, "Seat": 0,
            "Coalition": self.coalition, "AllowRecord": True,
            "RadioInfo": {
                "radios": self.radios, "unit": "External AWACS", "unitId": self.unit_id,
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
        self.udp.sendto(self.guid.encode("ascii"), self.server)   # bare 22-byte GUID

    def _ping_loop(self) -> None:
        while not self._stop.wait(PING_INTERVAL):
            try:
                self._udp_ping()
                self._send_tcp(MSG_PING)
            except OSError:
                break

    def _drain_tcp(self) -> None:
        # The server streams newline-delimited JSON (client lists, settings). We
        # keep the socket drained so it never wedges, and harvest GUID -> Name so
        # a voice packet's origin GUID can be resolved to "Sockeye".
        buf = b""
        # "" IS "WE ASKED IT TO STOP", not "no reason recorded".
        #
        # This initialised to "stopped", and the loop's own exit condition is
        # `self._stop.is_set()` -- so every ORDERLY close fell out of the loop
        # with that value still in hand and printed the identity-degradation
        # warning below. Each synthetic pilot in a rehearsal opens a client,
        # speaks, and closes it, so the transcript carried the alarm on nearly
        # every line and it cost a real diagnosis: a failing `stack_rehearsal`
        # read as "identity fell back to weaker evidence" when nothing of the
        # sort had happened.
        #
        # One value meaning both "I have no reason" and "the reason is that we
        # stopped it" is the same fault as `clearance_agreed` (#181), `due`
        # (#189) and `may_vector` (#197). A warning that cries on a clean
        # shutdown is a warning nobody reads on a real one.
        why = ""
        try:
            while not self._stop.is_set():
                try:
                    chunk = self.tcp.recv(4096)
                except TimeoutError:
                    # Belt and braces beside `settimeout(None)`. A timeout means
                    # the server had nothing to say, which is the NORMAL state
                    # of a quiet frequency -- it is not a reason to stop
                    # listening, and treating it as one is what killed this
                    # thread silently for a fortnight.
                    continue
                if not chunk:
                    why = "server closed the connection"
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    # One unparseable message must never end roster tracking for
                    # the rest of the session. It did: a live sortie logged two
                    # wingmen as raw GUID stubs because this thread had already
                    # died on some earlier line, and the failure is silent -- the
                    # socket keeps draining, calls keep working, and the SRS
                    # identity anchor is just quietly gone.
                    try:
                        self._harvest_roster(line)
                    except Exception:
                        continue
        except OSError as e:
            why = f"{type(e).__name__}: {e}"
        # NEVER SILENTLY. This thread is the only thing that knows what the
        # radios are called, and when it stops the system does not fail -- it
        # keeps working with worse evidence, which is the failure mode nobody
        # catches. If it ends, say so where somebody will see it.
        self.roster_ended = why
        if why:
            print(f"  !! SRS roster tracking stopped ({why}); radios will read "
                  f"as GUID stubs and identity falls back to weaker evidence",
                  flush=True)

    def _harvest_roster(self, line: bytes) -> None:
        """Pull {GUID: Name} out of any client records in one TCP message.

        The server sends the full roster (MsgType 2) to everyone whenever anyone
        joins, plus per-client updates (3 / 0) -- so a client that connects late,
        like a wingman keying up mid-approach, still resolves.
        """
        try:
            msg = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, dict):
            return
        records = list(msg.get("Clients") or [])
        if msg.get("Client"):
            records.append(msg["Client"])
        for c in records:
            if not isinstance(c, dict):
                continue
            guid, name = c.get("ClientGuid"), c.get("Name")
            if guid and name:
                self.roster[guid] = name

    def name_for(self, guid: str | None) -> str:
        """Friendly SRS name for a client GUID, or a short GUID stub if unknown."""
        if not guid:
            return "unknown"
        return self.roster.get(guid) or guid[:6]

    # --- voice ----------------------------------------------------------
    def transmit(self, opus_frames: list[bytes], freq_hz, modulation: int = AM,
                 settle: float = 0.4) -> None:
        """Send one transmission: a run of Opus frames, paced at 40 ms.

        `freq_hz` may be ONE frequency or SEVERAL, and several is not a trick --
        the SRS voice packet carries a variable-length frequency list and always
        has. This method simply wrapped a single value in it.

        WHY IT MATTERS HERE. The SCR-522 in a P-51 tunes four crystal channels
        and cannot reach 124.425; a modern radio can, and the published plate
        says 124.425 because that is the real frequency. So a controller working
        both has to choose which aircraft to be audible to -- unless one
        transmission carries both:

            "I wonder if SRS lets us duplex a channel, so we can use both
             124.425 for modern and 124.00 for a SCR-522 radio seamlessly."

        It does. Verified with three clients: a warbird listening on 124.000, a
        modern jet on 124.425, and one transmission naming both -- each heard it
        once. Not a relay, not two calls a beat apart: one packet, one voice, two
        radios, and neither pilot can tell there was a second frequency.

        This is what makes a mixed-era field possible at all. Without it the
        1944 Mustang and the F-16 are on different fields.
        """
        hz = [freq_hz] if isinstance(freq_hz, (int, float)) else list(freq_hz)
        freqs = [(float(f), modulation, 0) for f in hz]
        time.sleep(settle)          # let the server register our UDP source
        start = time.monotonic()
        for i, frame in enumerate(opus_frames):
            self.udp.sendto(self._voice_packet(frame, freqs), self.server)
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
                 + struct.pack("<I", self.unit_id)
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
                data, _src = self.udp.recvfrom(1500)
            except TimeoutError:
                continue
            except OSError:
                break
            if len(data) > GUID_LEN:
                packets += 1
                total += len(data)
        return packets, total

    def receive(self, duration: float):
        """Receive relayed voice, decode each packet's Opus frame to PCM.

        Returns (packet_count, int16 PCM samples). The ears half: this PCM is
        what Whisper will later transcribe. Each UDP voice packet carries one
        40 ms Opus frame right after the 6-byte length header.
        """
        import numpy as np
        import opuslib

        dec = opuslib.Decoder(tts.SRS_SAMPLE_RATE, tts.SRS_CHANNELS)
        self.udp.settimeout(0.5)
        end = time.monotonic() + duration
        packets = 0
        pcm: list = []
        while time.monotonic() < end:
            try:
                data, _src = self.udp.recvfrom(1500)
            except TimeoutError:
                continue
            except OSError:
                break
            if len(data) <= GUID_LEN:
                continue                      # a ping, not voice
            _plen, audio_len, _freq_len = struct.unpack("<HHH", data[:6])
            audio = data[6:6 + audio_len]
            try:
                frame = dec.decode(audio, tts.SAMPLES_PER_FRAME)
                pcm.append(np.frombuffer(frame, dtype="<i2"))
                packets += 1
            except Exception:
                pass
        samples = np.concatenate(pcm) if pcm else np.zeros(0, dtype="<i2")
        return packets, samples

    def recv_utterance(self, max_wait: float = 60.0, silence: float = 1.2):
        """Block until a transmission is heard, then return (int16 PCM, freq_hz)
        once the talker stops (a `silence`-second gap). (None, None) if nothing
        arrives within `max_wait`. One pilot 'over', tagged with the channel it
        came in on -- ready for Whisper.
        """
        import numpy as np
        import opuslib

        dec = opuslib.Decoder(tts.SRS_SAMPLE_RATE, tts.SRS_CHANNELS)
        self.udp.settimeout(0.3)
        frames: list = []
        freq_hz: float | None = None
        started = False
        t0 = time.monotonic()
        last = 0.0
        while True:
            now = time.monotonic()
            if not started and now - t0 > max_wait:
                return None, None
            if started and now - last > silence:
                break
            try:
                data, _src = self.udp.recvfrom(1500)
            except TimeoutError:
                continue
            except OSError:
                return None, None
            if len(data) <= GUID_LEN:
                continue
            _plen, audio_len, freq_len = struct.unpack("<HHH", data[:6])
            # WHOSE PACKET IS THIS -- ASKED FIRST, AND THAT ORDER IS THE BUG.
            #
            # The GUID check used to happen at the BOTTOM of this block, after
            # the audio had been decoded into `frames` and after the frequency
            # had been taken. `continue` then skipped only the bookkeeping, and
            # both of the things that mattered had already happened:
            #
            #   * OUR OWN VOICE WENT INTO THE PILOT'S UTTERANCE. SRS does not
            #     echo a client to itself but it does echo one client to
            #     another, and the ear and the transmit pool are different
            #     clients -- so the controller's last reply came back, was
            #     decoded, and was prepended to whatever the pilot said next.
            #     A live sortie transcribed as:
            #
            #       PILOT: sockeye, your on Kobuleti Clearance, 125 decimal 1,
            #       not ground, ground is 121 decimal 8, taxi requests go there.
            #       Kobuleti Ground, sockeye with information alpha ready to taxi.
            #
            #     The first sentence is the CONTROLLER'S. The agent was being
            #     handed its own words back as though the pilot had said them.
            #
            #   * THE FREQUENCY CAME OFF THE WRONG PACKET. `freq_hz` is set from
            #     the first block seen, and ours arrived first -- so a pilot
            #     transmitting on Ground 121.800 was logged, answered and
            #     STATION-RESOLVED as though he were on Clearance 125.100. He
            #     was told repeatedly that he was on the wrong frequency by a
            #     controller reading our own transmission's channel.
            #
            # One `continue`, moved up. Everything below it now sees only
            # packets from somebody who is not us.
            _guid = data[-GUID_LEN:].decode("ascii", "ignore")
            if _guid in self.ignore_guids:
                continue
            try:
                pcm = dec.decode(data[6:6 + audio_len], tts.SAMPLES_PER_FRAME)
                frames.append(np.frombuffer(pcm, dtype="<i2"))
                _on = None
                if freq_len >= 8:
                    (_on,) = struct.unpack("<d", data[6 + audio_len:6 + audio_len + 8])
                    if freq_hz is None:                    # first freq block
                        freq_hz = _on
                self.last_sender_guid = _guid
                started = True
                last = now
                # Somebody is on the air RIGHT NOW. Read by the transmitting
                # threads so the controller does not talk over a pilot -- see
                # `someone_is_talking`.
                #
                # PER FREQUENCY, because this client listens on all of them.
                # One timestamp for twelve channels meant a pilot talking to
                # Kobuleti Clearance held Batumi Approach off the air forty
                # miles away -- a courtesy applied to the wrong conversation.
                # It only mattered once there was more than one aerodrome, and
                # it gets worse with every field added.
                self.last_rx = time.monotonic()
                if _on:
                    self.last_rx_hz[int(round(_on))] = self.last_rx
            except Exception:
                pass
        return (np.concatenate(frames) if frames else None), freq_hz

    def someone_is_talking(self, within: float = 1.5, freq_hz=None) -> bool:
        """Is a pilot keying the mic right now?

        The radio lock only stops this client's own threads overlapping each
        other; it knows nothing about the humans. So the mile-call metronome
        transmitted on its own schedule regardless of what was happening on the
        frequency, and a pilot reported the controller "talks over us
        constantly, and didn't give us time for a readback".

        A real radio is half duplex and so is the courtesy: if voice packets
        arrived within the last second and a half, the channel is his.


        WHICH CHANNEL. Pass `freq_hz` and the answer is about that frequency
        alone; omit it and the answer is "anybody, anywhere", which is what
        this always used to mean and is almost never what a caller wants now.
        A single controller standing off because a pilot at another aerodrome
        is talking is not courtesy, it is the wrong conversation.
        """
        if freq_hz:
            for hz in (freq_hz if isinstance(freq_hz, (list, tuple)) else [freq_hz]):
                if time.monotonic() - self.last_rx_hz.get(int(round(hz)), 0.0) < within:
                    return True
            return False
        return (time.monotonic() - self.last_rx) < within

    def close(self) -> None:
        self._stop.set()
        for s in (self.tcp, self.udp):
            try:
                s and s.close()
            except OSError:
                pass


if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else config.SRS_HOST
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
