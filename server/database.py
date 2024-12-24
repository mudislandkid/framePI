import sqlite3
import os
import hashlib
from datetime import datetime
from PIL import Image
from config import load_config

class DatabaseManager:
    @staticmethod
    def get_db():
        """Get a database connection with row factory enabled"""
        current_config = load_config()
        conn = sqlite3.connect(current_config["DATABASE"])
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def init_db():
        """Initialize the database with required tables"""
        current_config = load_config()
        os.makedirs(os.path.dirname(current_config["DATABASE"]), exist_ok=True)
        
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            # Photos table stores metadata
            c.execute('''
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    upload_date TIMESTAMP NOT NULL,
                    last_modified TIMESTAMP NOT NULL,
                    size INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    is_portrait BOOLEAN NOT NULL,
                    paired_photo_id INTEGER,
                    active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (paired_photo_id) REFERENCES photos (id)
                )
            ''')
            
            # Add indexes for quicker lookups
            c.execute('''
                CREATE INDEX IF NOT EXISTS idx_portrait_photos 
                ON photos (is_portrait, active)
            ''')
            
            c.execute('''
                CREATE INDEX IF NOT EXISTS idx_photo_pairs
                ON photos (paired_photo_id, active)
            ''')
            
            # Sync_tokens table for tracking client syncs
            c.execute('''
                CREATE TABLE IF NOT EXISTS sync_tokens (
                    client_id TEXT PRIMARY KEY,
                    last_sync TIMESTAMP NOT NULL
                )
            ''')

            # Add client versions table
            c.execute('''
                CREATE TABLE IF NOT EXISTS client_versions (
                    client_id TEXT PRIMARY KEY,
                    display_version TEXT,
                    sync_version TEXT,
                    last_update TIMESTAMP,
                    active BOOLEAN DEFAULT 1
                )
            ''')
            
            conn.commit()

        DatabaseManager.scan_photos_directory()

    @staticmethod
    def setup_storage():
        """Create necessary directories for photo storage"""
        current_config = load_config()
        if not os.path.exists(current_config["UPLOAD_FOLDER"]):
            os.makedirs(current_config["UPLOAD_FOLDER"])
            if current_config["DEV_MODE"]:
                print(f"\nCreated photos directory at: {os.path.abspath(current_config['UPLOAD_FOLDER'])}")

    @staticmethod
    def calculate_file_hash(file_path):
        """Calculate SHA-256 hash of file"""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def get_image_dimensions(file_path):
        """Get image dimensions and determine if it's portrait"""
        try:
            with Image.open(file_path) as img:
                width, height = img.size
                is_portrait = height > width
                return width, height, is_portrait
        except Exception as e:
            print(f"Error getting image dimensions: {e}")
            return 0, 0, False

    @staticmethod
    def add_photo(filename, original_filename, file_path):
        """Add a new photo to the database"""
        try:
            current_config = load_config()
            file_hash = DatabaseManager.calculate_file_hash(file_path)
            file_size = os.path.getsize(file_path)
            width, height, is_portrait = DatabaseManager.get_image_dimensions(file_path)
            
            with DatabaseManager.get_db() as conn:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO photos (
                        filename, original_filename, file_hash, 
                        upload_date, last_modified, size,
                        width, height, is_portrait, active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ''', (filename, original_filename, file_hash, 
                     datetime.now(), datetime.now(), file_size,
                     width, height, is_portrait))
                photo_id = c.lastrowid
                
                # If portrait pairing is enabled and it's a portrait photo
                if current_config["ENABLE_PORTRAIT_PAIRS"] and is_portrait:
                    DatabaseManager.find_portrait_pair(c, photo_id)
                
                conn.commit()
                return photo_id
        except Exception as e:
            print(f"Error adding photo: {e}")
            return None

    @staticmethod
    def find_portrait_pair(cursor, photo_id):
        """Find an unpaired portrait photo to pair with"""
        try:
            # Look for an unpaired portrait photo
            cursor.execute('''
                SELECT id FROM photos 
                WHERE is_portrait = 1 
                AND active = 1 
                AND paired_photo_id IS NULL 
                AND id != ?
                ORDER BY upload_date DESC
                LIMIT 1
            ''', (photo_id,))
            
            potential_pair = cursor.fetchone()
            if potential_pair:
                pair_id = potential_pair[0]
                # Update both photos to be paired
                cursor.execute('''
                    UPDATE photos 
                    SET paired_photo_id = ?
                    WHERE id = ?
                ''', (pair_id, photo_id))
                
                cursor.execute('''
                    UPDATE photos 
                    SET paired_photo_id = ?
                    WHERE id = ?
                ''', (photo_id, pair_id))
        except Exception as e:
            print(f"Error finding portrait pair: {e}")

    @staticmethod
    def unpair_photo(photo_id):
        """Remove pairing for a photo"""
        try:
            with DatabaseManager.get_db() as conn:
                c = conn.cursor()
                # First get the paired photo ID
                c.execute('SELECT paired_photo_id FROM photos WHERE id = ?', (photo_id,))
                result = c.fetchone()
                if result and result['paired_photo_id']:
                    paired_id = result['paired_photo_id']
                    # Remove pairing from both photos
                    c.execute('''
                        UPDATE photos 
                        SET paired_photo_id = NULL 
                        WHERE id IN (?, ?)
                    ''', (photo_id, paired_id))
                    conn.commit()
                    return True
            return False
        except Exception as e:
            print(f"Error unpairing photo: {e}")
            return False

    @staticmethod
    def get_all_photos(order_by=None):
        """Get all photos with optional ordering"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            
            base_query = '''
                SELECT id, filename, file_hash, original_filename, upload_date, 
                       last_modified, size, width, height, is_portrait, paired_photo_id
                FROM photos 
                WHERE active = 1
            '''
            
            # Handle different sort modes
            if order_by == 'RANDOM()':
                query = f"{base_query} ORDER BY RANDOM()"
            elif order_by == 'upload_date DESC':
                query = f"{base_query} ORDER BY upload_date DESC"
            elif order_by == 'upload_date ASC':
                query = f"{base_query} ORDER BY upload_date ASC"
            elif order_by == 'filename':
                query = f"{base_query} ORDER BY filename"
            else:
                query = base_query
            
            c.execute(query)
            
            return [{
                'id': row[0],
                'filename': row[1],
                'file_hash': row[2],
                'original_filename': row[3],
                'upload_date': row[4],
                'last_modified': row[5],
                'size': row[6],
                'width': row[7],
                'height': row[8],
                'is_portrait': bool(row[9]),
                'paired_photo_id': row[10]
            } for row in c.fetchall()]

    @staticmethod
    def get_all_photos_with_pairs():
        """Get all active photos with optional pairing information."""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            
            # Base query for all active photos
            query = '''
                SELECT 
                    p.id, p.filename, p.original_filename, p.size, p.upload_date, 
                    p.is_portrait, p.paired_photo_id, p.active,
                    pp.id AS pair_id, pp.filename AS pair_filename, 
                    pp.original_filename AS pair_original_filename
                FROM photos p
                LEFT JOIN photos pp ON p.paired_photo_id = pp.id
                WHERE p.active = 1
                ORDER BY p.upload_date DESC
            '''
            c.execute(query)
            rows = c.fetchall()
            
            # Convert rows to dictionaries
            photos = []
            for row in rows:
                photo = {
                    'id': row['id'],
                    'filename': row['filename'],
                    'original_filename': row['original_filename'],
                    'size': row['size'],
                    'upload_date': row['upload_date'],
                    'is_portrait': row['is_portrait'],
                    'paired_photo': None,
                }
                if row['pair_id']:
                    photo['paired_photo'] = {
                        'id': row['pair_id'],
                        'filename': row['pair_filename'],
                        'original_filename': row['pair_original_filename']
                    }
                photos.append(photo)
            
            return photos

    @staticmethod
    def get_photo_by_id(photo_id):
        """Get a single photo by ID"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM photos WHERE id = ? AND active = 1', (photo_id,))
            return c.fetchone()

    @staticmethod
    def soft_delete_photo(photo_id):
        """Mark a photo as inactive (soft delete) and handle its pair"""
        try:
            with DatabaseManager.get_db() as conn:
                c = conn.cursor()
                # First unpair the photo if it's paired
                DatabaseManager.unpair_photo(photo_id)
                
                # Then soft delete the photo
                c.execute('UPDATE photos SET active = 0 WHERE id = ?', (photo_id,))
                conn.commit()
                return c.rowcount > 0
        except Exception as e:
            print(f"Error soft deleting photo: {e}")
            return False

    @staticmethod
    def get_photo_stats():
        """Get basic statistics about photos"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            stats = {}
            
            # Total active photos
            c.execute('SELECT COUNT(*) as count FROM photos WHERE active = 1')
            stats['active_photos'] = c.fetchone()['count']
            
            # Total portrait photos
            c.execute('''
                SELECT COUNT(*) as count 
                FROM photos 
                WHERE active = 1 AND is_portrait = 1
            ''')
            stats['portrait_photos'] = c.fetchone()['count']
            
            # Total paired photos
            c.execute('''
                SELECT COUNT(*) as count 
                FROM photos 
                WHERE active = 1 AND paired_photo_id IS NOT NULL
            ''')
            stats['paired_photos'] = c.fetchone()['count']
            
            # Total storage used
            c.execute('SELECT SUM(size) as total FROM photos WHERE active = 1')
            stats['total_size'] = c.fetchone()['total'] or 0
            
            # Photos per day (last 7 days)
            c.execute('''
                SELECT date(upload_date) as day, COUNT(*) as count 
                FROM photos 
                WHERE active = 1 
                AND upload_date >= date('now', '-7 days')
                GROUP BY day 
                ORDER BY day DESC
            ''')
            stats['recent_uploads'] = [dict(row) for row in c.fetchall()]
            
            return stats

    @staticmethod
    def get_sync_info(client_id):
        """Get sync information for a client"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM sync_tokens WHERE client_id = ?', (client_id,))
            return c.fetchone()

    @staticmethod
    def update_sync_token(client_id, client_versions=None):
        """Update the last sync time for a client and store version info"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            
            # Update sync token
            c.execute('''
                INSERT OR REPLACE INTO sync_tokens (client_id, last_sync)
                VALUES (?, ?)
            ''', (client_id, datetime.now()))

            # If client versions provided, update them
            if client_versions:
                c.execute('''
                    CREATE TABLE IF NOT EXISTS client_versions (
                        client_id TEXT PRIMARY KEY,
                        display_version TEXT,
                        sync_version TEXT,
                        last_update TIMESTAMP
                    )
                ''')
                
                c.execute('''
                    INSERT OR REPLACE INTO client_versions 
                    (client_id, display_version, sync_version, last_update)
                    VALUES (?, ?, ?, ?)
                ''', (
                    client_id,
                    client_versions.get('display.py', 'unknown'),
                    client_versions.get('sync_client.py', 'unknown'),
                    datetime.now()
                ))
            
            conn.commit()

    @staticmethod
    def update_client_versions(client_id, client_versions=None):
        """Update client version information"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS client_versions (
                    client_id TEXT PRIMARY KEY,
                    display_version TEXT,
                    sync_version TEXT,
                    last_update TIMESTAMP,
                    last_ip TEXT
                )
            ''')
            
            # Get client IP from request
            from flask import request
            client_ip = request.remote_addr
            
            c.execute('''
                INSERT OR REPLACE INTO client_versions 
                (client_id, display_version, sync_version, last_update, last_ip)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                client_id,
                client_versions.get('display.py', 'unknown'),
                client_versions.get('sync_client.py', 'unknown'),
                datetime.now(),
                client_ip
            ))
            conn.commit()

    @staticmethod
    def get_client_versions(client_id):
        """Get client version information"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM client_versions WHERE client_id = ?', (client_id,))
            row = c.fetchone()
            if row:
                return {
                    'display_version': row['display_version'],
                    'sync_version': row['sync_version'],
                    'last_update': row['last_update']
                }
            return None
        
    @staticmethod
    def get_all_client_versions():
        """Get all client versions"""
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT * FROM client_versions 
                ORDER BY last_update DESC
            ''')
            return [dict(row) for row in c.fetchall()]
        

    @staticmethod
    def scan_photos_directory():
        """Scan photos directory and add any missing photos to database"""
        current_config = load_config()
        photos_dir = current_config["UPLOAD_FOLDER"]
        
        try:
            for filename in os.listdir(photos_dir):
                if filename.endswith(('.jpg', '.jpeg', '.png')):
                    file_path = os.path.join(photos_dir, filename)
                    
                    # Check if photo already exists in database
                    with DatabaseManager.get_db() as conn:
                        c = conn.cursor()
                        c.execute('SELECT id FROM photos WHERE filename = ?', (filename,))
                        if not c.fetchone():
                            # If not in database, add it
                            DatabaseManager.add_photo(
                                filename=filename,
                                original_filename=filename,  # Use filename as original_filename
                                file_path=file_path
                            )
                            print(f"Added existing photo: {filename}")
        except Exception as e:
            print(f"Error scanning photos directory: {e}")