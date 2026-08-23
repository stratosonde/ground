from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from datetime import datetime
import json
import os
from pathlib import Path

app = FastAPI(title="Stratosonde Ground Station")

# Base directory of this script (so paths work regardless of CWD / under systemd)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Data directory (gitignored) and file path pattern
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE_PATTERN = "telemetry_data_{dev_eui}.json"

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_data_file(dev_eui):
    """Get the data file path for a specific device"""
    return os.path.join(DATA_DIR, DATA_FILE_PATTERN.format(dev_eui=dev_eui))


def load_telemetry(dev_eui):
    """Load existing telemetry data for a specific device"""
    data_file = get_data_file(dev_eui)
    if os.path.exists(data_file):
        with open(data_file, 'r') as f:
            return json.load(f)
    return []


def save_telemetry(dev_eui, data):
    """Save telemetry data to device-specific JSON file"""
    data_file = get_data_file(dev_eui)
    with open(data_file, 'w') as f:
        json.dump(data, f, indent=2)


def get_available_devices():
    """Get list of all devices with telemetry data"""
    devices = []
    for filename in os.listdir(DATA_DIR):
        if filename.startswith('telemetry_data_') and filename.endswith('.json'):
            dev_eui = filename.replace('telemetry_data_', '').replace('.json', '')
            data_file = get_data_file(dev_eui)
            try:
                with open(data_file, 'r') as f:
                    data = json.load(f)
                    if data:
                        latest = data[-1]
                        devices.append({
                            'dev_eui': dev_eui,
                            'device_name': latest.get('device_name', 'Unknown'),
                            'last_seen': latest.get('timestamp'),
                            'packet_count': len(data)
                        })
            except:
                pass
    # Sort by last_seen (most recent first)
    devices.sort(key=lambda x: x.get('last_seen', ''), reverse=True)
    return devices


@app.get("/viewer")
async def viewer():
    """Serve the CesiumJS viewer"""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/")
async def root():
    """Root endpoint to verify the server is running"""
    return {
        "status": "running",
        "service": "Stratosonde Ground Station",
        "timestamp": datetime.utcnow().isoformat(),
        "viewer_url": "/viewer",
        "api_docs": "/docs"
    }


def decode_gnss_detail(data_base64):
    """
    Decode GNSS detail packet from LoRaWAN Port 3 (Version 2 format)
    
    V2 Format: 4-byte header with separate constellation counts
    - Byte 0: Version (0x02)
    - Byte 1: GPS count
    - Byte 2: GLONASS count
    - Byte 3: BeiDou count
    - Satellites in fixed order: GPS → GLONASS → BeiDou
    - No PRN range checking needed
    
    Args:
        data_base64: base64 encoded payload string
        
    Returns:
        dict with decoded GNSS telemetry
    """
    import base64
    
    try:
        payload = base64.b64decode(data_base64)
    except:
        return None
        
    # V2 format requires 4-byte header minimum
    if len(payload) < 4:
        return None
        
    idx = 0
    result = {}
    
    # Header (4 bytes) - Version 2
    result['version'] = payload[idx]
    idx += 1
    result['gps_count'] = payload[idx]
    idx += 1
    result['glonass_count'] = payload[idx]
    idx += 1
    result['beidou_count'] = payload[idx]
    idx += 1
    
    # GPS satellites (sequential, no PRN checking)
    result['gps_satellites'] = []
    for i in range(result['gps_count']):
        if idx + 2 > len(payload):
            break
        sat = {
            'prn': payload[idx],
            'snr': payload[idx + 1]
        }
        result['gps_satellites'].append(sat)
        idx += 2
    
    # GLONASS satellites (sequential, no PRN checking)
    result['glonass_satellites'] = []
    for i in range(result['glonass_count']):
        if idx + 2 > len(payload):
            break
        sat = {
            'prn': payload[idx],
            'snr': payload[idx + 1]
        }
        result['glonass_satellites'].append(sat)
        idx += 2
    
    # BeiDou satellites (sequential, no PRN checking)
    result['beidou_satellites'] = []
    for i in range(result['beidou_count']):
        if idx + 2 > len(payload):
            break
        sat = {
            'prn': payload[idx],
            'snr': payload[idx + 1]
        }
        result['beidou_satellites'].append(sat)
        idx += 2
    
    # Speed data (12 bytes) - same as v1
    if idx + 12 <= len(payload):
        result['ground_speed_kmh'] = int.from_bytes(payload[idx:idx+2], 'big') * 0.1
        idx += 2
        
        result['vertical_speed_ms'] = int.from_bytes(payload[idx:idx+2], 'big', signed=True) * 0.01
        idx += 2
        
        result['speed_3d_kmh'] = int.from_bytes(payload[idx:idx+2], 'big') * 0.1
        idx += 2
        
        result['track_degrees'] = int.from_bytes(payload[idx:idx+2], 'big') * 0.1
        idx += 2
        
        result['hdop'] = int.from_bytes(payload[idx:idx+2], 'big') * 0.01
        idx += 2
    
    # Fix metadata (2 bytes) - same as v1
    if idx + 2 <= len(payload):
        result['fix_quality'] = payload[idx]
        result['satellites_used'] = payload[idx + 1]
    
    return result


