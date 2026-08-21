# Comprehensive Guide: Real-Time eTransit Punjab Data Ingestion & Unofficial GTFS Pipeline

This document details the complete process for safely intercepting real-time mass transit telemetry from the **eTransit Punjab** ecosystem and structuring it into industry-standard **GTFS (General Transit Feed Specification)** formats for local development.

---

## Section 1: Traffic Routing via Android Studio & Fiddler Classic

### Prerequisites & Software
* **Host Machine:** Windows 10/11 with Administrator privileges.
* **Fiddler Classic:** Download and install.
* **Android Studio:** Download and install.
* **Target App:** eTransit Punjab (`pk.pitb.punjab.masstransit.punjab_masstransit_authority`).

### 1.1 Fiddler Classic Setup
1. Launch Fiddler Classic.
2. Navigate to **Tools** > **Options** > **HTTPS**.
3. Check **Capture HTTPS Connects** and **Decrypt HTTPS Traffic**.
4. Trust the Fiddler Root Certificate when prompted by Windows.
5. Go to the **Connections** tab.
6. Check **Allow remote computers to connect**. Note the *Fiddler listens on port* value (Default: `8888`).
7. Open Windows Command Prompt, run `ipconfig`, and find your local IPv4 address (e.g., `192.168.1.50`).
8. Restart Fiddler Classic to apply changes.

### 1.2 Android Studio Emulator Setup
1. Open Android Studio and launch the **Virtual Device Manager (AVD)**.
2. Click **Create Device**. Choose a device definition that includes the **Google Play Store icon** (e.g., Pixel 4).
3. Select an **older Android version System Image**: **Android 7.0 (API 24)** or **Android 8.0 (API 26)**. 
   * *Critical Note: Android versions API 24/26 natively trust user-installed certificates for HTTPS decryption without requiring root access or APK modification.*
4. Download the system image, complete the wizard, and launch the emulator.

### 1.3 Network Interception Configuration
1. Inside the running emulator, go to **Settings** > **Network & Internet** > **Wi-Fi**.
2. Long-press the connected network name (`AndroidWifi`) and select **Modify**.
3. Change **Proxy** from *None* to *Manual*.
4. **Proxy hostname:** Enter your Windows host machine IPv4 address (e.g., `192.168.1.50`).
5. **Proxy port:** Enter Fiddler’s port (e.g., `8888`). Save changes.
6. Open the Google Chrome browser inside the emulator and navigate to: `http://ipv4.fiddler`
7. Click the **FiddlerRoot certificate** link to download it.
8. Name the certificate (e.g., "Fiddler Proxy") and install it to the device credential storage.
9. Open the Google Play Store, log in, download the **eTransit Punjab app**, and open it. Watch Fiddler capture JSON packets in real time.

---

## Section 2: Building Static GTFS (Schedules & Stops)

The eTransit app makes initialization requests to populate its UI maps, routes, and station lists. These responses can be parsed into a static GTFS layout (`.txt` files zipped together).

### 2.1 Identifying Key API Endpoints
Isolate the following payloads inside Fiddler's Inspector tab by sorting by Content-Type (`application/json`):
* **Stops / Stations Endpoint:** Returns an array containing station names, IDs, latitudes, and longitudes.
* **Routes / Shapes Endpoint:** Returns specific route designations (e.g., Metro Orange Line, Speedo Route 3) along with polyline points.

### 2.2 Python Script: Raw JSON to Static GTFS Generator
Run this script locally to process the captured JSON array into standard GTFS `stops.txt` and `routes.txt` configurations.

```python
import json
import csv

# Mock structural data captured from proxy logs
raw_stops_payload = """
[
    {"station_id": 101, "name": "Shahdara Metro Station", "lat": 31.6212, "lon": 74.2985},
    {"station_id": 102, "name": "MAO College Station", "lat": 31.5583, "lon": 74.3094}
]
"""

def generate_static_gtfs():
    stops_data = json.loads(raw_stops_payload)
    
    # Generate stops.txt
    with open('stops.txt', mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['stop_id', 'stop_name', 'stop_lat', 'stop_lon', 'location_type'])
        for item in stops_data:
            writer.writerow([item['station_id'], item['name'], item['lat'], item['lon'], 0])
            
    print("[SUCCESS] Static GTFS dependencies generated: stops.txt")

if __name__ == "__main__":
    generate_static_gtfs()
```

