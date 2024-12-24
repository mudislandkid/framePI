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
git clone https://github.com/YOUR_USERNAME/photoframe.git
```

2. Run the install script:
```bash
cd photoframe
sudo ./install.sh
```

The install script will:
- Install required system packages
- Set up Python virtual environment
- Configure Nginx
- Create system service
- Set up initial database
- Configure directories and permissions

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
{
    "DEV_MODE": false,
    "UPLOAD_FOLDER": "/opt/photoframe/server_photos",
    "DATABASE": "/opt/photoframe/photo_frame.db",
    "HOST": "0.0.0.0",
    "PORT": 80,
    "ALLOWED_EXTENSIONS": ["png", "jpg", "jpeg"],
    "MAX_CONTENT_LENGTH": 52428800,
    "MATTING_MODE": "white",
    "DISPLAY_TIME": 30,
    "TRANSITION_SPEED": 2,
    "ENABLE_PORTRAIT_PAIRS": true,
    "PORTRAIT_GAP": 20,
    "SORT_MODE": "sequential"
}
```

### Client Configuration

Client configuration is managed through the web interface at `http://your-server/admin/settings`

## Usage

1. Access the admin interface at `http://your-server/admin`
2. Upload photos through the web interface
3. Configure display settings
4. Monitor connected clients
5. Manage photo organization and pairing

## Development

### Server Development
```bash
# Set up development environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run development server
python api.py
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
   - Check X server is running
   - Verify display resolution settings
   - Check logs: `journalctl -u photo_display -f`

2. **Sync Issues**
   - Verify network connectivity
   - Check server URL configuration
   - Check logs: `journalctl -u photo_display -f`

3. **Permission Issues**
   - Verify file permissions in photos directory
   - Check service user permissions
   - Review service logs

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Acknowledgments

- Built using Flask for the web framework
- Pygame for display handling
- Pillow for image processing