def decode_port10_compact(data_base64):
    """
    Decode Port 10: Mission Heartbeat v2 (11 bytes, little-endian).

    Wire format per stratosonde/firmware docs/PayloadFormats.md +
    docs/LoRaWANApplicationProtocol.md (HEARTBEAT_FORMAT_VERSION 2, D2/D4, #33).
    All multibyte fields are LITTLE-ENDIAN (D9 - LE is wire truth; earlier docs
    that described big-endian were wrong).

    Byte layout (11 bytes):
      | Off | Field               | Type       | Scaling / meaning                 |
      |-----|---------------------|------------|-----------------------------------|
      | 0   | Timestamp (minutes) | uint16 LE  | minutes since epoch (wraps ~45.5d)|
      | 2   | Latitude            | int16 LE   | deg = value * 90  / 32767         |
      | 4   | Longitude           | int16 LE   | deg = value * 180 / 32767         |
      | 6   | Temperature         | uint8      | degC = (value - 64) * 2           |
      | 7   | Pressure+Humidity   | uint16 LE  | bits 0-10 pressure hPa (2047 inv);|
      |     |                     |            | bits 11-15 humidity 5%% (31 inv)  |
      | 9   | Battery             | uint8      | volts = value * 0.050             |
      | 10  | Status v2           | uint8      | bit flags (see masks below)       |

    v1 (legacy) shared port/length but is NOT decodable as v2 and never flew;
    v1 vs v2 is discriminated by deployment epoch + golden vectors.

    Args:
        data_base64: base64 encoded payload string

    Returns:
        dict with decoded telemetry, or None if the payload is not a valid
        11-byte v2 heartbeat.
    """
    import base64

    # Packed pressure/humidity word (bytes 7-8, LE) sentinels
    PRESS_HUM_PRESS_MASK = 0x07FF
    PRESS_HUM_PRESS_INVALID = 0x07FF          # 2047 = invalid pressure
    PRESS_HUM_HUM_INVALID = 31                # 31 (5%%-units) = invalid humidity

    # Status byte (byte 10) v2 bit masks
    STATUS_GPS_STALE_MASK = 0x01              # bit 0: GPS position last-known-good
    STATUS_TEMP_STALE_MASK = 0x02             # bit 1: temperature last-known-good
    STATUS_HUM_STALE_MASK = 0x04              # bit 2: humidity last-known-good
    STATUS_PRESS_STALE_MASK = 0x08            # bit 3: pressure last-known-good
    STATUS_TIME_GNSS_MASK = 0x10              # bit 4: RTC GNSS-disciplined this cycle
    STATUS_TS_WRAP_MASK = 0x20                # bit 5: timestamp_min has wrapped
    STATUS_MISSION_STATE_MASK = 0xC0          # bits 6-7: mission state
    MISSION_STATES = {0: "COMMISSIONING", 1: "ASCENT", 2: "FLOAT", 3: "RESERVED"}

    try:
        payload = base64.b64decode(data_base64)
    except Exception:
        return None

    if len(payload) != 11:
        print(f"Warning: Port 10 heartbeat v2 should be 11 bytes, got {len(payload)}")
        return None

    result = {}

    # Timestamp (uint16 LE, minutes since epoch)
    timestamp_minutes = int.from_bytes(payload[0:2], 'little')
    result['timestamp_minutes'] = timestamp_minutes
    result['decoded_time'] = f"{timestamp_minutes} minutes since epoch"

    # Latitude (int16 LE, full-range scale: deg = value * 90 / 32767)
    lat_raw = int.from_bytes(payload[2:4], 'little', signed=True)
    result['latitude'] = lat_raw * 90.0 / 32767.0

    # Longitude (int16 LE, full-range scale: deg = value * 180 / 32767)
    lon_raw = int.from_bytes(payload[4:6], 'little', signed=True)
    result['longitude'] = lon_raw * 180.0 / 32767.0

    # Temperature (uint8, degC = (value - 64) * 2)
    temp_raw = payload[6]
    result['temperature'] = (temp_raw - 64) * 2

    # Packed Pressure + Humidity (uint16 LE)
    press_hum = int.from_bytes(payload[7:9], 'little')
    pressure_raw = press_hum & PRESS_HUM_PRESS_MASK
    humidity_raw = (press_hum >> 11) & 0x1F
    if pressure_raw == PRESS_HUM_PRESS_INVALID:
        result['pressure'] = None
    else:
        result['pressure'] = pressure_raw            # 1 hPa units, 0-2046 hPa
    if humidity_raw == PRESS_HUM_HUM_INVALID:
        result['humidity'] = None
    else:
        result['humidity'] = min(humidity_raw * 5, 100)   # 5%%-units -> %%

    # Battery (uint8, volts = value * 0.050)
    result['battery_voltage'] = payload[9] * 0.050

    # Status byte v2 (byte 10)
    status = payload[10]
    result['status_byte'] = status
    result['gps_stale'] = bool(status & STATUS_GPS_STALE_MASK)
    result['temp_stale'] = bool(status & STATUS_TEMP_STALE_MASK)
    result['humidity_stale'] = bool(status & STATUS_HUM_STALE_MASK)
    result['pressure_stale'] = bool(status & STATUS_PRESS_STALE_MASK)
    result['time_gnss_disciplined'] = bool(status & STATUS_TIME_GNSS_MASK)
    result['timestamp_wrapped'] = bool(status & STATUS_TS_WRAP_MASK)
    mission_state = (status & STATUS_MISSION_STATE_MASK) >> 6
    result['mission_state'] = mission_state
    result['mission_state_name'] = MISSION_STATES.get(mission_state, "UNKNOWN")

    # Altitude is NOT transmitted - calculate from pressure + temperature
    # using the barometric formula: h = 44330 * (1 - (P/P0)^0.1903)
    if result['pressure']:
        P0 = 1013.25  # Sea level standard pressure in hPa
        result['altitude_calculated'] = 44330 * (1 - (result['pressure'] / P0) ** 0.1903)
    else:
        result['altitude_calculated'] = None

    return result


