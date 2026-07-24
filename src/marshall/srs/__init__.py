"""The SRS voice bridge.

A standalone SimpleRadio Standalone (SRS) client that lets Marshall talk to --
and, later, listen to -- human pilots over the sim's voice radio, independent of
DCS-gRPC (whose TTS is transmit-only and broken here).

    tts.py     text -> Opus frames (Polly renders PCM; we resample + encode)
    client.py  the SRS client: TCP registration + UDP voice transmit

The brain never lives here: this is ears and mouth. A clearance string from
atc/controller.py is voiced; a pilot transmission (future) becomes an Intent.
"""
