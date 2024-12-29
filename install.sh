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

# Function for comprehensive cleanup of previous installations
cleanup_previous_installation() {
    print_status "Performing comprehensive cleanup..."
    
    # Stop all related services
    print_info "Stopping services..."
    systemctl stop framePI nginx || true
    systemctl disable framePI nginx || true
    
    # Kill any running processes more aggressively
    print_info "Killing any running processes..."
    pkill -f nginx || true
    killall nginx || true
    pkill -f "uvicorn.*framePI" || true
    
    # Small delay to ensure processes are terminated
    sleep 2
    
    # Force kill any remaining nginx processes
    if pgrep nginx > /dev/null; then
        print_warning "Forcing termination of remaining nginx processes..."
        pkill -9 -f nginx || true
    fi
    
    # Remove service files
    print_info "Removing service files..."
    rm -f /etc/systemd/system/framePI.service
    
    # Clean up Nginx configurations
    print_info "Cleaning up Nginx configurations..."
    rm -f /etc/nginx/sites-enabled/*
    rm -f /etc/nginx/sites-available/framePI
    rm -f /var/run/nginx.pid
    
    # Remove installation directory
    if [ -d "$INSTALL_DIR" ]; then
        print_info "Removing previous installation directory..."
        rm -rf "$INSTALL_DIR"
    fi
    
    # Clean up log files
    print_info "Cleaning up log files..."
    rm -f /var/log/framePI.log
    rm -f /var/log/framePI.error.log
    
    # Clean up port usage
    print_info "Checking for processes using required ports..."
    for port in 80 443 8000; do
        if lsof -i ":$port" > /dev/null 2>&1; then
            print_warning "Found process using port $port. Attempting to terminate..."
            fuser -k "$port/tcp" || true
        fi
    done
    
    # Reload systemd daemon
    systemctl daemon-reload
    
    # Verify cleanup
    if pgrep nginx > /dev/null || lsof -i :80 > /dev/null 2>&1 || lsof -i :443 > /dev/null 2>&1; then
        print_error "Some processes could not be cleaned up. Manual intervention required."
        print_info "Try running these commands:"
        print_info "sudo systemctl stop nginx"
        print_info "sudo killall -9 nginx"
        print_info "sudo rm /var/run/nginx.pid"
        return 1
    fi
    
    print_status "Cleanup completed successfully."
    return 0
}

# Function to check ports
check_ports() {
    local ports=("80" "443" "8000")
    for port in "${ports[@]}"; do
        if lsof -i ":$port" >/dev/null 2>&1; then
            print_error "Port $port is already in use"
            print_info "Finding process using port $port..."
            lsof -i ":$port"
            return 1
        fi
    done
    return 0
}

# Function to configure Nginx
configure_nginx() {
    local fqdn=$1
    print_status "Configuring Nginx for FQDN..."
    
    # Clean up any existing configurations
    rm -f /etc/nginx/sites-enabled/*
    rm -f /etc/nginx/sites-available/framePI
    
    # Create Nginx configuration
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

    # Test Nginx configuration
    if ! nginx -t; then
        print_error "Nginx configuration test failed!"
        return 1
    fi
    
    print_status "Nginx configuration completed successfully"
    return 0
}

# Function to set up SSL using Let's Encrypt
setup_ssl() {
    local fqdn=$1
    print_status "Setting up SSL for $fqdn..."

    # Stop all web services first
    systemctl stop nginx framePI || true
    sleep 2
    
    # Double check no processes are running
    pkill -f nginx || true
    sleep 1

    # Install certbot if needed
    if ! command -v certbot &> /dev/null; then
        print_status "Installing certbot..."
        apt-get update
        apt-get install -y certbot python3-certbot-nginx
    fi

    # Obtain certificate without using nginx plugin
    if certbot certonly --standalone -d "$fqdn" --non-interactive --agree-tos --email "admin@$fqdn"; then
        # Manually configure nginx for SSL
        cat > /etc/nginx/sites-available/framePI << EOL
server {
    listen 80;
    listen [::]:80;
    server_name ${fqdn};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${fqdn};

    ssl_certificate /etc/letsencrypt/live/${fqdn}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${fqdn}/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDH+AESGCM:ECDH+AES256:ECDH+AES128:DH+3DES:!ADH:!AECDH:!MD5;

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

        print_status "SSL setup complete for $fqdn"
        return 0
    else
        print_error "Failed to obtain SSL certificate for $fqdn"
        return 1
    fi
}

# Function to update config.py
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
        print_error "Failed to update config.py!"
        return 1
    fi
    print_status "Config updated: DEV_MODE=$mode, HOST=$host"
    return 0
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

# Function to start services in the correct order
start_services() {
    print_status "Starting services in correct order..."
    
    # Stop everything first
    systemctl stop nginx framePI || true
    sleep 2
    
    # Kill any remaining processes
    pkill -f nginx || true
    pkill -f "uvicorn.*framePI" || true
    sleep 1
    
    # Start framePI first
    print_info "Starting framePI service..."
    systemctl start framePI
    sleep 2
    
    if ! systemctl is-active --quiet framePI; then
        print_error "framePI service failed to start"
        journalctl -u framePI --no-pager -n 50
        return 1
    fi
    
    # Then start nginx
    print_info "Starting nginx service..."
    systemctl start nginx
    sleep 2
    
    if ! systemctl is-active --quiet nginx; then
        print_error "Nginx failed to start"
        journalctl -u nginx --no-pager -n 50
        return 1
    fi
    
    print_status "All services started successfully"
    return 0
}
# Main installation logic
main() {
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        print_error "Please run as root"
        exit 1
    fi

    # Set installation directory
    INSTALL_DIR="/opt/framePI"

    # Perform cleanup
    if ! cleanup_previous_installation; then
        print_error "Cleanup failed. Please resolve the issues and try again."
        exit 1
    fi

    # Install required packages
    print_status "Installing required packages..."
    apt-get update
    apt-get install -y python3-venv python3-dev nginx sqlite3 lsof || {
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
        mkdir -p "$dir" || {
            print_error "Failed to create directory $dir. Exiting."
            exit 1
        }
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

# Set up FQDN and SSL
    read -p "Do you want to set up a Fully Qualified Domain Name (FQDN)? (y/n): " setup_fqdn
    if [[ "$setup_fqdn" == "y" || "$setup_fqdn" == "Y" ]]; then
        read -p "Enter your FQDN (e.g., example.com): " fqdn
        
        # Update Python configuration with FQDN
        if ! $INSTALL_DIR/venv/bin/python3 -c "import sys; sys.path.append('$INSTALL_DIR/server'); from config import update_fqdn; update_fqdn('$fqdn')"; then
            print_error "Failed to configure FQDN in config.py!"
            exit 1
        fi

        echo "Configuration updated with FQDN: $fqdn"

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
        configure_nginx "localhost"
    fi

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

    # Enable services
    systemctl daemon-reload
    systemctl enable framePI
    systemctl enable nginx

    # Start services in correct order
    if ! start_services; then
        print_error "Failed to start services. Please check the logs and try again."
        exit 1
    fi

    # Print installation summary
    print_status "Installation Summary:"
    echo "--------------------"
    echo "Installation Directory: $INSTALL_DIR"
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
        print_status "You can access the server at: http://localhost"
    fi

    # Print helpful commands
    print_info "Useful commands:"
    echo "  - View application logs: sudo journalctl -u framePI -f"
    echo "  - View nginx logs: sudo tail -f /var/log/nginx/error.log"
    echo "  - Restart application: sudo systemctl restart framePI"
    echo "  - Check status: sudo systemctl status framePI"

    print_status "Installation complete!"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        *)
            print_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Run main installation
main "$@"