---

## Section 3: Building GTFS Realtime Feed (Live Bus Positions)

GTFS Realtime (GTFS-rt) maps real-time vehicular data onto existing static entities. This section transforms live telemetry from PITB’s API string into a standardized Protocol Buffer (`.pb`) data format.

### 3.1 Tracking Telemetry Logic
The eTransit application polls live vehicle positions every few seconds. Fiddler will show a repeating request hitting a telemetry endpoint. The JSON schema generally structures data as follows:
```json
{
  "vehicle_id": "M-4012",
  "route_id": 12,
  "latitude": 31.5204,
  "longitude": 74.3587,
  "bearing": 180,
  "timestamp": 1718012400
}
```

### 3.2 Python Script: Live Telemetry to GTFS-rt Buffer
This script takes the captured live JSON format and converts it to a standard GTFS-rt entity structure.
*(Requires packages: `pip install google-transit-protobuf`)*

```python
import time
import json
from google.transit import gtfs_realtime_pb2

def json_to_gtfs_rt(raw_json_data):
    # Initialize real-time feed container
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
    feed.header.timestamp = int(time.time())

    telemetry_list = json.loads(raw_json_data)

    for index, bus in enumerate(telemetry_list):
        entity = feed.entity.add()
        entity.id = f"vehicle_update_{index}"
        
        # Define vehicle position object
        vehicle = entity.vehicle
        vehicle.vehicle.id = str(bus["vehicle_id"])
        vehicle.trip.route_id = str(bus["route_id"])
        vehicle.position.latitude = float(bus["latitude"])
        vehicle.position.longitude = float(bus["longitude"])
        vehicle.position.bearing = float(bus.get("bearing", 0.0))
        vehicle.timestamp = int(bus["timestamp"])

    # Output file serialized as a protocol buffer
    with open("vehicle_positions.pb", "wb") as f:
        f.write(feed.SerializeToString())
    print("[SUCCESS] Live GTFS-rt feed written to vehicle_positions.pb")

# Practical data instance example
sample_live_json = '[{"vehicle_id": "M-4012", "route_id": 12, "latitude": 31.5204, "longitude": 74.3587, "timestamp": 1718012400}]'
json_to_gtfs_rt(sample_live_json)
```

---

## Section 4: Operational Security & Anti-Blacklist Controls

Because you are calling non-public endpoints, security policies enforced by government-managed firewalls (Web Application Firewalls / WAF) must be carefully respected. 

### 4.1 Strict Polling Intervals (Throttle Controls)
* **Rule:** Do not loop network scripts constantly.
* **Interval:** Restrict polling sequences to a minimum of **60 to 90 seconds** per request cycle. 
* **Reasoning:** Mass-transit telemetry coordinates update periodically based on infrastructure hardware limits. Scraping milliseconds faster will yield duplicate data while instantly flagging your client as a Denial-of-Service (DoS) threat.

### 4.2 Exact Header Spoofing
Your script must mirror the exact client fingerprint captured by Fiddler Classic to look like a legitimate app user.
* Match the exact order of keys in your script's request headers.
* Duplicate the **User-Agent** string (e.g., `Dalvik/2.1.0 (Linux; U; Android...)`).
* Maintain active bearer authorization metadata parameters if passed within the API headers.

### 4.3 Network Layer Isolation
* Execute ingestion scripts with an active commercial VPN running on your host system.
* In the event that a script fails or accidentally violates a throttling rule, only the temporary public node IP address provided by the VPN service provider will get blacklisted—safeguarding your home internet connection and physical hardware identifiers.
