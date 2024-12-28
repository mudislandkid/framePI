import os
import hashlib
import requests
import json
import time
import logging
from datetime import datetime
import uuid
import sqlite3
from PIL import Image, ImageOps
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import subprocess

DEFAULT_SERVER_URL = 'http://192.168.178.164:5000'

__version__ = "1.0.5"

class PowerControlHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/power':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data)
            
            action = data.get('action')
            if action == 'shutdown':
                subprocess.run(['sudo', 'shutdown', '-h', 'now'])
                self.send_response(200)
            elif action == 'restart':
                subprocess.run(['sudo', 'reboot'])
                self.send_response(200)
            else:
                self.send_response(400)
            
            self.end_headers()

def run_control_server():
    server = HTTPServer(('', 5000), PowerControlHandler)
    server.serve_forever()

class PhotoFrameSync:
    def __init__(self, server_url=None, client_id=None):
        # Default server URL
        self.server_url = server_url or DEFAULT_SERVER_URL
        self.server_url = self.server_url.rstrip('/')

        # Start power control server
        self.control_thread = threading.Thread(target=run_control_server, daemon=True)
        self.control_thread.start()

        # Set up logging
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
        logging.basicConfig(
            level=logging.DEBUG,
            format=log_format,
            handlers=[logging.StreamHandler()]
        )
        self.logger = logging.getLogger('PhotoSync')

        # Initialize placeholders for dynamic config
        self.config = {}
        self.photos_dir = None
        self.db_path = None
        self.sync_interval = None
        self.display_order = {}  # Store photo display order from server

        # Load server-side configuration
        self.load_server_config()

        # Initialize storage and database
        self.setup_storage()
        self.init_local_db()

        # Load or generate client ID
        self.client_id = client_id or self.get_client_id()

        self.logger.info(f"\n=== Loaded Config from Server ===")
        self.logger.info(f"Server URL: {self.server_url}")
        self.logger.info(f"Photos directory: {os.path.abspath(self.photos_dir)}")
        self.logger.info(f"Database: {os.path.abspath(self.db_path)}")
        self.logger.info(f"Client ID: {self.client_id}")
        self.logger.info(f"Sync interval: {self.sync_interval} seconds")
        self.logger.info("=================================\n")

    def load_server_config(self):
        """Fetch configuration from the server"""
        try:
            response = requests.get(f'{self.server_url}/api/config')
            response.raise_for_status()
            self.config = response.json()

            # Apply dynamic configuration
            self.photos_dir = self.config.get('PHOTOS_DIR', 'photos')
            self.db_path = os.path.join(self.photos_dir, self.config.get('SYNC_DB_NAME', 'sync.db'))
            self.sync_interval = self.config.get('SYNC_INTERVAL', 300)
            self.dev_mode = self.config.get('DEV_MODE', False)
        except Exception as e:
            self.logger.error(f"Failed to load config from server: {e}")
            raise RuntimeError("Unable to fetch server configuration")

    def setup_storage(self):
        """Create necessary storage directories"""
        try:
            if not os.path.exists(self.photos_dir):
                os.makedirs(self.photos_dir, mode=0o755)  # rwxr-xr-x
                self.logger.info(f"Created photos directory at {self.photos_dir}")
            
            # Ensure correct permissions even if directory exists
            os.chmod(self.photos_dir, 0o755)
            
            # Get the uid and gid for user 'pi'
            import pwd
            pi_user = pwd.getpwnam('pi')
            os.chown(self.photos_dir, pi_user.pw_uid, pi_user.pw_gid)
        except Exception as e:
            self.logger.error(f"Error setting up storage: {e}")

    def init_local_db(self):
        """Initialize local SQLite database for sync tracking"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS sync_info (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS photo_hashes (
                    filename TEXT PRIMARY KEY,
                    file_hash TEXT NOT NULL,
                    photo_id INTEGER NOT NULL,
                    original_filename TEXT,
                    upload_date TIMESTAMP,
                    width INTEGER,
                    height INTEGER,
                    is_portrait BOOLEAN,
                    paired_photo_id INTEGER,
                    last_sync TIMESTAMP
                )
            ''')
            conn.commit()
            self.logger.debug(f"Initialized local database at {self.db_path}")

    def get_client_id(self):
        """Get client ID from RPi serial number or generate one"""
        try:
            # Try to get RPi serial number
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('Serial'):
                        return line.split(':')[1].strip()
        except Exception as e:
            self.logger.warning(f"Could not read RPi serial, using stored ID: {e}")
        
        # Fallback to stored/generated ID
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute('SELECT value FROM sync_info WHERE key = "client_id"')
            result = c.fetchone()
            if result:
                return result[0]
            client_id = str(uuid.uuid4())
            c.execute('INSERT INTO sync_info (key, value) VALUES (?, ?)', ('client_id', client_id))
            conn.commit()
            return client_id

    def calculate_file_hash(self, file_path):
        """Calculate SHA-256 hash of file"""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_local_photo_info(self):
        """Get information about all local photos"""
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute('''
                SELECT file_hash, filename, photo_id, is_portrait, 
                       paired_photo_id, original_filename, width, height
                FROM photo_hashes
            ''')
            return {
                row[0]: {
                    'filename': row[1],
                    'photo_id': row[2],
                    'is_portrait': row[3],
                    'paired_photo_id': row[4],
                    'original_filename': row[5],
                    'width': row[6],
                    'height': row[7]
                }
                for row in c.fetchall()
            }

    def download_photo(self, photo):
        """Download a photo from the server"""
        try:
            response = requests.get(
                f'{self.server_url}/api/photos/{photo["id"]}',
                stream=True
            )
            response.raise_for_status()

            filename = f'photo_{photo["id"]}.jpg'
            file_path = os.path.join(self.photos_dir, filename)

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            width, height, is_portrait = self.get_image_dimensions(file_path)

            # Store photo information in database
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute('''
                    INSERT OR REPLACE INTO photo_hashes 
                    (filename, file_hash, photo_id, original_filename, upload_date,
                     width, height, is_portrait, paired_photo_id, last_sync)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    filename,
                    self.calculate_file_hash(file_path),
                    photo["id"],
                    photo["original_filename"],
                    photo["upload_date"],
                    width,
                    height,
                    is_portrait,
                    photo.get("paired_photo_id"),
                    datetime.now().isoformat()
                ))
                conn.commit()

            self.logger.debug(
                f"Downloaded {filename} ({width}x{height}, {'portrait' if is_portrait else 'landscape'})"
            )

            return True

        except Exception as e:
            self.logger.error(f'Error downloading photo {photo["id"]}: {e}')
            return False

    def cleanup_orphaned_files(self):
        """Remove any files in the photos directory that aren't in the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute('SELECT filename FROM photo_hashes')
                db_files = set(row[0] for row in c.fetchall())

            disk_files = set(f for f in os.listdir(self.photos_dir)
                             if os.path.isfile(os.path.join(self.photos_dir, f))
                             and f != os.path.basename(self.db_path))

            orphaned_files = disk_files - db_files

            for filename in orphaned_files:
                try:
                    file_path = os.path.join(self.photos_dir, filename)
                    os.remove(file_path)
                    self.logger.debug(f"Removed orphaned file: {filename}")
                except Exception as e:
                    self.logger.error(f"Error removing orphaned file {filename}: {e}")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    def sync(self):
        """Perform full sync with server"""
        try:
            self.logger.info('Starting sync...')
            local_photos = self.get_local_photo_info()

            versions = {
                'display.py': self.get_file_version('display.py'),
                'sync_client.py': self.get_file_version('sync_client.py')
            }
            response = requests.post(
                f'{self.server_url}/api/sync',
                json={
                    'client_id': self.client_id,
                    'file_hashes': list(local_photos.keys()),
                    'client_versions': versions
                }
            )
            response.raise_for_status()
            sync_data = response.json()

            # Store the display order from server
            self.display_order = sync_data.get('display_order', {})

            # Handle deletions
            for hash_to_delete in sync_data['to_delete']:
                if hash_to_delete in local_photos:
                    photo_info = local_photos[hash_to_delete]
                    file_path = os.path.join(self.photos_dir, photo_info['filename'])
                    try:
                        os.remove(file_path)
                        with sqlite3.connect(self.db_path) as conn:
                            c = conn.cursor()
                            c.execute('DELETE FROM photo_hashes WHERE file_hash = ?', (hash_to_delete,))
                            conn.commit()
                    except Exception as e:
                        self.logger.error(f"Error deleting file {file_path}: {e}")

            # Handle downloads
            for photo in sync_data['to_download']:
                self.download_photo(photo)

            self.cleanup_orphaned_files()
            self.logger.info('Sync completed successfully')

        except Exception as e:
            self.logger.error(f'Sync failed: {e}')

    def get_image_dimensions(self, file_path):
        """Get image dimensions and determine if it's portrait"""
        try:
            with Image.open(file_path) as img:
                img = ImageOps.exif_transpose(img)  # Correct orientation
                width, height = img.size
                return width, height, height > width
        except Exception as e:
            self.logger.error(f"Error getting image dimensions: {e}")
            return 0, 0, False

        
    def check_for_updates(self):
        """Check and apply code updates"""
        try:
            response = requests.get(f'{self.server_url}/api/client/version')
            response.raise_for_status()
            latest_versions = response.json()
            
            current_dir = os.path.dirname(os.path.abspath(__file__))
            
            for filename, version in latest_versions.items():
                current_version = self.get_file_version(filename)
                if version != current_version:
                    self.logger.info(f"Updating {filename} from {current_version} to {version}")
                    
                    # Get new code
                    response = requests.get(f'{self.server_url}/api/client/code/{filename}')
                    response.raise_for_status()
                    new_code = response.text
                    
                    # Backup existing file
                    backup_path = os.path.join(current_dir, f"{filename}.backup")
                    file_path = os.path.join(current_dir, filename)
                    if os.path.exists(file_path):
                        os.rename(file_path, backup_path)
                    
                    # Write new file
                    with open(file_path, 'w') as f:
                        f.write(new_code)
                    
                    # Set correct ownership and permissions
                    try:
                        # Get the uid and gid for user 'pi'
                        import pwd
                        pi_user = pwd.getpwnam('pi')
                        os.chown(file_path, pi_user.pw_uid, pi_user.pw_gid)
                        # Make executable
                        os.chmod(file_path, 0o755)  # rwxr-xr-x
                    except Exception as e:
                        self.logger.error(f"Error setting file permissions: {e}")
                    
                    self.logger.info(f"Updated {filename}")
                    
                    # Mark for restart if needed
                    if filename == 'sync_client.py':
                        self.restart_needed = True
            
            if self.restart_needed:
                self.logger.info("Updates installed - restarting service...")
                os.execv(sys.executable, ['python'] + sys.argv)
                
        except Exception as e:
            self.logger.error(f"Error checking for updates: {e}")

    def get_file_version(self, filename):
        """Get current version of a file"""
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
            if not os.path.exists(path):
                return "0.0.0"
                
            with open(path, 'r') as f:
                for line in f:
                    if line.startswith('__version__'):
                        return line.split('=')[1].strip().strip('"\'')
        except Exception:
            return "0.0.0"
        return "0.0.0"

def main():
    """Main function to run the sync client"""
    syncer = PhotoFrameSync()
    while True:
        try:
            syncer.sync()  # Perform a sync with the server
        except Exception as e:
            print(f"Error during synchronization: {e}")
        time.sleep(syncer.sync_interval)  # Wait for the defined interval




if __name__ == '__main__':
    main()

