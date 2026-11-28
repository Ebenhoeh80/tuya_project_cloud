"""Tests for MPEG-TS timestamp rebasing in the local HLS proxy."""

from __future__ import annotations

from custom_components.tuya_project_cloud.hls_ts import (
    _write_pcr,
    _write_timestamp,
    decrypt,
    encrypt,
    shift,
    timestamps,
)

_KEY = bytes(range(16))
_IV = bytes(range(16, 32))
_TICK = 90000


def _packet(*, pcr: int | None, dts: int | None, pusi: bool = True) -> bytearray:
    """Build one 188-byte TS packet with optional PCR and PES timestamps."""
    packet = bytearray(188)
    packet[0] = 0x47
    packet[1] = 0x40 if pusi else 0x00
    packet[2] = 0x00
    packet[3] = 0x30
    if pcr is not None:
        packet[4] = 7
        packet[5] = 0x10
        _write_pcr(packet, 6, pcr)
    payload = 12 if pcr is not None else 5
    if pusi and dts is not None:
        packet[payload : payload + 3] = b"\x00\x00\x01"
        packet[payload + 3] = 0xE0
        packet[payload + 7] = 0xC0
        packet[payload + 8] = 10
        _write_timestamp(packet, payload + 9, dts)
        _write_timestamp(packet, payload + 14, dts)
    return packet


def test_timestamps_reads_first_and_last_dts() -> None:
    data = bytes(_packet(pcr=1 * _TICK, dts=1 * _TICK)) + bytes(
        _packet(pcr=2 * _TICK, dts=2 * _TICK, pusi=False)
    )
    assert timestamps(data) == (1 * _TICK, 2 * _TICK)


def test_shift_updates_timestamps_without_packet_changes() -> None:
    data = bytes(_packet(pcr=1 * _TICK, dts=1 * _TICK))
    result = shift(data, 30 * _TICK)
    assert timestamps(result) == (31 * _TICK, 31 * _TICK)
    assert len(result) == len(data)
    assert result[0] == data[0] == 0x47
    assert result[3] == data[3]


def test_shift_handles_33_bit_wraparound() -> None:
    data = bytes(_packet(pcr=(1 << 33) - _TICK, dts=(1 << 33) - _TICK))
    assert timestamps(shift(data, 2 * _TICK)) == (_TICK, _TICK)


def test_encrypt_decrypt_roundtrip() -> None:
    data = bytes(_packet(pcr=_TICK, dts=_TICK)) * 8
    encrypted = encrypt(data, _KEY, _IV)
    assert encrypted is not None
    assert encrypted != data
    assert decrypt(encrypted, _KEY, _IV) == data


def test_invalid_key_material_is_rejected() -> None:
    assert decrypt(b"not-aligned", _KEY, _IV) is None
    assert encrypt(b"not-aligned", _KEY, _IV) is None
