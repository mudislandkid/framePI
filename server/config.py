import os
import json

# Base directory of the application
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'settings.json')

# Default configuration values
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

def ensure_directories():
    """Ensure all required directories exist with proper permissions"""
    dirs = [
        os.path.dirname(CONFIG_FILE),
        os.path.join(BASE_DIR, 'uploads'),
        os.path.join(BASE_DIR, 'static'),
        os.path.join(BASE_DIR, 'logs')
    ]
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d, mode=0o775, exist_ok=True)
        os.chmod(d, 0o775)  # Ensure directory is writable
        # Assuming the script is run as root during installation
        import pwd
        import grp
        uid = pwd.getpwnam('www-data').pw_uid
        gid = grp.getgrnam('www-data').gr_gid
        os.chown(d, uid, gid)

def load_config():
    """Load configuration from JSON file with dynamic path handling"""
    ensure_directories()
    
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            loaded_config = json.load(f)
            
            # Always ensure DEV_MODE is properly set
            dev_mode = loaded_config.get("DEV_MODE", DEFAULT_CONFIG["DEV_MODE"])
            
            # Set paths based on mode
            loaded_config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, 'uploads')  # Always use uploads
            loaded_config["DATABASE"] = os.path.join(
                BASE_DIR,
                'dev_photo_frame.db' if dev_mode else 'photo_frame.db'
            )
            
            # Merge with defaults to ensure all required keys exist
            config = DEFAULT_CONFIG.copy()
            config.update(loaded_config)
            return config
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(config):
    """Save configuration to JSON file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Load current configuration
current_config = load_config()

# Assign settings dynamically
DEV_MODE = current_config["DEV_MODE"]
UPLOAD_FOLDER = current_config["UPLOAD_FOLDER"]  # Always uses 'uploads' directory
DATABASE = current_config["DATABASE"]
HOST = current_config["HOST"]
PORT = current_config["PORT"]
ALLOWED_EXTENSIONS = set(current_config["ALLOWED_EXTENSIONS"])
MAX_CONTENT_LENGTH = current_config["MAX_CONTENT_LENGTH"]
SECRET_KEY = 'dev' if DEV_MODE else current_config.get("SECRET_KEY", os.urandom(24))

# Display settings
MATTING_MODE = current_config["MATTING_MODE"]
DISPLAY_TIME = current_config["DISPLAY_TIME"]
TRANSITION_SPEED = current_config["TRANSITION_SPEED"]
ENABLE_PORTRAIT_PAIRS = current_config["ENABLE_PORTRAIT_PAIRS"]
PORTRAIT_GAP = current_config["PORTRAIT_GAP"]
SORT_MODE = current_config["SORT_MODE"]

def update_fqdn(fqdn):
    """Update FQDN in configuration"""
    global current_config, HOST
    current_config["HOST"] = fqdn
    HOST = fqdn
    save_config(current_config)
    print(f"Configuration updated with FQDN: {fqdn}")

def update_dev_mode(dev_mode):
    """Update development mode settings"""
    global current_config, DEV_MODE, DATABASE
    current_config["DEV_MODE"] = dev_mode
    DEV_MODE = dev_mode
    
    # Update database path based on mode
    DATABASE = os.path.join(BASE_DIR, 'dev_photo_frame.db' if dev_mode else 'photo_frame.db')
    current_config["DATABASE"] = DATABASE
    
    save_config(current_config)
    ensure_directories()
    
    return current_config