def decode_port11_bulk(data_base64):
    """
    Decode Port 11: Bulk Binary Packet (up to 222 bytes)
    
    High-resolution historical data transfer at SF7:
    - Header: 6 bytes (packet type, record count, flash address)
    - Records: Up to 6 × 32-byte high-resolution records
    - Metadata: 24 bytes (voltage trend, mode history, CRC32)
    
    Each 32-byte record includes:
    - Timestamp: uint32 BE (4 bytes) - second resolution
    - Latitude: int32 BE (4 bytes) - full precision (~1cm)
    - Longitude: int32 BE (4 bytes) - full precision (~1cm)
    - Altitude: int16 BE (2 bytes) - 1m resolution
    - Temperature: int16 BE (2 bytes) - 0.1°C resolution
    - Pressure: uint16 BE (2 bytes) - 0.1 hPa resolution
    - Humidity: uint8 (1 byte) - 1% resolution
    - Battery: uint16 BE (2 bytes) - 1 mV resolution
    - Solar: uint16 BE (2 bytes) - 1 mV resolution
    - Voltage Slope: int16 BE (2 bytes) - 1 mV/h resolution
    - Satellites: uint8 (1 byte)
    - HDOP: uint8 (1 byte) - 0.1 resolution
    - Power Mode: uint8 (1 byte)
    - CRC16: uint16 BE (2 bytes)
    
    Args:
        data_base64: base64 encoded payload string
        
    Returns:
        dict with decoded bulk telemetry
    """
    import base64
    
    try:
        payload = base64.b64decode(data_base64)
    except:
        return None
    
    if len(payload) < 6:
        print(f"Warning: Port 11 packet too short, got {len(payload)} bytes")
        return None
    
    idx = 0
    result = {}
    
    # Header (6 bytes)
    result['packet_type'] = payload[idx]
    idx += 1
    result['record_count'] = payload[idx]
    idx += 1
    result['flash_address'] = int.from_bytes(payload[idx:idx+4], 'big')
    idx += 4
    
    # Validate record count
    if result['record_count'] > 6:
        print(f"Warning: Invalid record count {result['record_count']}, expected max 6")
        return None
    
    # Decode records (32 bytes each)
    result['records'] = []
    for i in range(result['record_count']):
        if idx + 32 > len(payload):
            print(f"Warning: Not enough data for record {i+1}")
            break
        
        record = {}
        
        # Timestamp (4 bytes BE, second resolution)
        record['timestamp_seconds'] = int.from_bytes(payload[idx:idx+4], 'big')
        idx += 4
        
        # Latitude (4 bytes BE, signed, full precision)
        # Scaling: divide by 10000000 to get degrees (~1cm resolution)
        lat_raw = int.from_bytes(payload[idx:idx+4], 'big', signed=True)
        idx += 4
        record['latitude'] = lat_raw / 10000000.0
        
        # Longitude (4 bytes BE, signed, full precision)
        # Scaling: divide by 10000000 to get degrees (~1cm resolution)
        lon_raw = int.from_bytes(payload[idx:idx+4], 'big', signed=True)
        idx += 4
        record['longitude'] = lon_raw / 10000000.0
        
        # Altitude (2 bytes BE, signed, 1m resolution)
        # Direct meters value, offset by -1000m (range: -1000m to +64535m)
        alt_raw = int.from_bytes(payload[idx:idx+2], 'big', signed=True)
        idx += 2
        record['altitude'] = alt_raw + 1000
        
        # Temperature (2 bytes BE, signed, 0.1°C resolution)
        # Scaling: divide by 10, offset by -50°C
        temp_raw = int.from_bytes(payload[idx:idx+2], 'big', signed=True)
        idx += 2
        record['temperature'] = (temp_raw / 10.0) - 50
        
        # Pressure (2 bytes BE, unsigned, 0.1 hPa resolution)
        # Scaling: divide by 10, offset by 300 hPa
        pressure_raw = int.from_bytes(payload[idx:idx+2], 'big')
        idx += 2
        record['pressure'] = (pressure_raw / 10.0) + 300
        
        # Humidity (1 byte, unsigned, 1% resolution)
        record['humidity'] = payload[idx]
        idx += 1
        
        # Battery voltage (2 bytes BE, unsigned, 1 mV resolution)
        battery_raw = int.from_bytes(payload[idx:idx+2], 'big')
        idx += 2
        record['battery_voltage'] = battery_raw / 1000.0  # Convert to volts
        
        # Solar voltage (2 bytes BE, unsigned, 1 mV resolution)
        solar_raw = int.from_bytes(payload[idx:idx+2], 'big')
        idx += 2
        record['solar_voltage'] = solar_raw / 1000.0  # Convert to volts
        
        # Voltage slope (2 bytes BE, signed, 1 mV/h resolution)
        voltage_slope_raw = int.from_bytes(payload[idx:idx+2], 'big', signed=True)
        idx += 2
        record['voltage_slope'] = voltage_slope_raw  # mV/h
        
        # Satellites (1 byte)
        record['satellites'] = payload[idx]
        idx += 1
        
        # HDOP (1 byte, 0.1 resolution)
        hdop_raw = payload[idx]
        idx += 1
        record['hdop'] = hdop_raw / 10.0
        
        # Power mode (1 byte)
        # 0=NORMAL, 1=CONSERVATIVE, 2=REDUCED, 3=RECOVERY, 4=SURVIVAL
        record['power_mode'] = payload[idx]
        mode_names = {0: "NORMAL", 1: "CONSERVATIVE", 2: "REDUCED", 3: "RECOVERY", 4: "SURVIVAL"}
        record['power_mode_name'] = mode_names.get(record['power_mode'], f"UNKNOWN({record['power_mode']})")
        idx += 1
        
        # CRC16 (2 bytes BE)
        record['crc16'] = int.from_bytes(payload[idx:idx+2], 'big')
        idx += 2
        
        result['records'].append(record)
    
    # Metadata (24 bytes) - if present
    if idx + 24 <= len(payload):
        result['metadata'] = {}
        
        # Voltage trend data (12 bytes) - placeholder for future use
        result['metadata']['voltage_trend_data'] = payload[idx:idx+12].hex()
        idx += 12
        
        # Mode history (8 bytes) - placeholder for future use
        result['metadata']['mode_history'] = payload[idx:idx+8].hex()
        idx += 8
        
        # CRC32 (4 bytes BE)
        result['metadata']['crc32'] = int.from_bytes(payload[idx:idx+4], 'big')
        idx += 4
    
    return result


