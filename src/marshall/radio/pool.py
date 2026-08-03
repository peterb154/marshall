"""Several mouths on the radio, so controllers do not queue behind each other.

    "Maybe we can have a pool of clients... maybe we can get away with 10
     shared. I'd plan for never more than 50 pilots. Most times it will be
     1-10."

WHY A POOL AND NOT ONE CLIENT PER STATION. A client can only play one audio
stream at a time -- that is unavoidable, it is one stream of paced frames -- so
concurrency comes from having more of them. One per station scales with
AIRPORTS, which is the wrong axis: thirty aerodromes is a hundred and twenty
clients, nearly all of them permanently silent. A pool scales with concurrent
SPEECH, which is bounded by how many people are flying.

MEASURED BEFORE BUILT, because the whole idea rests on it:

    opening         100 clients in 0.4 s, 4 ms each
    transmitting    10 at once took 9.8 s wall for 9.4 s of audio.
                    Serialised the same work would have been 98 s.

So ten is generous for one to ten pilots and survives fifty.

PER-FREQUENCY, NOT GLOBAL, and this is the part that is easy to get wrong.

The lock this replaces was global: one transmission anywhere blocked every
other. Removing it entirely would let two controllers key the SAME frequency
at once, which is not concurrency, it is two voices over each other -- and on
a real radio that is exactly what a blocked transmission sounds like.

So a frequency is what is serialised. Two controllers at two aerodromes talk
simultaneously; two transmissions on one channel wait, as they must. That is
also the honest model of a radio: one frequency, one voice.

WAITING, NEVER DROPPING. A pool with nobody free blocks until somebody
finishes. Dropping would be silence on the air, which a pilot reads as a
controller who has stopped listening -- the single worst failure this system
has. A pool that is permanently saturated is a sizing bug, so it says so.
"""

from __future__ import annotations

import threading
import time

from marshall.radio.client import AM, SRSClient, radio

DEFAULT_SIZE = 10
# How long a transmission may wait for a free client before we say so. Not a
# timeout -- it still waits -- just the point at which silence stops being
# normal and starts being worth a line in the log.
SLOW_WARN_SEC = 2.0


class TransmitPool:
    """N SRS clients, borrowed for the length of one transmission.

    The clients are interchangeable and their SRS names are not meaningful:

        "Marshall-1 to -10 is fine. SRS name doesn't matter much. ATC always
         identifies itself."

    Which is true and is what makes the pool simple -- a controller says who he
    is in the first three words, so nothing downstream needs the client that
    carried him to have a particular name.
    """

    def __init__(self, host: str, port: int = 5002, size: int = DEFAULT_SIZE,
                 name: str = "Marshall", radios=None, log=print):
        self.log = log
        self._free: list[SRSClient] = []
        self._sem = threading.Semaphore(size)
        self._pick = threading.Lock()
        # ONE LOCK PER FREQUENCY, made on demand. A dict of locks rather than
        # one lock: the whole point is that 124.425 and 133.000 do not wait for
        # each other.
        self._chan: dict[int, threading.Lock] = {}
        self._chan_guard = threading.Lock()
        self.waits: list[float] = []
        for i in range(size):
            c = SRSClient(host, port=port, name=f"{name}-{i + 1}")
            c.connect(list(radios or []))
            self._free.append(c)

    def _lock_for(self, hz: float) -> threading.Lock:
        key = int(round(hz))
        with self._chan_guard:
            got = self._chan.get(key)
            if got is None:
                got = self._chan[key] = threading.Lock()
            return got

    def transmit(self, frames: list[bytes], freq_hz, modulation: int = AM,
                 settle: float = 0.4) -> None:
        """Put one transmission on the air, on one frequency or several."""
        freqs = list(freq_hz) if isinstance(freq_hz, (list, tuple)) else [freq_hz]
        # SORTED, so two transmissions wanting overlapping channel sets take
        # them in the same order and cannot deadlock against each other. A
        # facility owning several frequencies makes that a real case, not a
        # theoretical one -- see `channels_of`.
        locks = [self._lock_for(f) for f in sorted(freqs)]
        t0 = time.monotonic()
        for lk in locks:
            lk.acquire()
        try:
            self._sem.acquire()
            waited = time.monotonic() - t0
            self.waits.append(waited)
            if waited > SLOW_WARN_SEC:
                # Saturation is a sizing bug and must not be silent: from the
                # cockpit a queued transmission is indistinguishable from a
                # controller who has gone quiet.
                self.log(f"  !! radio pool: waited {waited:.1f}s for a free "
                         f"client -- {len(self._free)} idle of "
                         f"{self._sem._value + 1}; consider a larger pool")
            with self._pick:
                client = self._free.pop()
            try:
                client.transmit(frames, freqs, modulation, settle=settle)
            finally:
                with self._pick:
                    self._free.append(client)
                self._sem.release()
        finally:
            for lk in reversed(locks):
                lk.release()

    def stats(self) -> dict:
        """For `/diag`. A pool nobody can see is a pool nobody trusts."""
        w = self.waits[-200:]
        return {"idle": len(self._free),
                "channels": len(self._chan),
                "waited_max_s": round(max(w), 2) if w else 0.0,
                "transmissions": len(self.waits)}

    def close(self) -> None:
        for c in self._free:
            try:
                c.close()
            except Exception:
                pass


def one_radio(mhz: float):
    """A radio block for a frequency in MHz, which is how route.py holds them."""
    return radio(mhz * 1e6)
