#!/bin/bash

# Colors for prettier output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored messages
print_status() { echo -e "${GREEN}[+]${NC} $1"; }
print_error() { echo -e "${RED}[!]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[*]${NC} $1"; }
print_info() { echo -e "${BLUE}[i]${NC} $1"; }

# Function to check if a command exists
check_command() {
    if ! command -v $1 &> /dev/null; then
        print_error "$1 is not installed. Installing..."
        return 1
    else
        return 0
    fi
}

# Function to update config.py for mode and host
update_config() {
    local mode=$1
    local host=$2

    if ! $INSTALL_DIR/venv/bin/python3 << EOF
import sys
sys.path.append('$INSTALL_DIR/server')
from config import save_config, load_config
config = load_config()
config["DEV_MODE"] = ${mode,,}  # Convert to Python's True/False
config["HOST"] = "$host"
save_config(config)
EOF
    then
        print_error "Failed to update config.py! Ensure the config module is properly installed in $INSTALL_DIR/server."
        return 1
    fi
    print_status "Config updated: DEV_MODE=$mode, HOST=$host"
    return 0
}

# Function to prompt for FQDN and SSL setup
setup_fqdn_ssl() {
    read -p "Do you want to set up a Fully Qualified Domain Name (FQDN)? (y/n): " setup_fqdn
    if [[ "$setup_fqdn" == "y" || "$setup_fqdn" == "Y" ]]; then
        read -p "Enter your FQDN (e.g., example.com): " fqdn
        if ! $INSTALL_DIR/venv/bin/python3 -c "import sys; sys.path.append('$INSTALL_DIR/server'); from config import update_fqdn; update_fqdn('$fqdn')"; then
            print_error "Failed to configure FQDN in config.py!"
            exit 1
        fi
        read -p "Do you want to set up SSL with Let's Encrypt for $fqdn? (y/n): " setup_ssl
        if [[ "$setup_ssl" == "y" || "$setup_ssl" == "Y" ]]; then
            setup_ssl "$fqdn"
        fi
    else
        print_warning "Skipping FQDN and SSL setup."
    fi
}

# Function to test Python virtual environment
test_virtualenv() {
    print_status "Testing Python virtual environment..."
    source $INSTALL_DIR/venv/bin/activate
    if ! python3 -m venv --help &> /dev/null; then
        print_error "Virtual environment is not set up correctly."
        print_info "Try running: python3 -m venv $INSTALL_DIR/venv and activate it manually."
        return 1
    fi
    print_status "Virtual environment is set up correctly."
    return 0
}

# Function to test database connection
test_database() {
    local db_path=$1
    print_status "Testing database at: $db_path"
    
    if ! $INSTALL_DIR/venv/bin/python3 << EOF
import sqlite3
try:
    conn = sqlite3.connect('$db_path')
    c = conn.cursor()
    c.execute('SELECT SQLITE_VERSION()')
    version = c.fetchone()
    print(f"SQLite version: {version[0]}")
    conn.close()
    exit(0)
except Exception as e:
    print(f"Database error: {e}")
    exit(1)
EOF
    then
        print_error "Database test failed!"
        print_info "Troubleshooting steps:"
        print_info "1. Ensure the database file exists: $db_path"
        print_info "2. Check file permissions: sudo chown -R www-data:www-data $db_path"
        print_info "3. Initialize the database manually using the application."
        return 1
    fi
    return 0
}

# Function to test API endpoints
test_api() {
    print_status "Testing API endpoints..."
    local endpoints=("/api/config" "/api/photos" "/admin/settings")
    local failed=0
    
    for endpoint in "${endpoints[@]}"; do
        if ! curl -s "http://localhost$endpoint" > /dev/null; then
            print_error "Endpoint $endpoint failed!"
            failed=1
        fi
    done
    
    if [ $failed -eq 1 ]; then
        print_error "API tests failed!"
        print_info "Troubleshooting steps:"
        print_info "1. Check if the application is running: sudo systemctl status photoframe"
        print_info "2. Review server logs: sudo journalctl -u photoframe -f"
        print_info "3. Verify Nginx configuration: sudo nginx -t"
        return 1
    fi
    print_status "All API endpoints are working."
    return 0
}

