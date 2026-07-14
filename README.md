# dhn-pi

IoT edge controller for Raspberry Pi — GPIO, sensors, camera, MQTT, REST API.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # edit credentials
cp config.example.yaml config.yaml
python main.py
```

Web UI: http://localhost:8000 — Swagger: http://localhost:8000/docs

---

## Installation

### Option 1: Docker (Linux / Windows)

```bash
# 1. Configure
cp .env.example .env
cp config.example.yaml config.yaml
# edit .env and config.yaml

# 2. Run
docker compose up -d

# 3. View logs
docker compose logs -f
```

On a Raspberry Pi, GPIO and I2C devices are auto-mounted. If device paths differ, set `privileged: true` in `docker-compose.yml`.

### Option 2: Linux (systemd — auto-start with OS)

```bash
sudo bash deploy/install.sh [/opt/dhn-pi]
```

This installs to `/opt/dhn-pi` by default, creates a venv, installs deps, and registers a systemd service.

Manage:
```bash
sudo systemctl status dhn-pi
sudo systemctl start|stop|restart dhn-pi
journalctl -u dhn-pi -f
```

### Option 3: Windows (NSSM service — auto-start with OS)

```powershell
# Run as Administrator
.\deploy\install_service.ps1
```

Manage:
```powershell
nssm start|stop|restart|status DHN-Pi
```

### Option 4: Python package (any OS)

```bash
pip install -e .
dhn-pi
```

---

## Configuration

| File | Purpose |
|---|---|
| `.env` | Environment variables (MQTT, DB URL, device code) |
| `config.yaml` | GPIO devices, sensors, camera, scheduler |

All values in `.env` override matching keys in `config.yaml`.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DEVICE_CODE` | `PI-000001` | Unique device identifier |
| `MQTT_BROKER` | `localhost` | MQTT broker hostname |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USERNAME` | — | MQTT username |
| `MQTT_PASSWORD` | — | MQTT password |
| `DATABASE_URL` | `sqlite:///dhn_pi.db` | Database URL |
| `LOG_LEVEL` | `DEBUG` | Log level (DEBUG/INFO/WARNING/ERROR) |

---

## Project structure

```
dhn-pi/
├── main.py                 # Entry point
├── config/                 # Pydantic settings + YAML loader
├── core/                   # Controller + database
├── drivers/                # GPIO, sensors, camera
├── services/               # MQTT, web server, scheduler, system stats
├── scripts/                # Utility CLI tools
├── deploy/                 # Systemd service + Windows service script
├── tests/                  # pytest tests
├── Dockerfile              # Docker build
├── docker-compose.yml      # Docker orchestration
└── pyproject.toml          # Python packaging
```

---

## API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/gpio` | List GPIO devices |
| POST | `/gpio/{name}` | Set GPIO output state |
| GET | `/sensors` | Read all sensors |
| GET | `/camera/stream` | MJPEG live stream |
| GET | `/camera/capture` | Single JPEG frame |
| POST | `/mqtt/publish` | Publish MQTT message |

---

## Development

```bash
pip install -e .
pytest tests/
```
