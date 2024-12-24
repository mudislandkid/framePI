from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from config import (
    load_config, save_config, UPLOAD_FOLDER, ALLOWED_EXTENSIONS, 
    MATTING_MODE, DISPLAY_TIME, TRANSITION_SPEED, ENABLE_PORTRAIT_PAIRS, 
    PORTRAIT_GAP
)
from database import DatabaseManager

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@admin_bp.route('/')
def index():
    photos = DatabaseManager.get_all_photos_with_pairs()
    return render_template('admin/index.html', photos=photos)

@admin_bp.route('/upload', methods=['POST'])
def upload():
    if 'photos' not in request.files:
        flash('No photos selected', 'error')
        return redirect(url_for('admin.index'))
    
    files = request.files.getlist('photos')
    if not files or files[0].filename == '':
        flash('No photos selected', 'error')
        return redirect(url_for('admin.index'))
    
    success_count = 0
    error_count = 0
    
    for file in files:
        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{original_filename}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            
            file.save(file_path)
            photo_id = DatabaseManager.add_photo(filename, original_filename, file_path)
            if photo_id:
                success_count += 1
            else:
                error_count += 1
        else:
            error_count += 1
    
    if success_count > 0:
        flash(f'Successfully uploaded {success_count} photo{"s" if success_count != 1 else ""}', 'success')
    if error_count > 0:
        flash(f'Failed to upload {error_count} photo{"s" if success_count != 1 else ""} (invalid file type)', 'error')
    
    return redirect(url_for('admin.index'))

@admin_bp.route('/delete/<int:photo_id>', methods=['POST'])
def delete(photo_id):
    if DatabaseManager.soft_delete_photo(photo_id):
        flash('Photo deleted successfully', 'success')
    else:
        flash('Photo not found', 'error')
    return redirect(url_for('admin.index'))

@admin_bp.route('/settings')
def settings():
    current_config = load_config()

    # Get latest versions from server config
    latest_versions = current_config.get("CLIENT_VERSION", {
        "display.py": "unknown",
        "sync_client.py": "unknown"
    })
    
    # Get all client versions
    clients = DatabaseManager.get_all_client_versions()

    return render_template(
        'admin/settings.html', 
        matting_mode=current_config["MATTING_MODE"],
        display_time=current_config["DISPLAY_TIME"],
        transition_speed=current_config["TRANSITION_SPEED"],
        enable_portrait_pairs=current_config["ENABLE_PORTRAIT_PAIRS"],
        portrait_gap=current_config["PORTRAIT_GAP"],
        dev_mode=current_config["DEV_MODE"],
        server_address=current_config["HOST"],
        server_port=current_config["PORT"],
        sort_mode=current_config["SORT_MODE"],
        latest_versions=latest_versions,
        clients=clients
    )

@admin_bp.route('/settings/update', methods=['POST'])
def update_settings():
    try:
        # Load current configuration
        current_config = load_config()

        # Update values from the form
        current_config["MATTING_MODE"] = request.form.get('matting_mode', 'white')
        current_config["DISPLAY_TIME"] = float(request.form.get('display_time', 30))
        current_config["TRANSITION_SPEED"] = float(request.form.get('transition_speed', 2))
        current_config["ENABLE_PORTRAIT_PAIRS"] = request.form.get('enable_portrait_pairs') == 'on'
        current_config["PORTRAIT_GAP"] = int(request.form.get('portrait_gap', 20))
        current_config["DEV_MODE"] = request.form.get('dev_mode') == 'on'
        current_config["HOST"] = request.form.get('server_address', '127.0.0.1')
        current_config["PORT"] = int(request.form.get('server_port', 5000))
        current_config["SORT_MODE"] = request.form.get('sort_mode', 'sequential')  # Add this line

        # Validate numeric values
        if not (5 <= current_config["DISPLAY_TIME"] <= 300):
            raise ValueError('Display time must be between 5 and 300 seconds')
        if not (1 <= current_config["TRANSITION_SPEED"] <= 30):
            raise ValueError('Transition time must be between 1 and 30 seconds')
        if not (0 <= current_config["PORTRAIT_GAP"] <= 100):
            raise ValueError('Portrait gap must be between 0 and 100 pixels')
        
        # Validate sort mode
        if current_config["SORT_MODE"] not in ['sequential', 'random', 'newest', 'oldest']:
            raise ValueError('Invalid sort mode')

        # Save updated configuration
        save_config(current_config)

        flash('Settings updated successfully', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        flash(f'Error updating settings: {str(e)}', 'error')
    
    return redirect(url_for('admin.settings'))

@admin_bp.route('/unpair/<int:photo_id>', methods=['POST'])
def unpair_photo(photo_id):
    """Endpoint to manually unpair a portrait photo"""
    if DatabaseManager.unpair_photo(photo_id):
        flash('Photo unpaired successfully', 'success')
    else:
        flash('Failed to unpair photo', 'error')
    return redirect(url_for('admin.index'))

@admin_bp.route('/pair/<int:photo_id1>/<int:photo_id2>', methods=['POST'])
def pair_photos(photo_id1, photo_id2):
    """Endpoint to manually pair two portrait photos"""
    try:
        with DatabaseManager.get_db() as conn:
            c = conn.cursor()
            # First unpair both photos if they're paired
            DatabaseManager.unpair_photo(photo_id1)
            DatabaseManager.unpair_photo(photo_id2)
            
            # Then pair them together
            c.execute('''
                UPDATE photos 
                SET paired_photo_id = ?
                WHERE id = ?
            ''', (photo_id2, photo_id1))
            
            c.execute('''
                UPDATE photos 
                SET paired_photo_id = ?
                WHERE id = ?
            ''', (photo_id1, photo_id2))
            
            conn.commit()
            flash('Photos paired successfully', 'success')
    except Exception as e:
        flash(f'Failed to pair photos: {str(e)}', 'error')
    
    return redirect(url_for('admin.index'))
