from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from config import load_config, BASE_DIR, ALLOWED_EXTENSIONS
from database import DatabaseManager
from admin import admin_bp
import requests

def create_app():
    app = Flask(__name__)
    
    # Load configuration dynamically
    current_config = load_config()
    app.config['UPLOAD_FOLDER'] = current_config["UPLOAD_FOLDER"]
    app.config['MAX_CONTENT_LENGTH'] = current_config["MAX_CONTENT_LENGTH"]
    app.secret_key = current_config["SECRET_KEY"]

    # Initialize storage and database
    DatabaseManager.setup_storage()
    DatabaseManager.init_db()

    # Register the admin blueprint
    app.register_blueprint(admin_bp)

    # Define all routes
    @app.route('/')
    def index():
        photos = DatabaseManager.get_all_photos_with_pairs()
        return render_template('admin/index.html', photos=photos)
    
    @app.route('/api/photos', methods=['POST'])
    def upload_photo():
        if 'photo' not in request.files:
            return jsonify({'error': 'No photo part'}), 400
        
        file = request.files['photo']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{original_filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            file.save(file_path)
            photo_id = DatabaseManager.add_photo(filename, original_filename, file_path)
            
            return jsonify({
                'message': 'Photo uploaded successfully',
                'filename': filename,
                'id': photo_id
            }), 201
        
        return jsonify({'error': 'Invalid file type'}), 400

    @app.route('/api/photos', methods=['GET'])
    def list_photos():
        photos = DatabaseManager.get_all_photos()
        return jsonify([{
            'id': p['id'],
            'filename': p['filename'],
            'original_filename': p['original_filename'],
            'file_hash': p['file_hash'],
            'upload_date': p['upload_date'],
            'last_modified': p['last_modified'],
            'size': p['size'],
            'width': p['width'],
            'height': p['height'],
            'is_portrait': p['is_portrait'],
            'paired_photo_id': p['paired_photo_id']
        } for p in photos])

    @app.route('/api/photos/<int:photo_id>', methods=['GET'])
    def get_photo(photo_id):
        photo = DatabaseManager.get_photo_by_id(photo_id)
        if photo is None:
            return jsonify({'error': 'Photo not found'}), 404
        
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], photo['filename']),
            mimetype='image/jpeg'
        )

    @app.route('/api/photos/<int:photo_id>', methods=['DELETE'])
    def delete_photo(photo_id):
        if DatabaseManager.soft_delete_photo(photo_id):
            return jsonify({'message': 'Photo deleted successfully'})
        return jsonify({'error': 'Photo not found'}), 404

    @app.route('/api/sync', methods=['POST'])
    def sync_client():
        client_id = request.json.get('client_id')
        client_hashes = request.json.get('file_hashes', [])
        client_versions = request.json.get('client_versions', {})
        
        if not client_id:
            return jsonify({'error': 'Client ID required'}), 400
        
        current_config = load_config()
        sort_mode = current_config.get('sort_mode', 'sequential')
        
        # Get sorted photos based on mode
        if sort_mode == 'random':
            photos = DatabaseManager.get_all_photos(order_by='RANDOM()')
        elif sort_mode == 'newest':
            photos = DatabaseManager.get_all_photos(order_by='upload_date DESC')
        elif sort_mode == 'oldest':
            photos = DatabaseManager.get_all_photos(order_by='upload_date ASC')
        else:  # sequential
            photos = DatabaseManager.get_all_photos(order_by='filename')

        # Create the photos_to_download list with display order included
        photos_to_download = []
        for idx, photo in enumerate(photos):
            if photo['file_hash'] not in client_hashes:
                photo_info = {
                    'id': photo['id'],
                    'filename': photo['filename'],
                    'hash': photo['file_hash'],
                    'size': photo['size'],
                    'is_portrait': photo['is_portrait'],
                    'paired_photo_id': photo['paired_photo_id'],
                    'original_filename': photo['original_filename'],
                    'upload_date': photo['upload_date']
                }
                photos_to_download.append(photo_info)
        
        # Calculate photos to delete
        photos_to_delete = [h for h in client_hashes if h not in {p['file_hash'] for p in photos}]
        
        # Update sync token with version information
        DatabaseManager.update_sync_token(client_id, client_versions)
        
        # Create the display order mapping
        display_order = {p['file_hash']: idx for idx, p in enumerate(photos)}
        
        return jsonify({
            'to_download': photos_to_download,
            'to_delete': photos_to_delete,
            'display_order': display_order
        })

    @app.route('/api/dev/status', methods=['GET'])
    def dev_status():
        """Development endpoint to check server status and configuration"""
        current_config = load_config()
        if not current_config["DEV_MODE"]:
            return jsonify({'error': 'Development endpoints disabled'}), 403
        
        stats = DatabaseManager.get_photo_stats()
        
        return jsonify({
            'status': 'running',
            'dev_mode': current_config["DEV_MODE"],
            'upload_folder': os.path.abspath(current_config["UPLOAD_FOLDER"]),
            'database_path': os.path.abspath(current_config["DATABASE"]),
            'photo_count': stats['active_photos'],
            'portrait_count': stats['portrait_photos'],
            'paired_count': stats['paired_photos'],
            'server_url': f"http://{current_config['HOST']}:{current_config['PORT']}"
        })

    @app.route('/api/config', methods=['GET'])
    def get_config():
        """Get display configuration"""
        current_config = load_config()
        return jsonify({
            'matting_mode': current_config["MATTING_MODE"],
            'display_time': current_config["DISPLAY_TIME"],
            'transition_speed': current_config["TRANSITION_SPEED"],
            'enable_portrait_pairs': current_config["ENABLE_PORTRAIT_PAIRS"],
            'portrait_gap': current_config["PORTRAIT_GAP"],
            'sort_mode': current_config["SORT_MODE"]
        })

    @app.route('/api/client/version')
    def get_client_version():
        """Get latest client code versions"""
        current_config = load_config()
        return jsonify(current_config["CLIENT_VERSION"])

    @app.route('/api/client/code/<filename>')
    def get_client_code(filename):
        """Serve client code files"""
        if filename not in ['display.py', 'sync_client.py']:
            return jsonify({'error': 'Invalid file'}), 404
            
        try:
            with open(os.path.join(BASE_DIR, 'client', filename), 'r') as f:
                return f.read(), 200, {'Content-Type': 'text/plain'}
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        
    @app.route('/api/client/<client_id>/power', methods=['POST'])
    def control_client(client_id):
        action = request.json.get('action')
        if action not in ['shutdown', 'restart']:
            return jsonify({'error': 'Invalid action'}), 400
        
        # Find client IP from database
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT last_ip FROM client_versions WHERE client_id = ?', (client_id,))
            result = c.fetchone()
            if not result:
                return jsonify({'error': 'Client not found'}), 404
            
            # Send command to client
            try:
                response = requests.post(
                    f'http://{result["last_ip"]}:5000/power',
                    json={'action': action},
                    timeout=5
                )
                response.raise_for_status()
                return jsonify({'message': f'{action} command sent successfully'})
            except Exception as e:
                return jsonify({'error': f'Failed to send command: {str(e)}'}), 500

    return app

