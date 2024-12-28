import os
import json

# Base directory of the application
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'settings.json')

# Default configuration values
DEFAULT_CONFIG = {
    "DEV_MODE": False,
    "UPLOAD_FOLDER": os.path.join(BASE_DIR, 'uploads'),  # Changed to single uploads directory
    "DATABASE": os.path.join(BASE_DIR, 'photo_frame.db'),  # Removed dev vs prod distinction
    "HOST": 'localhost',  # Default to localhost, updated if FQDN is provided
    "PORT": 5000,
    "ALLOWED_EXTENSIONS": ["png", "jpg", "jpeg"],
    "MAX_CONTENT_LENGTH": 50 * 1024 * 1024,  # 50MB max file size
    "SECRET_KEY": 'dev',
    "MATTING_MODE": 'white',
    "DISPLAY_TIME": 15,
    "TRANSITION_SPEED": 10,
    "ENABLE_PORTRAIT_PAIRS": True,
    "PORTRAIT_GAP": 20,
    "SORT_MODE": "random",
    "CLIENT_VERSION": {
        "display.py": "1.0.5",
        "sync_client.py": "1.0.5"
    }
}

# Load configuration from a JSON file
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    else:
        save_config(DEFAULT_CONFIG)  # Save default if the config file doesn't exist
        return DEFAULT_CONFIG

# Save configuration to a JSON file
def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Load current configuration
current_config = load_config()

# Assign settings dynamically
DEV_MODE = current_config.get("DEV_MODE", DEFAULT_CONFIG["DEV_MODE"])
UPLOAD_FOLDER = (
    os.path.join(BASE_DIR, 'server_photos')
    if DEV_MODE
    else os.path.join(BASE_DIR, 'photo_storage')
)
DATABASE = (
    os.path.join(BASE_DIR, 'dev_photo_frame.db')
    if DEV_MODE
    else os.path.join(BASE_DIR, 'photo_frame.db')
)
HOST = current_config.get("HOST", DEFAULT_CONFIG["HOST"])
PORT = current_config.get("PORT", DEFAULT_CONFIG["PORT"])
ALLOWED_EXTENSIONS = set(current_config.get("ALLOWED_EXTENSIONS", DEFAULT_CONFIG["ALLOWED_EXTENSIONS"]))
MAX_CONTENT_LENGTH = current_config.get("MAX_CONTENT_LENGTH", DEFAULT_CONFIG["MAX_CONTENT_LENGTH"])
SECRET_KEY = (
    'dev'
    if DEV_MODE
    else current_config.get("SECRET_KEY", os.urandom(24))
)
MATTING_MODE = current_config.get("MATTING_MODE", DEFAULT_CONFIG["MATTING_MODE"])
DISPLAY_TIME = current_config.get("DISPLAY_TIME", DEFAULT_CONFIG["DISPLAY_TIME"])
TRANSITION_SPEED = current_config.get("TRANSITION_SPEED", DEFAULT_CONFIG["TRANSITION_SPEED"])
ENABLE_PORTRAIT_PAIRS = current_config.get("ENABLE_PORTRAIT_PAIRS", DEFAULT_CONFIG["ENABLE_PORTRAIT_PAIRS"])
PORTRAIT_GAP = current_config.get("PORTRAIT_GAP", DEFAULT_CONFIG["PORTRAIT_GAP"])

# Update for FQDN
def update_fqdn(fqdn):
    current_config["HOST"] = fqdn
    save_config(current_config)
    print(f"Configuration updated with FQDN: {fqdn}")
