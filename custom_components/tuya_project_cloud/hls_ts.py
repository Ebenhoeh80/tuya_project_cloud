"""Minimal MPEG-TS timestamp handling for the local HLS stream proxy.

Tuya starts a fresh HLS session roughly every 30 s. Its new segments restart
their MPEG-TS timestamps near zero while FFmpeg does not apply an HLS
discontinuity offset. Home Assistant's stream validator therefore sees a jump
of about 30 s. The proxy rebases each new session to the previous timeline.

Only PCR, PTS and DTS fields are touched; packet boundaries and continuity
counters stay unchanged.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_PTS_MODULO = 1 << 33
_PACKET_SIZE = 188
# These PES stream IDs have no optional header and therefore no PTS/DTS.
_PES_WITHOUT_TIMESTAMPS = frozenset({0xBC, 0xBE, 0xBF})


def decrypt(data: bytes, key: bytes, iv: bytes) -> bytes | None:
    """Decrypt an AES-128 HLS segment with the playlist's key and IV."""
    if len(key) != 16 or len(iv) != 16 or len(data) % 16:
        return None
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def encrypt(data: bytes, key: bytes, iv: bytes) -> bytes | None:
    """Re-encrypt a rewritten segment so the playlist's key tag stays valid."""
    if len(key) != 16 or len(iv) != 16 or len(data) % 16:
        return None
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(data) + encryptor.finalize()


def _read_timestamp(data: bytes, offset: int) -> int | None:
    """Decode a 33-bit MPEG-TS PTS/DTS field."""
    if offset + 5 > len(data):
        return None
    return (
        ((data[offset] >> 1) & 0x07) << 30
        | data[offset + 1] << 22
        | ((data[offset + 2] >> 1) & 0x7F) << 15
        | data[offset + 3] << 7
        | (data[offset + 4] >> 1)
    )


def _write_timestamp(data: bytearray, offset: int, value: int) -> None:
    """Encode a 33-bit PTS/DTS field, preserving its prefix and marker bits."""
    value %= _PTS_MODULO
    data[offset] = (data[offset] & 0xF0) | (((value >> 30) & 0x07) << 1) | 0x01
    data[offset + 1] = (value >> 22) & 0xFF
    data[offset + 2] = (data[offset + 2] & 0x01) | (((value >> 15) & 0x7F) << 1)
    data[offset + 3] = (value >> 7) & 0xFF
    data[offset + 4] = (data[offset + 4] & 0x01) | ((value & 0x7F) << 1)


def _read_pcr(data: bytes, offset: int) -> int | None:
    """Decode the 33-bit PCR base of an adaptation field."""
    if offset + 6 > len(data):
        return None
    return (
        data[offset] << 25
        | data[offset + 1] << 17
        | data[offset + 2] << 9
        | data[offset + 3] << 1
        | (data[offset + 4] >> 7)
    )


def _write_pcr(data: bytearray, offset: int, value: int) -> None:
    """Encode a PCR base without changing its extension."""
    value %= _PTS_MODULO
    data[offset] = (value >> 25) & 0xFF
    data[offset + 1] = (value >> 17) & 0xFF
    data[offset + 2] = (value >> 9) & 0xFF
    data[offset + 3] = (value >> 1) & 0xFF
    # Bits 6..1 are reserved and must stay set; bit 0 carries the extension flag.
    data[offset + 4] = (data[offset + 4] & 0x01) | 0x7E | ((value & 0x01) << 7)


def _pes_timestamp_positions(packet: bytes, index: int) -> tuple[int, ...]:
    """Return in-packet offsets of PTS/DTS fields when a PES header fits."""
    if index + 9 > _PACKET_SIZE or packet[index : index + 3] != b"\x00\x00\x01":
        return ()
    if packet[index + 3] in _PES_WITHOUT_TIMESTAMPS:
        return ()
    if packet[index + 6] & 0xC0 != 0x80:
        return ()
    flags = packet[index + 7]
    field = index + 9
    if flags & 0xC0 == 0xC0:
        return (field, field + 5) if field + 10 <= _PACKET_SIZE else ()
    if flags & 0x80:
        return (field,) if field + 5 <= _PACKET_SIZE else ()
    return ()


def is_later(value: int, previous: int) -> bool:
    """Compare 33-bit timestamps across the wraparound boundary."""
    return ((value - previous) % _PTS_MODULO) < (_PTS_MODULO // 2)


def timestamps(data: bytes) -> tuple[int | None, int | None]:
    """Return the first DTS and the last timestamp of a clear segment."""
    first_dts: int | None = None
    last_dts: int | None = None
    first_pcr: int | None = None
    last_pcr: int | None = None
    for start in range(0, len(data) - _PACKET_SIZE + 1, _PACKET_SIZE):
        packet = data[start : start + _PACKET_SIZE]
        if packet[0] != 0x47:
            return None, None
        has_adaptation = bool(packet[3] & 0x20)
        has_payload = bool(packet[3] & 0x10)
        index = 4
        if has_adaptation:
            length = packet[4]
            if 5 + length > _PACKET_SIZE:
                return None, None
            if length >= 7 and packet[5] & 0x10:
                value = _read_pcr(packet, 6)
                if value is not None:
                    if first_pcr is None:
                        first_pcr = value
                    last_pcr = value
            index = 5 + length
        if not has_payload or not (packet[1] & 0x40):
            continue
        positions = _pes_timestamp_positions(packet, index)
        if not positions:
            continue
        # Prefer DTS over PTS for PTS+DTS packets: rebasing uses presentation
        # order, and HA validates DTS continuity.
        value = _read_timestamp(packet, positions[-1])
        if value is None:
            continue
        if first_dts is None:
            first_dts = value
        last_dts = value
    first = first_dts if first_dts is not None else first_pcr
    last = last_dts
    if last_pcr is not None and (last is None or is_later(last_pcr, last)):
        last = last_pcr
    return first, last


def shift(data: bytes, offset: int) -> bytes:
    """Add an offset (in 90 kHz ticks) to every PCR, PTS and DTS field."""
    if not offset:
        return data
    output = bytearray(data)
    delta = offset % _PTS_MODULO
    for start in range(0, len(output) - _PACKET_SIZE + 1, _PACKET_SIZE):
        packet = output[start : start + _PACKET_SIZE]
        if packet[0] != 0x47:
            continue
        has_adaptation = bool(packet[3] & 0x20)
        has_payload = bool(packet[3] & 0x10)
        index = 4
        if has_adaptation:
            length = packet[4]
            if 5 + length > _PACKET_SIZE:
                continue
            if length >= 7 and packet[5] & 0x10:
                value = _read_pcr(packet, 6)
                if value is not None:
                    _write_pcr(output, start + 6, value + delta)
            index = 5 + length
        if not has_payload or not (packet[1] & 0x40):
            continue
        for position in _pes_timestamp_positions(packet, index):
            value = _read_timestamp(packet, position)
            if value is not None:
                _write_timestamp(output, start + position, value + delta)
    return bytes(output)