def allowed_file(filename):
    """Check if filename has an allowed extension.
    The function is case-insensitive and properly handles files without extensions."""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in (ext.lower() for ext in ALLOWED_EXTENSIONS)

# Create the Flask application
flask_app = create_app()

# For production with uvicorn, we need to wrap the Flask app
try:
    from asgiref.wsgi import WsgiToAsgi
    app = WsgiToAsgi(flask_app)
except ImportError:
    app = flask_app

if __name__ == '__main__':
    current_config = load_config()
    if current_config["DEV_MODE"]:
        print("\n=== Running in DEVELOPMENT mode ===")
        print(f"Server URL: http://{current_config['HOST']}:{current_config['PORT']}")
        print(f"Photos directory: {os.path.abspath(current_config['UPLOAD_FOLDER'])}")
        print(f"Database: {os.path.abspath(current_config['DATABASE'])}")
        print("\nTest the server with:")
        print(f"  curl http://{current_config['HOST']}:{current_config['PORT']}/api/dev/status")
        print("\nDevelopment endpoints enabled")
        print("=================================\n")
        
        flask_app.run(debug=current_config["DEV_MODE"], 
                     host=current_config["HOST"], 
                     port=current_config["PORT"])
    else:
        print("\n=== Running in PRODUCTION mode ===")
        print(f"Photos directory: {os.path.abspath(current_config['UPLOAD_FOLDER'])}")
        print(f"Database: {os.path.abspath(current_config['DATABASE'])}")
        print("The application will be served by uvicorn")
        print("=================================\n")