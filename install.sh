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

# Function to set up SSL using Let's Encrypt
setup_ssl() {
    local fqdn=$1
    print_status "Setting up SSL for $fqdn..."

    # Install certbot if not already installed
    if ! check_command "certbot"; then
        print_status "Installing certbot..."
        apt-get install -y certbot python3-certbot-nginx
    fi

    # Obtain SSL certificate
    if certbot --nginx -d "$fqdn" --non-interactive --agree-tos --email "admin@$fqdn" --redirect; then
        print_status "SSL setup complete for $fqdn."
    else
        print_error "Failed to obtain SSL certificate for $fqdn. Check your DNS settings and ensure ports 80 and 443 are open."
        exit 1
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
config["DEV_MODE"] = True if "$mode" == "True" else False
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

        # Update Nginx configuration
        print_status "Configuring Nginx for FQDN..."
        cat > /etc/nginx/sites-available/framePI << EOL
server {
    listen 80;
    server_name $fqdn;

    location / {
        proxy_pass http://127.0.0.1:80;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    location /static {
        root $INSTALL_DIR/server;
    }
}
EOL
        ln -sf /etc/nginx/sites-available/framePI /etc/nginx/sites-enabled/
        systemctl restart nginx || {
            print_error "Failed to restart Nginx. Check configuration and try again."
            exit 1
        }
        print_status "Nginx configuration updated for $fqdn."
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
        print_info "1. Check if the application is running: sudo systemctl status framePI"
        print_info "2. Review server logs: sudo journalctl -u framePI -f"
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
    if systemctl is-active --quiet framePI; then
        print_status "Stopping existing framePI service..."
        systemctl stop framePI || {
            print_error "Failed to stop existing framePI service. Exiting."
            exit 1
        }
    fi
    print_status "Disabling existing framePI service..."
    systemctl disable framePI || {
        print_error "Failed to disable existing framePI service. Exiting."
        exit 1
    }
    print_status "Removing existing framePI service..."
    rm -f /etc/systemd/system/framePI.service || {
        print_error "Failed to remove existing framePI service file. Exiting."
        exit 1
    }
    print_status "Reloading systemd daemon..."
    systemctl daemon-reload || {
        print_error "Failed to reload systemd daemon after service removal. Exiting."
        exit 1
    }
    rm -rf "$INSTALL_DIR"
    print_status "Previous installation removed."
fi

# Update and upgrade the system
print_status "Updating and upgrading the system..."
apt-get update && apt-get upgrade -y || {
    print_error "System update and upgrade failed. Exiting."
    exit 1
}

# Create directory structure
# Ensure the necessary directories exist with correct permissions
print_status "Setting up required directories..."
directories=(
    "$INSTALL_DIR/server"
    "$INSTALL_DIR/server/server_photos"
    "$INSTALL_DIR/server/logs"
)

for dir in "${directories[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir" || {
            print_error "Failed to create directory $dir. Exiting."
            exit 1
        }
    fi
    chown -R www-data:www-data "$dir" || {
        print_error "Failed to set permissions for $dir. Exiting."
        exit 1
    }
    chmod -R 755 "$dir" || {
        print_error "Failed to set permissions for $dir. Exiting."
        exit 1
    }
done


# Copy server files
print_status "Copying server files to installation directory..."
cp -r ./server/* $INSTALL_DIR/server/ || {
    print_error "Failed to copy server files. Exiting."
    exit 1
}

# Set up Python virtual environment
print_status "Setting up Python virtual environment..."
python3 -m venv $INSTALL_DIR/venv || {
    print_error "Failed to create Python virtual environment. Exiting."
    exit 1
}
source $INSTALL_DIR/venv/bin/activate || {
    print_error "Failed to activate Python virtual environment. Exiting."
    exit 1
}

# Install Python requirements
print_status "Installing Python requirements from requirements.txt..."
cat > $INSTALL_DIR/requirements.txt << EOL
flask
pillow
requests
werkzeug
gunicorn
uvicorn
EOL
$INSTALL_DIR/venv/bin/pip install -r $INSTALL_DIR/requirements.txt || {
    print_error "Failed to install Python requirements. Exiting."
    exit 1
}

# Test virtual environment
if ! test_virtualenv; then
    print_error "Virtual environment setup failed. Exiting."
    exit 1
fi

# Prompt for FQDN and SSL setup
setup_fqdn_ssl

# Configure systemd service for production
if [[ "$MODE" == "prod" ]]; then
    print_status "Configuring for production mode..."
    
    # Enforce IPv4 and resolve FQDN or use default
    host=${fqdn:-$(hostname -I | grep -m 1 "^[0-9]\+\.[0-9]\+\.[0-9]\+\.[0-9]\+$")}
    if [[ -z "$host" ]]; then
        print_error "Failed to resolve a valid IPv4 address for the host. Exiting."
        exit 1
    fi
    update_config False "$host"

    # Create systemd service for Uvicorn with IPv4 enforced
    print_status "Setting up systemd service for Uvicorn..."
    cat > /etc/systemd/system/framePI.service << EOL
[Unit]
Description=Photo Frame Server
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$INSTALL_DIR/server
Environment="PATH=$INSTALL_DIR/venv/bin"
ExecStart=$INSTALL_DIR/venv/bin/uvicorn api:app --host 0.0.0.0 --port 80
Restart=always

[Install]
WantedBy=multi-user.target
EOL


    # Reload systemd daemon and enable service
    print_status "Reloading systemd daemon..."
    systemctl daemon-reload || {
        print_error "Failed to reload systemd daemon. Exiting."
        exit 1
    }
    print_status "Enabling framePI service..."
    systemctl enable framePI || {
        print_error "Failed to enable framePI service. Exiting."
        exit 1
    }
    print_status "Starting framePI service..."
    systemctl start framePI || {
        print_error "Failed to start framePI service. Exiting."
        exit 1
    }

    # Test if the service is running
    if ! systemctl is-active --quiet framePI; then
        print_error "framePI service failed to start. Check logs with: sudo journalctl -u framePI -f"
        exit 1
    fi
    print_status "framePI service is up and running."
fi


# Final message
print_status "Installation complete! You can access the server at http://${host} or https://${fqdn} if SSL was set up."
exit 0


