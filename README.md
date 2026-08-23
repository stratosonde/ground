# Radiosonde Ground Station 🎈

A real-time LoRaWAN radiosonde tracking system with CesiumJS 3D visualization. Receives telemetry data from ChirpStack webhooks and displays flight paths with environmental data.

## Features

- 📡 **Real-time webhook receiver** for ChirpStack LoRaWAN network
- 🗄️ **JSON-based telemetry storage** (up to 10,000 data points)
- 🌍 **3D CesiumJS visualization** with live flight path tracking
- 📊 **Environmental data logging** (temperature, humidity, pressure)
- 📍 **Smart location fallback** - Uses gateway location when sensor GPS is unavailable
- 🔌 **REST API** for telemetry access
- ⚡ **Auto-refresh** - Updates every 5 seconds

## Quick Start

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Run the Server

```bash
python3 ground_station.py
```

The server will start on `http://0.0.0.0:8005`

### 3. View the Visualization

Open your browser to:
```
http://localhost:8005/static/index.html
```

### 4. Configure ChirpStack

Set your ChirpStack application webhook URL to:
```
http://your-server-address:8005/
```

## API Endpoints

### Webhook
- `POST /` - Receives ChirpStack webhook calls (JSON payload)

### Telemetry Data
- `GET /api/telemetry?limit=1000` - Get recent telemetry points
- `GET /api/latest` - Get the most recent telemetry point
- `GET /health` - Health check with data point count

### Visualization
- `GET /static/index.html` - CesiumJS 3D tracker interface

## Data Format

Each telemetry point is stored as:

```json
{
  "timestamp": "2025-11-18T00:55:35.481+00:00",
  "device_name": "strato2",
  "dev_eui": "6081f953250e672c",
  "latitude": 51.155173,
  "longitude": -114.070677,
  "altitude": 0.0,
  "temperature": 17.0,
  "humidity": 50.0,
  "pressure": 1000.0,
  "rssi": -117,
  "snr": -5.2,
  "fcnt": 1156
}
```

## Smart GPS Fallback

When the radiosonde GPS reports `0.0, 0.0` (not yet locked or unavailable):
- Automatically uses the location of the gateway with the strongest signal (highest RSSI)
- This ensures you can still see the approximate launch location on the map
- Once the radiosonde GPS locks, it will switch to actual sensor coordinates

## CesiumJS Visualization

The 3D viewer displays:
- **Flight path** - Cyan glowing line showing the radiosonde trajectory
- **Current position** - Red marker with device label
- **Real-time telemetry** - Info panel with latest sensor readings
- **Interactive 3D globe** - Full terrain support with Cesium Ion

### Controls
- **Left mouse drag** - Rotate view
- **Right mouse drag** - Pan
- **Mouse wheel** - Zoom in/out
- **Middle mouse drag** - Tilt view
- Click on the radiosonde marker for detailed information

## File Structure

```
ground/
├── ground_station.py       # Main FastAPI application
├── requirements.txt        # Python dependencies
├── telemetry_data.json    # Stored telemetry (auto-created)
├── static/
│   └── index.html         # CesiumJS visualization
└── README.md
```

## Testing

Test the webhook with curl:

```bash
curl -X POST http://localhost:8005/ \
  -H "Content-Type: application/json" \
  -d '{
    "time": "2025-11-18T00:00:00+00:00",
    "deviceInfo": {
      "deviceName": "test-radiosonde",
      "devEui": "0000000000000001"
    },
    "object": {
      "gpsLocation": {"4": {"latitude": 51.0, "longitude": -114.0, "altitude": 1000}},
      "temperatureSensor": {"1": 15.5},
      "humiditySensor": {"2": 65.0},
      "barometer": {"3": 950.0}
    },
    "rxInfo": [{
      "rssi": -110,
      "snr": 5.0,
      "metadata": {
        "gateway_name": "test-gateway",
        "gateway_lat": "51.0",
        "gateway_long": "-114.0"
      }
    }]
  }'
```

## Cesium Ion Token

The default Cesium Ion token is included for testing. For production use, get a free token at:
https://cesium.com/ion/signup

Replace the token in `static/index.html`:
```javascript
Cesium.Ion.defaultAccessToken = 'YOUR_TOKEN_HERE';
```

## How It Works

1. **ChirpStack** sends uplink data via webhook to your ground station
2. **ground_station.py** receives the POST request and extracts:
   - Device information (name, EUI)
   - GPS coordinates (or gateway location as fallback)
   - Environmental sensors (temperature, humidity, pressure)
   - Signal quality (RSSI, SNR)
3. Data is appended to **telemetry_data.json**
4. **CesiumJS frontend** polls `/api/telemetry` every 5 seconds
5. Flight path and current position update in real-time on the 3D globe

## NASA-Style Data Architecture (Future)

This simple JSON-based system is perfect for getting started. For production deployments with multiple radiosondes and long-term data retention, consider upgrading to:

- **PostgreSQL with TimescaleDB** extension for time-series optimization
- **InfluxDB** for high-frequency telemetry
- **Grafana** for additional dashboard views
- **WebSocket** connections for true real-time updates

## License

Open source - use for your radiosonde tracking needs!
