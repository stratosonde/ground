# Stratosonde Ground Station — API Reference (for LLM/agent access)

This document describes the public HTTP API of the Stratosonde Ground Station so
that another program or LLM agent can read radiosonde telemetry.

## Base URL

```
https://uplink.stratosonde.org
```

- Served by a FastAPI app (origin `localhost:8005`) behind a Cloudflare Tunnel.
- All responses are JSON unless noted.
- A machine-readable OpenAPI spec is available and is the recommended way to
  auto-generate tools:
  - OpenAPI JSON: `GET https://uplink.stratosonde.org/openapi.json`
  - Swagger UI:    `GET https://uplink.stratosonde.org/docs`

> ⚠️ **Security note:** the API is currently **public and unauthenticated**.
> Anyone with the URL can read all telemetry, and `POST /` accepts webhook data.
> Treat it as read-only for LLM use and do not expose write access.

---

## Recommended usage pattern for an LLM

1. Call `GET /api/devices` to discover devices and their `dev_eui`.
2. For "current status" questions, call `GET /api/latest?dev_eui=<eui>` — this
   returns a single small record (best for token budgets).
3. Only call `GET /api/telemetry` when you need history, and **always pass a
   small `limit`**. The full payload (`limit=1000`) is ~550 KB of verbose JSON
   and will overflow most context windows. Prefer `limit=1` to `limit=50`.

---

## Endpoints

### `GET /health`
Liveness + aggregate counts. Cheap; safe to poll.

Response:
```json
{ "status": "healthy", "devices": 2, "total_data_points": 605 }
```

### `GET /api/devices`
List all known devices with a summary. Small payload — call this first.

Response:
```json
[
  {
    "dev_eui": "6081f95325100915",
    "device_name": "strato3",
    "last_seen": "2026-02-15T03:28:48.180+00:00",
    "packet_count": 496
  }
]
```

### `GET /api/latest?dev_eui=<eui>`
Most recent telemetry point for one device. **Required:** `dev_eui`.
Returns a single record (see schema below), or `{"message": "No data available"}`.

### `GET /api/telemetry?dev_eui=<eui>&limit=<n>`
Historical telemetry for one device, oldest→newest, capped to the last `limit`
points.
- `dev_eui` — **required** string.
- `limit` — optional integer, default `1000`. **Keep this small for LLM use.**

Returns a JSON array of records (schema below).

### `GET /api/version?dev_eui=<eui>`
Most recent **Port 20 version report** for one device — the firmware and
heartbeat wire-format version the device announced (A-005/#79). Small payload.
Returns `{"message": "No version report available"}` if the device has not sent
a version frame yet. Example response:
```json
{
  "device_name": "strato3",
  "dev_eui": "6081f95325100915",
  "firmware_version": "1.0.0",
  "format_version": 2,
  "stage_name": "COMMISSIONING",
  "mission_minutes": 1234,
  "crc_valid": true
}
```
`format_version` is the heartbeat wire version the backend should expect for
that device's Port 10 frames; `crc_valid` reports the CRC-16/CCITT check.

### `GET /` and `GET /viewer`
`/` returns a status object. `/viewer` serves the CesiumJS 3D map (HTML, not for
programmatic use).

---

## Telemetry record schema

Each telemetry point is a JSON object. Fields observed on a live record:

| Field | Type | Meaning |
|---|---|---|
| `timestamp` | string (ISO 8601) | Uplink receive time (UTC) |
| `device_name` | string | Friendly device name (e.g. `strato3`) |
| `dev_eui` | string | LoRaWAN device EUI (unique id) |
| `dev_addr` | string | LoRaWAN device address |
| `application_name` | string | ChirpStack application |
| `device_profile_name` | string | ChirpStack device profile |
| `tenant_name` | string | ChirpStack tenant |
| `latitude` | float | Degrees. `0.0` may mean no GPS lock (see fallback note) |
| `longitude` | float | Degrees |
| `altitude` | float | Meters |
| `temperature` | float | °C |
| `humidity` | float | % RH |
| `pressure` | float | hPa |
| `satellites` | float | GNSS satellites used |
| `battery_voltage` | float | Volts |
| `power_rail_voltage` | float | Volts |
| `solar_panel_voltage` | float | Volts |
| `voltage_slope` | float | mV/h ÷ 10 as sent by device |
| `time_to_target` | float | Hours: +charging, -depletion, 0=stable |
| `operating_mode` | float | 0=NORMAL,1=CONSERVATIVE,2=REDUCED,3=RECOVERY,4=SURVIVAL |
| `hdop` | float | GNSS horizontal dilution of precision |
| `ttf_seconds` | float | Time-to-fix, seconds |
| `rssi` | int | Best gateway RSSI (dBm) |
| `snr` | float | Best gateway SNR (dB) |
| `fcnt` | int | LoRaWAN frame counter |
| `dr` | int | Data rate |
| `adr` | bool | Adaptive data rate enabled |
| `f_port` | int | LoRaWAN port (2=telemetry, 3=GNSS detail, 11=bulk) |
| `confirmed` | bool | Confirmed uplink |
| `frequency` | int | Hz |
| `spreading_factor` | int | LoRa SF |
| `bandwidth` | int | Hz |
| `code_rate` | string | e.g. `CR_4_5` |
| `gateways` | array | Receiving gateways (see below), sorted by RSSI desc |
| `gnss_detail` | object/null | Per-satellite GNSS detail when available (Port 3) |

Each entry in `gateways`:

| Field | Type | Meaning |
|---|---|---|
| `gateway_id` | string | Gateway EUI |
| `gateway_name` | string | Gateway name |
| `rssi` | int | dBm |
| `snr` | float | dB |
| `latitude` / `longitude` | float | Gateway location |
| `distance` | float | Meters from reported sensor position |
| `network` | string | e.g. `helium_iot` |
| `region` | string | e.g. `US915` |
| `h3_index` | string | H3 cell of the gateway |

### Packet types feeding telemetry
Telemetry points carry an `f_port` indicating the source LoRaWAN packet:
- **`f_port: 10`** — the 11-byte compact heartbeat (SF10, low-res, current
  position/sensors).
- **`f_port: 11`** — high-resolution archive records (bulk v6, SF7 backfill).
  These carry `bulk_sequence`, `sensor_quality`, `veto_reason`, and
  `crc16_valid`. Port 10 and Port 11 measurements of the same air should agree
  (e.g. pressure); both are decoded little-endian per the firmware v6 wire spec.

### GPS fallback note
When the radiosonde GPS reports `0.0, 0.0` (not yet locked), the system may use
the strongest-signal gateway's location as an approximate position. Once the GPS
locks, actual sensor coordinates are used. Check `satellites`/`hdop` to judge fix
quality.

---

## Example calls

```bash
# 1) discover devices
curl -s "https://uplink.stratosonde.org/api/devices"

# 2) current status for one device (small, ideal for LLM)
curl -s "https://uplink.stratosonde.org/api/latest?dev_eui=6081f95325100915"

# 3) last 20 points of history (keep limit small)
curl -s "https://uplink.stratosonde.org/api/telemetry?dev_eui=6081f95325100915&limit=20"

# 4) the machine-readable contract for auto-generating tools
curl -s "https://uplink.stratosonde.org/openapi.json"
```

## Known device EUIs (as of last update)

| dev_eui | name |
|---|---|
| `6081f95325100915` | strato3 |
| `6081f95325200915` | strato4 |

(Device list is dynamic — always confirm via `GET /api/devices`.)
