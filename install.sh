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

# Function to configure Nginx
configure_nginx() {
    local fqdn=$1
    print_status "Configuring Nginx for FQDN..."
    
    # Create initial Nginx configuration
    cat > /etc/nginx/sites-available/framePI << EOL
server {
    listen 80;
    listen [::]:80;
    server_name ${fqdn:-_};

    client_max_body_size 50M;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static {
        alias $INSTALL_DIR/server/static;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location /uploads {
        alias $INSTALL_DIR/server/uploads;
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }
}
EOL

    # Enable the site
    ln -sf /etc/nginx/sites-available/framePI /etc/nginx/sites-enabled/

    # Remove default site if it exists
    rm -f /etc/nginx/sites-enabled/default
    
    # Test Nginx configuration
    if ! nginx -t; then
        print_error "Nginx configuration test failed!"
        return 1
    fi
    
    # Restart Nginx
    systemctl restart nginx
    if [ $? -ne 0 ]; then
        print_error "Failed to restart Nginx"
        return 1
    fi
    
    print_status "Nginx configuration completed successfully"
    return 0
}

# Function to set up SSL using Let's Encrypt
setup_ssl() {
    local fqdn=$1
    print_status "Setting up SSL for $fqdn..."

    # Install certbot if not already installed
    if ! check_command "certbot"; then
        print_status "Installing certbot..."
        apt-get update
        apt-get install -y certbot python3-certbot-nginx
    fi

    # Stop Nginx temporarily to free up port 80
    systemctl stop nginx

    # Obtain SSL certificate
    if certbot --nginx -d "$fqdn" --non-interactive --agree-tos --email "admin@$fqdn" --redirect; then
        print_status "SSL setup complete for $fqdn"
        systemctl start nginx
        return 0
    else
        print_error "Failed to obtain SSL certificate for $fqdn"
        systemctl start nginx
        return 1
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

# Function to handle FQDN and SSL setup
setup_fqdn_ssl() {
    read -p "Do you want to set up a Fully Qualified Domain Name (FQDN)? (y/n): " setup_fqdn
    if [[ "$setup_fqdn" == "y" || "$setup_fqdn" == "Y" ]]; then
        read -p "Enter your FQDN (e.g., example.com): " fqdn
        
        # Update Python configuration with FQDN
        if ! $INSTALL_DIR/venv/bin/python3 -c "import sys; sys.path.append('$INSTALL_DIR/server'); from config import update_fqdn; update_fqdn('$fqdn')"; then
            print_error "Failed to configure FQDN in config.py!"
            exit 1
        fi

        # Configure Nginx first
        if ! configure_nginx "$fqdn"; then
            print_error "Failed to configure Nginx. Exiting."
            exit 1
        fi

        # Ask about SSL setup
        read -p "Do you want to set up SSL with Let's Encrypt for $fqdn? (y/n): " setup_ssl_prompt
        if [[ "$setup_ssl_prompt" == "y" || "$setup_ssl_prompt" == "Y" ]]; then
            if ! setup_ssl "$fqdn"; then
                print_warning "SSL setup failed. You can try setting it up manually later using:"
                print_info "sudo certbot --nginx -d $fqdn"
            fi
        else
            print_warning "Skipping SSL setup."
        fi
    else
        print_warning "Skipping FQDN and SSL setup."
        # Configure Nginx with default configuration
        configure_nginx "localhost"
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
    
    # Stop services if running
    systemctl stop framePI nginx || true
    
    # Disable services
    systemctl disable framePI nginx || true
    
    # Remove service files
    rm -f /etc/systemd/system/framePI.service
    rm -f /etc/nginx/sites-enabled/framePI
    rm -f /etc/nginx/sites-available/framePI
    
    # Reload systemd daemon
    systemctl daemon-reload
    
    # Remove installation directory
    rm -rf "$INSTALL_DIR"
    
    print_status "Previous installation removed."
fi

# Update and upgrade the system
print_status "Updating and upgrading the system..."
apt-get update || {
    print_error "System update failed. Exiting."
    exit 1
}

# Install required packages
print_status "Installing required packages..."
apt-get install -y python3-venv python3-dev nginx sqlite3 || {
    print_error "Failed to install required packages. Exiting."
    exit 1
}

# Create directory structure
print_status "Setting up required directories..."
directories=(
    "$INSTALL_DIR/server"
    "$INSTALL_DIR/server/uploads"
    "$INSTALL_DIR/server/static"
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
print_status "Installing Python requirements..."
cat > $INSTALL_DIR/requirements.txt << EOL
flask
pillow
requests
werkzeug
gunicorn
uvicorn
python-dotenv
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

# Configure for production
if [[ "$MODE" == "prod" ]]; then
    print_status "Configuring for production mode..."
    
    # Enforce IPv4 and resolve FQDN or use default
    host=${fqdn:-$(hostname -I | grep -m 1 "^[0-9]\+\.[0-9]\+\.[0-9]\+\.[0-9]\+$")}
    if [[ -z "$host" ]]; then
        print_error "Failed to resolve a valid IPv4 address for the host. Exiting."
        exit 1
    fi
    update_config False "$host"

    # Create log files
    print_status "Setting up log files..."
    touch /var/log/framePI.log /var/log/framePI.error.log
    chown www-data:www-data /var/log/framePI.log /var/log/framePI.error.log

# Create systemd service
    print_status "Setting up systemd service..."
    cat > /etc/systemd/system/framePI.service << EOL
[Unit]
Description=Photo Frame Server
After=network.target
Requires=nginx.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=$INSTALL_DIR/server
Environment="PATH=$INSTALL_DIR/venv/bin"
ExecStart=$INSTALL_DIR/venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000
Restart=always
StandardOutput=append:/var/log/framePI.log
StandardError=append:/var/log/framePI.error.log

[Install]
WantedBy=multi-user.target
EOL

    # Start services
    print_status "Starting services..."
    systemctl daemon-reload
    
    # Stop services if running
    systemctl stop framePI nginx
    
    # Start and enable services in correct order
    systemctl enable nginx
    systemctl start nginx
    systemctl enable framePI
    systemctl start framePI

    # Verify services
    if ! systemctl is-active --quiet nginx; then
        print_error "Nginx failed to start. Check logs with: journalctl -u nginx"
        exit 1
    fi

    if ! systemctl is-active --quiet framePI; then
        print_error "framePI service failed to start. Check logs with: journalctl -u framePI -f"
        exit 1
    fi

    print_status "All services started successfully"

    # Test API endpoints
    print_status "Testing API endpoints..."
    sleep 5  # Give the service a moment to fully start
    if ! test_api; then
        print_warning "API endpoint tests failed. Please check the logs and configuration."
    fi
fi

# Final verification and information
print_status "Verifying installation..."

# Check directory permissions
if [ ! -w "$INSTALL_DIR/server/uploads" ]; then
    print_warning "Uploads directory may have incorrect permissions. Running fix..."
    chown -R www-data:www-data "$INSTALL_DIR/server/uploads"
    chmod -R 755 "$INSTALL_DIR/server/uploads"
fi

# Check log files
if [ ! -f "/var/log/framePI.log" ]; then
    print_warning "Log file not found. Creating..."
    touch /var/log/framePI.log /var/log/framePI.error.log
    chown www-data:www-data /var/log/framePI.log /var/log/framePI.error.log
fi

# Print installation summary
print_status "Installation Summary:"
echo "--------------------"
echo "Installation Directory: $INSTALL_DIR"
echo "Mode: $MODE"
echo "Host: ${host:-localhost}"
if [ ! -z "$fqdn" ]; then
    echo "FQDN: $fqdn"
    echo "SSL: ${setup_ssl_prompt:-no}"
fi
echo "Logs: /var/log/framePI.log"
echo "Error Logs: /var/log/framePI.error.log"
echo "--------------------"

# Print access information
if [ ! -z "$fqdn" ]; then
    print_status "You can access the server at:"
    print_info "http://${fqdn}"
    if [[ "$setup_ssl_prompt" == "y" || "$setup_ssl_prompt" == "Y" ]]; then
        print_info "https://${fqdn}"
    fi
else
    print_status "You can access the server at: http://${host:-localhost}"
fi

# Print helpful commands
print_info "Useful commands:"
echo "  - View application logs: sudo journalctl -u framePI -f"
echo "  - View nginx logs: sudo tail -f /var/log/nginx/error.log"
echo "  - Restart application: sudo systemctl restart framePI"
echo "  - Check status: sudo systemctl status framePI"

print_status "Installation complete!"
exit 0