
# Photo Frame

A digital photo frame system with a centralized web server for managing photos and multiple Raspberry Pi clients for display. Built with Python, Flask, and Pygame.

## Features

- Web-based admin interface for managing photos
- Support for multiple photo frame displays
- Automatic portrait photo pairing
- Smooth transitions between photos
- Multiple sorting options (sequential, random, newest, oldest)
- Remote client management and monitoring
- OTA (Over-The-Air) updates for client displays
- Background color options (white, black, or auto from dominant colors)

## System Requirements

### Server
- Ubuntu/Debian based system
- Python 3.11+
- Nginx
- SQLite3

### Client (Raspberry Pi)
- Raspberry Pi (tested on Pi 4)
- Raspbian/Raspberry Pi OS
- Python 3.11+
- X11 display server
- Connected display

## Quick Start

### Server Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/mudislandkid/framePI.git
   ```

2. Run the install script:
   ```bash
   cd framePI
   chmod +x ./install.sh
   sudo ./install.sh --mode <dev|prod>
   ```

   Replace `<dev|prod>` with:
   - `dev` for development mode: runs Flask server with debug enabled and sets host to `127.0.0.1`. This is designed for local testing without a RPI client. It will launch a python window to emulate the RPI display.
   - `prod` for production mode: sets up Uvicorn with systemd and configures host as the external IP or FQDN.

   The install script will:
   - Update and upgrade the system
   - Install required system packages
   - Set up Python virtual environment
   - Configure Nginx
   - Create system service
   - Set up initial database
   - Configure directories and permissions

3. Access the admin interface:
   - In development mode: `http://127.0.0.1:5000/admin`
   - In production mode: `http://<your-server-ip>/admin`

### Client Setup

1. Install required packages on Raspberry Pi:
   ```bash
   sudo apt update
   sudo apt install -y python3-pip python3-pygame x11-xserver-utils
   ```

2. Clone the client files:
   ```bash
   mkdir -p ~/piFrame
   cd ~/piFrame
   # Copy client files from server or download from repository
   ```

3. Install Python requirements:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. Set up autostart service:
   ```bash
   sudo cp systemd/photo_display.service /etc/systemd/system/
   sudo systemctl enable photo_display
   sudo systemctl start photo_display
   ```

## Configuration

### Server Configuration

The server configuration is stored in `config.json`:

```json
DEFAULT_CONFIG = {
    "DEV_MODE": False,
    "UPLOAD_FOLDER": os.path.join(BASE_DIR, 'uploads'),
    "DATABASE": os.path.join(BASE_DIR, 'photo_frame.db'),
    "HOST": 'localhost',
    "PORT": 5000,
    "ALLOWED_EXTENSIONS": [
        "jpg", "jpeg", "JPG", "JPEG",
        "png", "PNG",
        "gif", "GIF",
        "bmp", "BMP",
        "webp", "WEBP",
        "tiff", "TIFF", "tif", "TIF",
        "heic", "HEIC"
    ],
    "MAX_CONTENT_LENGTH": 50 * 1024 * 1024,  # 50MB max file size
    "SECRET_KEY": 'dev',
    # Display settings
    "MATTING_MODE": 'white',
    "DISPLAY_TIME": 15,
    "TRANSITION_SPEED": 10,
    "ENABLE_PORTRAIT_PAIRS": True,
    "PORTRAIT_GAP": 20,
    "SORT_MODE": "random",
    # Client versioning
    "CLIENT_VERSION": {
        "display.py": "1.0.5",
        "sync_client.py": "1.0.5"
    }
}
```

### Client Configuration

Client configuration is managed through the web interface at `http://your-server/admin/settings`.

## Usage

1. Access the admin interface at `http://your-server/admin`.
2. Upload photos through the web interface.
3. Configure display settings.
4. Monitor connected clients.
5. Manage photo organization and pairing.

## Development

### Server Development
```bash
# Set up development environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run development server
./run_dev.sh
```

### Client Development
```bash
# Run in development mode
DEV_MODE=1 python display.py
```

## Architecture

- **Server**: Flask-based web application serving photos and managing configuration
- **Client**: Pygame-based display application with sync capabilities
- **Communication**: RESTful API between server and clients
- **Database**: SQLite for photo and client management
- **Updates**: OTA update system for client software

## Troubleshooting

### Common Issues

1. **Display Issues**
   - Check X server is running.
   - Verify display resolution settings.
   - Check logs: `journalctl -u photo_display -f`.

2. **Sync Issues**
   - Verify network connectivity.
   - Check server URL configuration.
   - Check logs: `journalctl -u photo_display -f`.

3. **Permission Issues**
   - Verify file permissions in photos directory.
   - Check service user permissions.
   - Review service logs.

## Contributing

1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/amazing-feature`).
3. Commit your changes (`git commit -m 'Add amazing feature'`).
4. Push to the branch (`git push origin feature/amazing-feature`).
5. Open a Pull Request.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Acknowledgments

- Built using Flask for the web framework.
- Pygame for display handling.
- Pillow for image processing.
