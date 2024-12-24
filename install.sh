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
        print_info "Try:"
        print_info "1. Check permissions: sudo chown -R www-data:www-data $db_path"
        print_info "2. Check directory exists: sudo mkdir -p $(dirname $db_path)"
        print_info "3. Initialize database manually: sudo $INSTALL_DIR/venv/bin/python3 -c 'from database import DatabaseManager; DatabaseManager.init_db()'"
        return 1
    fi
    return 0
}

# Function to test network connectivity
test_network() {
    local port=$1
    print_status "Testing network on port $port..."
    
    if ! netstat -tuln | grep -q ":$port "; then
        print_error "Port $port is not listening!"
        print_info "Try:"
        print_info "1. Check if nginx is running: sudo systemctl status nginx"
        print_info "2. Check nginx config: sudo nginx -t"
        print_info "3. Check service status: sudo systemctl status photoframe"
        return 1
    fi
    return 0
}

# Function to initialize database
init_database() {
    print_status "Initializing database..."
    if ! $INSTALL_DIR/venv/bin/python3 << EOF
from database import DatabaseManager
try:
    DatabaseManager.init_db()
    print("Database initialized successfully")
    exit(0)
except Exception as e:
    print(f"Database initialization error: {e}")
    exit(1)
EOF
    then
        print_error "Database initialization failed!"
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
        print_info "Try:"
        print_info "1. Check server logs: sudo journalctl -u photoframe -f"
        print_info "2. Check nginx logs: sudo tail -f /var/log/nginx/error.log"
        print_info "3. Restart services: sudo systemctl restart photoframe nginx"
        return 1
    fi
    return 0
}

# Function to setup SSL with Let's Encrypt
setup_ssl() {
    local domain=$1
    print_status "Setting up SSL for $domain"

    # Install certbot
    if ! check_command "certbot"; then
        apt-get install -y certbot python3-certbot-nginx
    fi

    # Get certificate
    if ! certbot --nginx -d "$domain" --non-interactive --agree-tos --email "$SSL_EMAIL" --redirect; then
        print_error "Failed to obtain SSL certificate!"
        print_info "Try:"
        print_info "1. Check domain DNS settings"
        print_info "2. Ensure port 80 is accessible"
        print_info "3. Run: certbot --nginx -d $domain"
        return 1
    fi

    print_status "SSL setup complete for $domain"
    return 0
}

# Function to setup Cloudflare Tunnel
setup_cloudflare_tunnel() {
    local tunnel_name=$1
    print_status "Setting up Cloudflare Tunnel: $tunnel_name"

    # Install cloudflared
    if ! check_command "cloudflared"; then
        # Add Cloudflare GPG key
        curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
        echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared focal main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
        apt-get update
        apt-get install -y cloudflared
    fi

    # Create tunnel configuration directory
    mkdir -p /etc/cloudflared

    # Create tunnel configuration file
    cat > /etc/cloudflared/config.yml << EOL
tunnel: ${tunnel_name}
credentials-file: /etc/cloudflared/${tunnel_name}.json
ingress:
  - hostname: ${DOMAIN}
    service: http://localhost:80
  - service: http_status:404
EOL

    print_info "Cloudflare Tunnel setup instructions:"
    print_info "1. Login to Cloudflare:"
    print_info "   cloudflared tunnel login"
    print_info "2. Create tunnel:"
    print_info "   cloudflared tunnel create ${tunnel_name}"
    print_info "3. Start tunnel:"
    print_info "   cloudflared tunnel run ${tunnel_name}"
    print_info "4. To run as service:"
    print_info "   cloudflared service install"
    
    return 0
}

# Parse command line arguments
DEV_MODE=0
SKIP_TESTS=0
SETUP_SSL=0
SETUP_CLOUDFLARE=0
REPO_URL="https://github.com/mudislandkid/framePI.git"
BRANCH="main"
DOMAIN=""
SSL_EMAIL=""
TUNNEL_NAME=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            DEV_MODE=1
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=1
            shift
            ;;
        --repo)
            REPO_URL="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --ssl)
            SETUP_SSL=1
            DOMAIN="$2"
            SSL_EMAIL="$3"
            shift 3
            ;;
        --cloudflare)
            SETUP_CLOUDFLARE=1
            DOMAIN="$2"
            TUNNEL_NAME="$3"
            shift 3
            ;;
        *)
            print_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run as root"
    exit 1
