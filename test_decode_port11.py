#!/usr/bin/env python3
"""
Golden-vector tests for the Port 11 bulk archive v6 decoder.

The golden frame is generated from the firmware's exact serialization
(stratosonde/firmware Core/Src/payload_encode.c EncodeBulkPacketV6 +
SerializeRecordV3LE), with the sensor_t lat/lon binary scaling from
sys_sensors.c (deg * 8388607 / 90 and /180). CRC-16/MODBUS per record and
CRC-32/ISO-HDLC over the packet, matching CalculateCRC16 / CalculateCRC32.

Golden (1 record, seq=256, Calgary-ish coords, 886.3 hPa, -45.8 C, 16.9 %,
gps_fix_valid flag set):
  06 01 00 01 00 00 A0 8B 93 68 C6 BF 48 00 12 E2 AE FF EC 4F 36 FE
  A9 00 9F 22 EA 22 74 15 39 03 07 09 00 01 00 00 68 13 7A DE CF 54

These guard against silent drift on the next wire bump; update in lockstep
with a fresh firmware vector if the format changes.

Run:  python3 test_decode_port11.py
"""

import base64
import struct
import unittest

from ground_station import decode_port11_bulk, _crc16_modbus, _crc32_ieee

GPS_SCALE = 8388607.0


def build_v6(records, seqs):
    """Mirror the firmware EncodeBulkPacketV6 for test-vector construction.
    Each record is a dict of already-scaled integer wire fields."""
    body = bytes([0x06, len(records)])
    for seq, r in zip(seqs, records):
        body += struct.pack("<I", seq)
        rec = struct.pack(
            "<IiiHhHHHHhBBBBBB",
            r["ts"], r["lat"], r["lon"], r["alt"], r["temp"], r["hum"],
            r["press"], r["batt"], r["solar"], r["slope"], r["sats"],
            r["hdop"], r["mode"], r["flags"], r["sq"], r["veto"],
        )
        rec += struct.pack("<H", _crc16_modbus(rec))
        body += rec
    return body + struct.pack("<I", _crc32_ieee(body))


NOMINAL = {
    "ts": 1754500000,
    "lat": round(51.15173 * GPS_SCALE / 90),
    "lon": round(-114.07068 * GPS_SCALE / 180),
    "alt": 20460, "temp": -458, "hum": 169, "press": 8863,
    "batt": 8938, "solar": 5492, "slope": 825, "sats": 7, "hdop": 9,
    "mode": 0, "flags": 0x01, "sq": 0, "veto": 0,
}


class TestPort11BulkV6(unittest.TestCase):

    GOLDEN = ("0601000100 00A08B9368C6BF480012E2AEFFEC4F36FE"
              "A9009F22EA2274153903070900010000 68137ADE CF54")

    def b64(self, hex_str):
        return base64.b64encode(bytes.fromhex(hex_str.replace(" ", ""))).decode()

    def test_golden_structure(self):
        r = decode_port11_bulk(self.b64(self.GOLDEN))
        self.assertIsNotNone(r)
        self.assertEqual(r["packet_type"], 0x06)
        self.assertEqual(r["record_count"], 1)
        self.assertTrue(r["crc32_valid"])
        self.assertEqual(len(r["records"]), 1)

    def test_golden_fields_match_heartbeat_units(self):
        r = decode_port11_bulk(self.b64(self.GOLDEN))["records"][0]
        self.assertEqual(r["sequence"], 256)
        self.assertAlmostEqual(r["latitude"], 51.15173, places=4)
        self.assertAlmostEqual(r["longitude"], -114.07068, places=4)
        self.assertEqual(r["altitude"], 20460)
        self.assertAlmostEqual(r["temperature"], -45.8, places=1)
        self.assertAlmostEqual(r["humidity"], 16.9, places=1)
        # The whole point of the fix: pressure decodes to ~886 hPa (sane,
        # agrees with the Port 10 heartbeat), NOT ~2750.
        self.assertAlmostEqual(r["pressure"], 886.3, places=1)
        self.assertAlmostEqual(r["battery_voltage"], 8.938, places=3)
        self.assertAlmostEqual(r["solar_voltage"], 5.492, places=3)
        self.assertEqual(r["voltage_slope"], 825)
        self.assertEqual(r["satellites"], 7)
        self.assertAlmostEqual(r["hdop"], 0.9, places=1)
        self.assertEqual(r["power_mode_name"], "NORMAL")
        self.assertTrue(r["gps_fix_valid"])
        self.assertTrue(r["crc16_valid"])

    def test_roundtrip_builder_matches_golden(self):
        frame = build_v6([NOMINAL], [256])
        self.assertEqual(frame.hex().upper(),
                         self.GOLDEN.replace(" ", "").upper())

    def test_multi_record(self):
        frame = build_v6([NOMINAL, NOMINAL, NOMINAL], [256, 257, 258])
        r = decode_port11_bulk(base64.b64encode(frame).decode())
        self.assertEqual(r["record_count"], 3)
        self.assertTrue(r["crc32_valid"])
        self.assertEqual([rec["sequence"] for rec in r["records"]], [256, 257, 258])
        for rec in r["records"]:
            self.assertTrue(rec["crc16_valid"])
            self.assertAlmostEqual(rec["pressure"], 886.3, places=1)

    def test_sensor_quality_bits(self):
        rec = dict(NOMINAL, sq=0x0B)  # press+temp+gnss stale (b0,b1,b3)
        r = decode_port11_bulk(base64.b64encode(build_v6([rec], [1])).decode())["records"][0]
        self.assertTrue(r["press_stale"])
        self.assertTrue(r["temp_stale"])
        self.assertFalse(r["hum_stale"])
        self.assertTrue(r["gnss_stale"])

    def test_bad_crc32_flagged(self):
        frame = bytearray(build_v6([NOMINAL], [256]))
        frame[-1] ^= 0xFF
        r = decode_port11_bulk(base64.b64encode(bytes(frame)).decode())
        self.assertFalse(r["crc32_valid"])

    def test_wrong_packet_type_rejected(self):
        self.assertIsNone(decode_port11_bulk(self.b64("01 01 00 00 00 00")))

    def test_wrong_length_rejected(self):
        # v6 header claiming 1 record but truncated body
        self.assertIsNone(decode_port11_bulk(self.b64("06 01 00 00 00 00")))

    def test_invalid_base64_returns_none(self):
        self.assertIsNone(decode_port11_bulk("!!!not-base64!!!"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