# Parse command line arguments
MODE=""
SETUP_SSL=0
DOMAIN=""
SSL_EMAIL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --ssl)
            SETUP_SSL=1
            DOMAIN="$2"
            SSL_EMAIL="$3"
            shift 3
            ;;
        *)
            print_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Validate mode
if [[ "$MODE" != "dev" && "$MODE" != "prod" ]]; then
    print_error "Please specify a valid mode: --mode dev or --mode prod"
    exit 1
fi

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run as root"
    exit 1
fi

# Set installation directory
INSTALL_DIR="/opt/framePI"

# Remove previous installation if exists
if [ -d "$INSTALL_DIR" ]; then
    print_warning "Previous installation detected. Removing..."
    rm -rf "$INSTALL_DIR"
    print_status "Previous installation removed."
fi

# Update and upgrade the system
print_status "Updating and upgrading the system..."
apt-get update && apt-get upgrade -y

# Create directory structure
print_status "Creating directory structure..."
mkdir -p $INSTALL_DIR
mkdir -p $INSTALL_DIR/server_photos
mkdir -p $INSTALL_DIR/logs
mkdir -p $INSTALL_DIR/client
mkdir -p $INSTALL_DIR/server

# Copy server files
print_status "Copying server files to installation directory..."
cp -r ./server/* $INSTALL_DIR/server/

# Check and install required system packages
print_status "Checking and installing required system packages..."
apt-get update

PACKAGES="python3 python3-pip python3-venv nginx git curl"
for pkg in $PACKAGES; do
    if ! dpkg -l | grep -q "^ii  $pkg "; then
        print_status "Installing $pkg..."
        apt-get install -y $pkg
    fi
done

# Create virtual environment
print_status "Setting up Python virtual environment..."
python3 -m venv $INSTALL_DIR/venv
source $INSTALL_DIR/venv/bin/activate

# Create requirements file
print_status "Creating requirements file..."
cat > $INSTALL_DIR/requirements.txt << EOL
flask
pillow
requests
werkzeug
gunicorn
uvicorn
EOL

# Install Python requirements
print_status "Installing Python requirements from requirements.txt..."
$INSTALL_DIR/venv/bin/pip install -r $INSTALL_DIR/requirements.txt

# Test virtual environment
if ! test_virtualenv; then
    print_error "Virtual environment setup failed."
    exit 1
fi

# Configure based on mode
if [[ "$MODE" == "dev" ]]; then
    print_status "Configuring for development mode..."
    update_config True "127.0.0.1"

    # Create Flask run script
    cat > $INSTALL_DIR/run_dev.sh << EOL
#!/bin/bash
source $INSTALL_DIR/venv/bin/activate
export FLASK_ENV=development
flask run --host=127.0.0.1 --port=5000
EOL
    chmod +x $INSTALL_DIR/run_dev.sh
    print_status "Development setup complete! Run with: $INSTALL_DIR/run_dev.sh"
else
    print_status "Configuring for production mode..."
    host=${DOMAIN:-$(hostname -I | awk '{print $1}')}
    update_config False "$host"

    # Prompt for FQDN and SSL setup
    setup_fqdn_ssl

    # Create systemd service for Uvicorn
    cat > /etc/systemd/system/framePI.service << EOL
[Unit]
Description=Photo Frame Server
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin"
ExecStart=$INSTALL_DIR/venv/bin/uvicorn api:app --host $host --port 80
Restart=always

[Install]
WantedBy=multi-user.target
EOL

    systemctl daemon-reload
    systemctl enable framePI
    systemctl restart framePI
    print_status "Production setup complete! Server running at http://$host"
fi

exit 0