fi

# Set installation directory based on mode
if [ $DEV_MODE -eq 1 ]; then
    INSTALL_DIR="./photoframe_dev"
    print_warning "Installing in development mode to: $INSTALL_DIR"
else
    INSTALL_DIR="/opt/photoframe"
fi

# Create directory structure
print_status "Creating directory structure..."
mkdir -p $INSTALL_DIR
mkdir -p $INSTALL_DIR/server_photos
mkdir -p $INSTALL_DIR/logs
mkdir -p $INSTALL_DIR/client

# Check and install required system packages
print_status "Checking and installing required system packages..."
apt-get update

PACKAGES="python3 python3-pip python3-venv nginx git"
for pkg in $PACKAGES; do
    if ! dpkg -l | grep -q "^ii  $pkg "; then
        print_status "Installing $pkg..."
        apt-get install -y $pkg
    fi
done

# Clone repository
print_status "Cloning repository..."
git clone --branch $BRANCH $REPO_URL /tmp/photoframe
if [ $? -ne 0 ]; then
    print_error "Failed to clone repository"
    exit 1
fi

# Copy server files
print_status "Copying server files..."
cp -r /tmp/photoframe/server/* $INSTALL_DIR/
cp -r /tmp/photoframe/server/admin/templates $INSTALL_DIR/
cp -r /tmp/photoframe/server/static $INSTALL_DIR/

# Copy client files
print_status "Setting up client files..."
cp -r /tmp/photoframe/client/* $INSTALL_DIR/client/

# Clean up temporary files
rm -rf /tmp/photoframe

# Create virtual environment
print_status "Setting up Python virtual environment..."
python3 -m venv $INSTALL_DIR/venv
source $INSTALL_DIR/venv/bin/activate

# Install Python requirements
print_status "Installing Python requirements..."
$INSTALL_DIR/venv/bin/pip install flask pillow requests werkzeug gunicorn

# Create systemd service file
print_status "Creating systemd service..."
cat > /etc/systemd/system/photoframe.service << EOL
[Unit]
Description=Photo Frame Server
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin"
ExecStart=$INSTALL_DIR/venv/bin/gunicorn --workers 3 --bind unix:photoframe.sock -m 007 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
EOL

# Create WSGI file
print_status "Creating WSGI file..."
cat > $INSTALL_DIR/wsgi.py << EOL
from api import app

if __name__ == "__main__":
    app.run()
EOL

# Create nginx configuration
print_status "Configuring nginx..."
cat > /etc/nginx/sites-available/photoframe << EOL
server {
    listen 80;
    server_name ${DOMAIN:-_};

    location / {
        include proxy_params;
        proxy_pass http://unix:$INSTALL_DIR/photoframe.sock;
    }

    location /static {
        alias $INSTALL_DIR/static;
    }
}
EOL

# Enable nginx site
ln -sf /etc/nginx/sites-available/photoframe /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Set correct permissions
print_status "Setting permissions..."
chown -R www-data:www-data $INSTALL_DIR
chmod -R 755 $INSTALL_DIR

# Create default config if it doesn't exist
if [ ! -f "$INSTALL_DIR/config.json" ]; then
    print_status "Creating default configuration..."
    cat > $INSTALL_DIR/config.json << EOL
{
    "DEV_MODE": false,
    "UPLOAD_FOLDER": "$INSTALL_DIR/server_photos",
    "DATABASE": "$INSTALL_DIR/photo_frame.db",
    "HOST": "0.0.0.0",
    "PORT": 80,
    "ALLOWED_EXTENSIONS": ["png", "jpg", "jpeg"],
    "MAX_CONTENT_LENGTH": 52428800,
    "SECRET_KEY": "$(openssl rand -hex 32)",
    "MATTING_MODE": "white",
    "DISPLAY_TIME": 30,
    "TRANSITION_SPEED": 2,
    "ENABLE_PORTRAIT_PAIRS": true,
    "PORTRAIT_GAP": 20,
    "SORT_MODE": "sequential",
    "CLIENT_VERSION": {
        "display.py": "1.0.0",
        "sync_client.py": "1.0.0"
    }
}
EOL
fi

# Development mode specific configuration
if [ $DEV_MODE -eq 1 ]; then
    print_status "Setting up development configuration..."
    sed -i 's/"DEV_MODE": false/"DEV_MODE": true/' $INSTALL_DIR/config.json
    sed -i 's/"PORT": 80/"PORT": 5000/' $INSTALL_DIR/config.json
    
    # Create development start script
    cat > $INSTALL_DIR/run_dev.sh << EOL
#!/bin/bash
source venv/bin/activate
export FLASK_ENV=development
export FLASK_DEBUG=1
python api.py
EOL
    chmod +x $INSTALL_DIR/run_dev.sh
fi

# Setup SSL if requested
if [ $SETUP_SSL -eq 1 ]; then
    if ! setup_ssl "$DOMAIN" "$SSL_EMAIL"; then
        print_error "SSL setup failed"
    fi
fi

# Setup Cloudflare Tunnel if requested
if [ $SETUP_CLOUDFLARE -eq 1 ]; then
    if ! setup_cloudflare_tunnel "$TUNNEL_NAME"; then
        print_error "Cloudflare Tunnel setup failed"
    fi
fi

# Reload systemd and start services
print_status "Starting services..."
systemctl daemon-reload
systemctl enable photoframe
systemctl restart photoframe
systemctl restart nginx

# Run tests unless skipped
if [ $SKIP_TESTS -eq 0 ]; then
    print_status "Running tests..."
    
    # Test database
    if ! test_database "$INSTALL_DIR/photo_frame.db"; then
        print_error "Database tests failed!"
        exit 1
    fi
    
    # Test network in production mode
    if [ $DEV_MODE -eq 0 ]; then
        if ! test_network 80; then
            print_error "Network tests failed!"
            exit 1
        fi
    fi
    
    # Initialize database
    if ! init_database; then
        print_error "Database initialization failed!"
        exit 1
    fi
    
    # Test API in production mode
    if [ $DEV_MODE -eq 0 ]; then
        if ! test_api; then
            print_error "API tests failed!"
            exit 1
        fi
    fi
fi

# Final instructions
if [ $DEV_MODE -eq 1 ]; then
    print_status "Development installation complete!"
    print_info "To start the development server:"
    print_info "1. cd $INSTALL_DIR"
    print_info "2. ./run_dev.sh"
    print_info "Access the server at: http://localhost:5000"
else
    print_status "Production installation complete!"
    if [ $SETUP_SSL -eq 1 ]; then
        print_info "Access the server at: https://$DOMAIN"
        print_info "SSL certificate will auto-renew via certbot"
    elif [ $SETUP_CLOUDFLARE -eq 1 ]; then
        print_info "Access the server via Cloudflare Tunnel at: https://$DOMAIN"
        print_info "Complete Cloudflare setup with the following commands:"
        print_info "1. cloudflared tunnel login"
        print_info "2. cloudflared tunnel route dns $TUNNEL_NAME $DOMAIN"
    else
        print_info "Access the server at: http://YOUR_SERVER_IP"
    fi
fi

print_info "Useful commands:"
print_info "- View logs: sudo journalctl -u photoframe -f"
print_info "- Restart server: sudo systemctl restart photoframe"
print_info "- Check status: sudo systemctl status photoframe"
print_info "- Initialize database: sudo $INSTALL_DIR/venv/bin/python3 -c 'from database import DatabaseManager; DatabaseManager.init_db()'"

if [ $SKIP_TESTS -eq 1 ]; then
    print_warning "Tests were skipped. Run manual tests with:"
    print_info "sudo $INSTALL_DIR/venv/bin/python3 -c 'from database import DatabaseManager; DatabaseManager.init_db()'"
    print_info "curl http://localhost/api/config"
fi

# Print backup instructions
print_info "\nBackup instructions:"
print_info "1. Database backup:"
print_info "   sudo cp $INSTALL_DIR/photo_frame.db $INSTALL_DIR/photo_frame.db.backup"
print_info "2. Photos backup:"
print_info "   sudo tar -czf photoframe_photos.tar.gz $INSTALL_DIR/server_photos"
print_info "3. Configuration backup:"
print_info "   sudo cp $INSTALL_DIR/config.json $INSTALL_DIR/config.json.backup"

# Print security reminders
print_warning "\nSecurity reminders:"
print_warning "1. Change default passwords"
print_warning "2. Configure firewall rules"
print_warning "3. Keep system updated"

if [ $DEV_MODE -eq 0 ]; then
    print_warning "4. Set up regular backups"
    print_warning "5. Monitor system logs"
fi

exit 0