@app.post("/")
async def chirpstack_webhook(request: Request):
    """
    Receive webhook calls from ChirpStack with LoRaWAN sensor data
    """
    try:
        payload = await request.json()
        timestamp = datetime.utcnow().isoformat()
        
        # Ignore error/log events from ChirpStack
        if "level" in payload and payload["level"] == "ERROR":
            print(f"\n[{timestamp}] Ignoring ChirpStack error log event")
            return {"status": "ignored", "message": "Error log event"}
        
        # Log the received data
        print(f"\n{'='*60}")
        print(f"[{timestamp}] Webhook received from ChirpStack")
        print(f"{'='*60}")
        
        # Print raw payload for debugging
        print("RAW PAYLOAD:")
        print(json.dumps(payload, indent=2))
        print(f"{'='*60}")
        
        # Extract device info
        device_info = payload.get("deviceInfo", {})
        device_name = device_info.get("deviceName", "unknown")
        dev_eui = device_info.get("devEui", "unknown")
        
        print(f"Device Name: {device_name}")
        print(f"Device EUI: {dev_eui}")
        
        # Extract sensor data
        sensor_data = payload.get("object", {})
        
        # Get GPS location from sensor
        gps_data = sensor_data.get("gpsLocation", {}).get("4", {})
        latitude = gps_data.get("latitude", 0.0)
        longitude = gps_data.get("longitude", 0.0)
        altitude = gps_data.get("altitude", 0.0)
        
        # If GPS is zero, use gateway location (first gateway with best signal)
        if latitude == 0.0 and longitude == 0.0:
            rx_info = payload.get("rxInfo", [])
            if rx_info:
                # Sort by RSSI (best signal first)
                rx_info_sorted = sorted(rx_info, key=lambda x: x.get("rssi", -999), reverse=True)
                best_gateway = rx_info_sorted[0]
                metadata = best_gateway.get("metadata", {})
                latitude = float(metadata.get("gateway_lat", 0.0))
                longitude = float(metadata.get("gateway_long", 0.0))
                gateway_name = metadata.get("gateway_name", "unknown")
                print(f"Using gateway location: {gateway_name}")
        
        # Extract environmental data
        temperature = sensor_data.get("temperatureSensor", {}).get("1", None)
        humidity = sensor_data.get("humiditySensor", {}).get("2", None)
        pressure = sensor_data.get("barometer", {}).get("3", None)
        
        # Extract additional analog channels
        satellites = sensor_data.get("analogInput", {}).get("5", None)  # GPS satellite count
        battery_voltage = sensor_data.get("analogInput", {}).get("6", None)  # Battery voltage
        power_rail_voltage = sensor_data.get("analogInput", {}).get("7", None)  # Regulator voltage (3.3V rail/VDDA)
        hdop = sensor_data.get("analogInput", {}).get("8", None)  # HDOP (Horizontal Dilution of Precision)
        ttf_seconds = sensor_data.get("analogInput", {}).get("9", None)  # Time to Fix in seconds
        solar_panel_voltage = sensor_data.get("analogInput", {}).get("10", None)  # Solar Panel Voltage
        voltage_slope = sensor_data.get("analogInput", {}).get("11", None)  # mV/h ÷ 10 (charge/discharge rate)
        time_to_target = sensor_data.get("analogInput", {}).get("12", None)  # Hours (+charging, -depletion)
        # Channel 13 is skipped/unused
        operating_mode = sensor_data.get("analogInput", {}).get("14", None)  # 0=NORMAL, 1=CONSERVATIVE, 2=REDUCED, 3=RECOVERY, 4=SURVIVAL
        
        print(f"Location: {latitude}, {longitude}, {altitude}m")
        print(f"Temperature: {temperature}°C, Humidity: {humidity}%, Pressure: {pressure} hPa")
        print(f"Satellites: {satellites}, Battery: {battery_voltage}V, Regulator: {power_rail_voltage}V, Solar: {solar_panel_voltage}V")
        print(f"HDOP: {hdop}, TTF: {ttf_seconds}s")
        if voltage_slope is not None:
            # Voltage slope is sent divided by 10, so multiply back to get mV/h
            actual_voltage_slope = voltage_slope * 10
            print(f"Voltage Slope: {actual_voltage_slope:.1f} mV/h, Time to Target: {time_to_target:.1f}h")
        if operating_mode is not None:
            mode_names = {0: "NORMAL", 1: "CONSERVATIVE", 2: "REDUCED", 3: "RECOVERY", 4: "SURVIVAL"}
            mode_str = mode_names.get(int(operating_mode), f"UNKNOWN({operating_mode})")
            print(f"Operating Mode: {mode_str}")
        
        # Extract LoRaWAN parameters
        dev_addr = payload.get("devAddr", None)
        dr = payload.get("dr", None)
        adr = payload.get("adr", False)
        f_port = payload.get("fPort", None)
        confirmed = payload.get("confirmed", False)
        
        # Extract transmission info (needed for Port 11)
        tx_info = payload.get("txInfo", {})
        frequency = tx_info.get("frequency", None)
        modulation = tx_info.get("modulation", {}).get("lora", {})
        spreading_factor = modulation.get("spreadingFactor", None)
        bandwidth = modulation.get("bandwidth", None)
        code_rate = modulation.get("codeRate", None)
        
        # Extract device info details (needed for Port 11)
        application_name = device_info.get("applicationName", None)
        device_profile_name = device_info.get("deviceProfileName", None)
        tenant_name = device_info.get("tenantName", None)
        
        # Process all receiving gateways (needed before Port 3 processing)
        rx_info = payload.get("rxInfo", [])
        gateways = []
        for gw in rx_info:
            gw_metadata = gw.get("metadata", {})
            gw_lat = gw_metadata.get("gateway_lat", None)
            gw_lon = gw_metadata.get("gateway_long", None)
            
            # Calculate distance if coordinates are available
            distance = None
            if gw_lat and gw_lon and latitude != 0 and longitude != 0:
                try:
                    # Simple haversine distance calculation
                    from math import radians, sin, cos, sqrt, atan2
                    R = 6371000  # Earth radius in meters
                    lat1, lon1 = radians(float(gw_lat)), radians(float(gw_lon))
                    lat2, lon2 = radians(latitude), radians(longitude)
                    dlat = lat2 - lat1
                    dlon = lon2 - lon1
                    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                    c = 2 * atan2(sqrt(a), sqrt(1-a))
                    distance = R * c  # Distance in meters
                except:
                    distance = None
            
            gw_info = {
                "gateway_id": gw.get("gatewayId", None),
                "gateway_name": gw_metadata.get("gateway_name", None),
                "rssi": gw.get("rssi", None),
                "snr": gw.get("snr", None),
                "latitude": float(gw_lat) if gw_lat else None,
                "longitude": float(gw_lon) if gw_lon else None,
                "distance": distance,
                "network": gw_metadata.get("network", None),
                "region": gw_metadata.get("regi", None),
                "h3_index": gw_metadata.get("gateway_h3index", None)
            }
            gateways.append(gw_info)
        
        # Decode binary packets based on port number
        gnss_detail = None
        port10_data = None
        port11_data = None
        
        # Port 10: Compact Binary Packet
        if f_port == 10:
            data_base64 = payload.get("data", None)
            if data_base64:
                port10_data = decode_port10_compact(data_base64)
                if port10_data:
                    alt = port10_data['altitude_calculated']
                    press = port10_data['pressure']
                    hum = port10_data['humidity']
                    print("\n--- PORT 10 HEARTBEAT v2 ---")
                    print(f"Timestamp: {port10_data['decoded_time']} ({port10_data['timestamp_minutes']} min)")
                    print(f"Location: {port10_data['latitude']:.4f}°, {port10_data['longitude']:.4f}°")
                    print(f"Altitude (calculated): {alt:.1f}m" if alt is not None else "Altitude (calculated): N/A (pressure invalid)")
                    print(f"Temperature: {port10_data['temperature']}°C")
                    print(f"Pressure: {press} hPa" if press is not None else "Pressure: N/A (invalid sentinel)")
                    print(f"Humidity: {hum}%" if hum is not None else "Humidity: N/A (invalid sentinel)")
                    print(f"Battery: {port10_data['battery_voltage']:.2f}V")
                    print(f"Mission state: {port10_data['mission_state_name']} | "
                          f"time GNSS-disciplined: {port10_data['time_gnss_disciplined']} | "
                          f"stale(gps/t/h/p): {port10_data['gps_stale']}/{port10_data['temp_stale']}/"
                          f"{port10_data['humidity_stale']}/{port10_data['pressure_stale']}")
                    print("-------------------------------\n")
                    
                    # Override extracted values with decoded binary data
                    latitude = port10_data['latitude']
                    longitude = port10_data['longitude']
                    altitude = port10_data['altitude_calculated']
                    temperature = port10_data['temperature']
                    pressure = port10_data['pressure']
                    humidity = port10_data['humidity']
                    battery_voltage = port10_data['battery_voltage']
        
        # Port 11: Bulk Binary Packet
        elif f_port == 11:
            data_base64 = payload.get("data", None)
            if data_base64:
                port11_data = decode_port11_bulk(data_base64)
                if port11_data:
                    print("\n--- PORT 11 BULK PACKET ---")
                    print(f"Packet Type: {port11_data['packet_type']}")
                    print(f"Record Count: {port11_data['record_count']}")
                    print(f"Flash Address: 0x{port11_data['flash_address']:08X}")
                    print(f"\nRecords:")
                    
                    # Process each record in the bulk packet
                    telemetry_data = load_telemetry(dev_eui)
                    records_added = 0
                    
                    for idx, record in enumerate(port11_data['records']):
                        print(f"\n  Record {idx+1}:")
                        print(f"    Timestamp: {record['timestamp_seconds']}s since epoch")
                        print(f"    Location: {record['latitude']:.7f}°, {record['longitude']:.7f}°")
                        print(f"    Altitude: {record['altitude']}m")
                        print(f"    Temperature: {record['temperature']:.1f}°C")
                        print(f"    Pressure: {record['pressure']:.1f} hPa")
                        print(f"    Humidity: {record['humidity']}%")
                        print(f"    Battery: {record['battery_voltage']:.3f}V")
                        print(f"    Solar: {record['solar_voltage']:.3f}V")
                        print(f"    Voltage Slope: {record['voltage_slope']} mV/h")
                        print(f"    Satellites: {record['satellites']}")
                        print(f"    HDOP: {record['hdop']:.1f}")
                        print(f"    Power Mode: {record['power_mode_name']}")
                        print(f"    CRC16: 0x{record['crc16']:04X}")
                        
                        # Create individual telemetry point for each record
                        record_point = {
                            "timestamp": payload.get("time", timestamp),  # Use packet receive time as base
                            "device_timestamp_seconds": record['timestamp_seconds'],
                            "device_name": device_name,
                            "dev_eui": dev_eui,
                            "dev_addr": dev_addr,
                            "application_name": application_name,
                            "device_profile_name": device_profile_name,
                            "tenant_name": tenant_name,
                            "latitude": record['latitude'],
                            "longitude": record['longitude'],
                            "altitude": record['altitude'],
                            "temperature": record['temperature'],
                            "humidity": record['humidity'],
                            "pressure": record['pressure'],
                            "satellites": record['satellites'],
                            "battery_voltage": record['battery_voltage'],
                            "solar_panel_voltage": record['solar_voltage'],
                            "voltage_slope": record['voltage_slope'] / 10.0,  # Convert to consistent format (÷10)
                            "operating_mode": record['power_mode'],
                            "hdop": record['hdop'],
                            "rssi": best_gateway.get("rssi", None),
                            "snr": best_gateway.get("snr", None),
                            "fcnt": payload.get("fCnt", None),
                            "dr": dr,
                            "adr": adr,
                            "f_port": f_port,
                            "confirmed": confirmed,
                            "frequency": frequency,
                            "spreading_factor": spreading_factor,
                            "bandwidth": bandwidth,
                            "code_rate": code_rate,
                            "gateways": gateways,
                            "bulk_record_index": idx,
                            "bulk_flash_address": port11_data['flash_address'],
                            "crc16": record['crc16']
                        }
                        
                        telemetry_data.append(record_point)
                        records_added += 1
                    
                    # Add metadata if present
                    if 'metadata' in port11_data:
                        print(f"\n  Metadata:")
                        print(f"    Voltage Trend: {port11_data['metadata']['voltage_trend_data']}")
                        print(f"    Mode History: {port11_data['metadata']['mode_history']}")
                        print(f"    CRC32: 0x{port11_data['metadata']['crc32']:08X}")
                    
                    print("---------------------------\n")
                    
                    # Keep only last 10000 points
                    if len(telemetry_data) > 10000:
                        telemetry_data = telemetry_data[-10000:]
                    
                    save_telemetry(dev_eui, telemetry_data)
                    data_file = get_data_file(dev_eui)
                    print(f"Saved {records_added} bulk records to {data_file} (Total points: {len(telemetry_data)})")
                    print(f"{'='*60}\n")
                    
                    return {
                        "status": "success",
                        "message": f"Bulk data received: {records_added} records saved",
                        "timestamp": timestamp,
                        "device": device_name,
                        "dev_eui": dev_eui,
                        "records_saved": records_added
                    }
        
        # Decode GNSS detail packet if on Port 3
        elif f_port == 3:
            data_base64 = payload.get("data", None)
            if data_base64:
                gnss_detail = decode_gnss_detail(data_base64)
                if gnss_detail:
                    print("\n--- GNSS DETAIL (Port 3) ---")
                    print(f"Packet Version: {gnss_detail.get('version', '?')}")
                    print(f"GPS satellites: {len(gnss_detail['gps_satellites'])}")
                    for sat in gnss_detail['gps_satellites']:
                        print(f"  GPS PRN {sat['prn']}: SNR {sat['snr']} dBHz")
                    if gnss_detail['glonass_satellites']:
                        print(f"GLONASS satellites: {len(gnss_detail['glonass_satellites'])}")
                        for sat in gnss_detail['glonass_satellites']:
                            print(f"  GLONASS PRN {sat['prn']}: SNR {sat['snr']} dBHz")
                    if gnss_detail['beidou_satellites']:
                        print(f"BeiDou satellites: {len(gnss_detail['beidou_satellites'])}")
                        for sat in gnss_detail['beidou_satellites']:
                            print(f"  BeiDou PRN {sat['prn']}: SNR {sat['snr']} dBHz")
                    if 'ground_speed_kmh' in gnss_detail:
                        print(f"Ground speed: {gnss_detail['ground_speed_kmh']:.1f} km/h")
                        print(f"Vertical speed: {gnss_detail['vertical_speed_ms']:.2f} m/s")
                        print(f"3D speed: {gnss_detail['speed_3d_kmh']:.1f} km/h")
                        print(f"Track: {gnss_detail['track_degrees']:.1f}°")
                    if 'hdop' in gnss_detail:
                        print(f"HDOP: {gnss_detail['hdop']:.2f}")
                    if 'fix_quality' in gnss_detail:
                        fix_types = {0: 'Invalid', 1: 'GPS', 2: 'DGPS'}
                        fix_str = fix_types.get(gnss_detail['fix_quality'], 'Unknown')
                        print(f"Fix Quality: {fix_str} ({gnss_detail.get('satellites_used', 0)} sats used)")
                    print("----------------------------\n")
                    
                    # Merge with most recent Port 2 packet instead of creating new entry
                    telemetry_data = load_telemetry(dev_eui)
                    if telemetry_data:
                        # Update the most recent packet with GNSS detail
                        telemetry_data[-1]['gnss_detail'] = gnss_detail
                        
                        # Also merge gateways from Port 3 (might be different gateways)
                        existing_gateways = telemetry_data[-1].get('gateways', [])
                        existing_gw_ids = {gw['gateway_id'] for gw in existing_gateways if gw.get('gateway_id')}
                        
                        # Add any new gateways from Port 3 that aren't already in the list
                        for new_gw in gateways:
                            if new_gw.get('gateway_id') not in existing_gw_ids:
                                existing_gateways.append(new_gw)
                                print(f"  Added gateway from Port 3: {new_gw.get('gateway_name', 'Unknown')}")
                        
                        # Re-sort by RSSI
                        telemetry_data[-1]['gateways'] = sorted(existing_gateways, key=lambda x: x.get('rssi', -999), reverse=True)
                        
                        save_telemetry(telemetry_data)
                        print(f"Merged Port 3 data with most recent packet (Total points: {len(telemetry_data)})")
                        print(f"  Total gateways: {len(telemetry_data[-1]['gateways'])}")
                        print(f"{'='*60}\n")
                        
                        return {
                            "status": "success",
                            "message": "GNSS detail data merged with latest telemetry",
                            "timestamp": timestamp,
                            "device": device_name,
                            "dev_eui": dev_eui
                        }
                    else:
                        print("Warning: No existing telemetry to merge Port 3 data with - discarding")
                        print(f"{'='*60}\n")
                        return {
                            "status": "warning",
                            "message": "No existing telemetry to merge Port 3 data with",
                            "timestamp": timestamp,
                            "device": device_name,
                            "dev_eui": dev_eui
                        }
        
        # Get best gateway (highest RSSI)
        best_gateway = gateways[0] if gateways else {}
        
        # Create telemetry point
        telemetry_point = {
            "timestamp": payload.get("time", timestamp),
            "device_name": device_name,
            "dev_eui": dev_eui,
            "dev_addr": dev_addr,
            "application_name": application_name,
            "device_profile_name": device_profile_name,
            "tenant_name": tenant_name,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "temperature": temperature,
            "humidity": humidity,
            "pressure": pressure,
            "satellites": satellites,
            "battery_voltage": battery_voltage,
            "power_rail_voltage": power_rail_voltage,
            "solar_panel_voltage": solar_panel_voltage,
            "voltage_slope": voltage_slope,  # mV/h ÷ 10 as sent by device
            "time_to_target": time_to_target,  # Hours: +charging, -depletion, 0=stable
            "operating_mode": operating_mode,  # 0=NORMAL, 1=CONSERVATIVE, 2=REDUCED, 3=RECOVERY, 4=SURVIVAL
            "hdop": hdop,
            "ttf_seconds": ttf_seconds,
            "rssi": best_gateway.get("rssi", None),
            "snr": best_gateway.get("snr", None),
            "fcnt": payload.get("fCnt", None),
            "dr": dr,
            "adr": adr,
            "f_port": f_port,
            "confirmed": confirmed,
            "frequency": frequency,
            "spreading_factor": spreading_factor,
            "bandwidth": bandwidth,
            "code_rate": code_rate,
            "gateways": gateways,
            "gnss_detail": gnss_detail
        }
        
        # Only save if NOT Port 3 (Port 3 packets merge with existing data and return early above)
        if f_port != 3:
            # Load existing data and append
            telemetry_data = load_telemetry(dev_eui)
            telemetry_data.append(telemetry_point)
            
            # Keep only last 10000 points to avoid file getting too large
            if len(telemetry_data) > 10000:
                telemetry_data = telemetry_data[-10000:]
            
            save_telemetry(dev_eui, telemetry_data)
            
            data_file = get_data_file(dev_eui)
            print(f"Saved to {data_file} (Total points: {len(telemetry_data)})")
            print(f"{'='*60}\n")
        
        return {
            "status": "success",
            "message": "Telemetry data received and saved",
            "timestamp": timestamp,
            "device": device_name,
            "dev_eui": dev_eui,
            "location": f"{latitude}, {longitude}"
        }
        
    except Exception as e:
        print(f"Error processing webhook: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@app.get("/api/devices")
async def get_devices():
    """
    Get list of all available devices with telemetry data
    """
    return get_available_devices()


@app.get("/api/telemetry")
async def get_telemetry(dev_eui: str, limit: int = 1000):
    """
    Get telemetry data for a specific device
    """
    telemetry_data = load_telemetry(dev_eui)
    # Return most recent data first
    return telemetry_data[-limit:]


@app.get("/api/latest")
async def get_latest(dev_eui: str):
    """
    Get the most recent telemetry point for a specific device
    """
    telemetry_data = load_telemetry(dev_eui)
    if telemetry_data:
        return telemetry_data[-1]
    return {"message": "No data available"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    devices = get_available_devices()
    total_points = sum(d['packet_count'] for d in devices)
    return {
        "status": "healthy",
        "devices": len(devices),
        "total_data_points": total_points
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
