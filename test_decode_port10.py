#!/usr/bin/env python3
"""
Golden-vector tests for the Port 10 heartbeat v2 decoder.

Vectors are taken directly from the firmware host suite
(stratosonde/firmware tests/host/test_main.c, printed as `GOLDEN heartbeat-v2:`)
and the wire spec in docs/PayloadFormats.md / docs/LoRaWANApplicationProtocol.md.

These guard against silent drift on the next wire-format bump: if the firmware
changes the layout, this test must be updated in lockstep with a new vector.

Run:  python3 test_decode_port10.py
"""

import base64
import unittest

from ground_station import decode_port10_compact


def b64(hex_str):
    """Turn a space-separated hex string into the base64 ChirpStack sends."""
    raw = bytes.fromhex(hex_str.replace(" ", ""))
    return base64.b64encode(raw).decode("ascii")


class TestPort10HeartbeatV2(unittest.TestCase):

    # Golden vector from firmware host suite (§13 LoRaWANApplicationProtocol):
    #   C8 32 FF 3F F0 AE 4C F5 4B 64 10   (nominal sensors)
    GOLDEN = "C8 32 FF 3F F0 AE 4C F5 4B 64 10"

    def test_golden_vector_decodes(self):
        r = decode_port10_compact(b64(self.GOLDEN))
        self.assertIsNotNone(r, "golden 11-byte v2 vector must decode")

    def test_golden_fields(self):
        r = decode_port10_compact(b64(self.GOLDEN))
        # timestamp: 0x32C8 LE = 13000 minutes
        self.assertEqual(r["timestamp_minutes"], 13000)
        # latitude: 0x3FFF = 16383 -> 16383*90/32767 = 44.9986 deg
        self.assertAlmostEqual(r["latitude"], 16383 * 90.0 / 32767.0, places=4)
        # longitude: 0xAEF0 signed = -20752 -> -20752*180/32767 = -113.99 deg
        self.assertAlmostEqual(r["longitude"], -20752 * 180.0 / 32767.0, places=4)
        # temperature: 0x4C = 76 -> (76-64)*2 = 24 C
        self.assertEqual(r["temperature"], 24)
        # press/hum word: 0x4BF5 LE -> pressure bits0-10, humidity bits11-15
        word = 0x4BF5
        self.assertEqual(r["pressure"], word & 0x07FF)          # 1013 hPa
        self.assertEqual(r["pressure"], 1013)
        self.assertEqual(r["humidity"], ((word >> 11) & 0x1F) * 5)  # 9*5 = 45 %
        self.assertEqual(r["humidity"], 45)
        # battery: 0x64 = 100 -> 100*0.05 = 5.0 V
        self.assertAlmostEqual(r["battery_voltage"], 5.0, places=3)
        # status: 0x10 -> only RTC GNSS-disciplined bit set
        self.assertTrue(r["time_gnss_disciplined"])
        self.assertFalse(r["gps_stale"])
        self.assertFalse(r["timestamp_wrapped"])
        self.assertEqual(r["mission_state"], 0)
        self.assertEqual(r["mission_state_name"], "COMMISSIONING")
        # altitude is derived (not on the wire) and present for valid pressure
        self.assertIsNotNone(r["altitude_calculated"])

    def test_wrong_length_rejected(self):
        # Old v1 10-byte frame must not be misdecoded as v2
        self.assertIsNone(decode_port10_compact(b64("00 11 22 33 44 55 66 77 88 99")))
        # 12 bytes rejected too
        self.assertIsNone(decode_port10_compact(b64("00 11 22 33 44 55 66 77 88 99 AA BB")))

    def test_invalid_base64_returns_none(self):
        self.assertIsNone(decode_port10_compact("!!!not-base64!!!"))

    def test_pressure_humidity_sentinels(self):
        # pressure bits = 0x7FF (2047, invalid), humidity bits = 31 (invalid)
        # word = (31 << 11) | 0x7FF = 0xFFFF
        payload = bytes([0, 0, 0, 0, 0, 0, 64, 0xFF, 0xFF, 100, 0x00])
        r = decode_port10_compact(base64.b64encode(payload).decode())
        self.assertIsNone(r["pressure"])
        self.assertIsNone(r["humidity"])
        self.assertIsNone(r["altitude_calculated"])

    def test_mission_state_float(self):
        # status bits 6-7 = 0b10 -> FLOAT (mission state 2)
        payload = bytes([0, 0, 0, 0, 0, 0, 64, 0x00, 0x00, 100, 0x80])
        r = decode_port10_compact(base64.b64encode(payload).decode())
        self.assertEqual(r["mission_state"], 2)
        self.assertEqual(r["mission_state_name"], "FLOAT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
