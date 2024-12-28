import pygame
import sys
import time
import os
from PIL import Image, ImageOps
import numpy as np
from sync_client import PhotoFrameSync
import threading
import requests
import subprocess

__version__ = "1.0.5"

class PhotoDisplay:
    def __init__(self):
        # Enable hardware acceleration if available
        os.environ['SDL_VIDEODRIVER'] = 'x11'  # For Linux/Raspberry Pi
        # Disable audio to prevent ALSA errors
        os.environ['SDL_AUDIODRIVER'] = 'dummy'
        
        # Enable hardware acceleration if available
        os.environ['SDL_VIDEODRIVER'] = 'x11'
        
        pygame.init()
        pygame.display.init()
        
        # Try to enable OpenGL
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4)
        
        # Initialize the sync client
        self.sync_client = PhotoFrameSync()
        self.photos_dir = self.sync_client.photos_dir
        self.config = {
            'matting_mode': 'white',
            'display_time': 30,
            'transition_speed': 2,
            'enable_portrait_pairs': True,
            'portrait_gap': 20,
            'sort_mode': 'sequential'
        }

        # Dynamically get screen resolution
        self.WIDTH, self.HEIGHT = self.get_screen_resolution()

        # Set up pygame display
        if self.sync_client.dev_mode:
            self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
            pygame.display.set_caption('Photo Frame (Development Mode)')
        else:
            os.putenv('SDL_FBDEV', '/dev/fb0')
            self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT), pygame.FULLSCREEN | pygame.DOUBLEBUF)
            pygame.display.toggle_fullscreen()

        # Initialize other variables
        self.display_time = self.config['display_time']
        self.transition_duration = self.config['transition_speed']
        self.current_surfaces = []  # Can hold one or two surfaces
        self.next_surfaces = []  # Can hold one or two surfaces
        self.current_images = []  # Store PIL images for color calculation
        self.transition_start_time = None
        self.transitioning = False
        self.current_photo_paths = None
        self.current_photo = None
        self.preloading = False
        self.preloaded_surfaces = None
        self.preloaded_bg_color = None

        self.current_bg_color = self.get_background_color(None)
        self.next_bg_color = self.get_background_color(None)
        self.last_update = time.time() - (self.display_time + 1)
        self.update_config(self.get_server_config())

        self.sync_thread = threading.Thread(target=self.run_sync, daemon=True)
        self.sync_thread.start()

        self.config_thread = threading.Thread(target=self.run_config_update, daemon=True)
        self.config_thread.start()

    def get_screen_resolution(self):
        """Determine the native screen resolution dynamically."""
        try:
            output = subprocess.check_output(['xrandr']).decode('utf-8')
            for line in output.splitlines():
                if '*' in line:  # Resolution line has an asterisk (*)
                    resolution = line.split()[0]
                    width, height = map(int, resolution.split('x'))
                    return width, height
        except Exception as e:
            print(f"Error getting screen resolution: {e}")
            return 1280, 800  # WXGA resolution as a fallback

    def get_next_photo_paths(self):
        """Get next photo paths to display"""
        try:
            # Get all photo files and sort them according to server's display order
            photo_files = sorted(
                [f for f in os.listdir(self.photos_dir) 
                 if f.endswith(('.jpg', '.jpeg', '.png')) and 
                 os.path.isfile(os.path.join(self.photos_dir, f))],
                key=lambda x: self.sync_client.display_order.get(x, float('inf'))
            )

            if not photo_files:
                return None, None

            if self.current_photo in photo_files:
                next_index = (photo_files.index(self.current_photo) + 1) % len(photo_files)
            else:
                next_index = 0

            next_photo = photo_files[next_index]
            self.current_photo = next_photo
            next_path = os.path.join(self.photos_dir, next_photo)

            if self.config.get('enable_portrait_pairs', True):
                try:
                    with Image.open(next_path) as img:
                        width, height = img.size
                        is_portrait = height > width

                        if is_portrait:
                            remaining_photos = photo_files.copy()
                            remaining_photos.remove(next_photo)

                            for potential_pair in remaining_photos:
                                pair_path = os.path.join(self.photos_dir, potential_pair)
                                with Image.open(pair_path) as pair_img:
                                    pair_width, pair_height = pair_img.size
                                    if pair_height > pair_width:
                                        return next_path, pair_path
                except Exception as e:
                    print(f"Error checking portrait orientation: {e}")

            return next_path, None

        except Exception as e:
            print(f"Error getting next photo: {e}")
            return None, None

    def _get_smooth_progress(self, progress):
        """Apply easing function to progress for smoother transitions"""
        # Cubic easing function for smoother transitions
        return progress * progress * (3 - 2 * progress)

    def update_display(self):
        current_time = time.time()

        # Start preloading next image when we're halfway through display time
        if not self.transitioning and not self.preloading:
            if current_time - self.last_update >= (self.display_time / 2):
                self.preload_next_image()

        if not self.transitioning:
            if current_time - self.last_update >= self.display_time:
                if self.preloaded_surfaces:
                    self.next_surfaces = self.preloaded_surfaces
                    self.next_bg_color = self.preloaded_bg_color
                    self.preloaded_surfaces = None
                    self.preloaded_bg_color = None
                    self.preloading = False
                    if self.next_surfaces:
                        self.transitioning = True
                        self.transition_start_time = current_time
                else:
                    next_paths = self.get_next_photo_paths()
                    if next_paths[0]:
                        self.next_surfaces, self.next_bg_color = self.load_image(next_paths)
                        if self.next_surfaces:
                            self.transitioning = True
                            self.transition_start_time = current_time
                            self.current_photo_paths = next_paths

        if self.transitioning:
            elapsed = current_time - self.transition_start_time
            raw_progress = min(1.0, elapsed / self.transition_duration)
            
            # Apply smoothing to the progress
            smooth_progress = self._get_smooth_progress(raw_progress)

            if raw_progress >= 1.0:
                self.transitioning = False
                self.current_surfaces = self.next_surfaces
                self.current_bg_color = self.next_bg_color
                self.next_surfaces = []
                self.last_update = current_time
                self.preloading = False
            else:
                self._draw_frame(smooth_progress)
        else:
            self._draw_frame(1.0)

    def preload_next_image(self):
        """Preload the next image to ensure smooth transitions"""
        try:
            next_paths = self.get_next_photo_paths()
            if next_paths[0]:
                self.preloaded_surfaces, self.preloaded_bg_color = self.load_image(next_paths)
                self.preloading = True
                self.current_photo_paths = next_paths
        except Exception as e:
            print(f"Error preloading next image: {e}")

    def update_display_parameters(self):
        """Update display parameters based on config"""
        self.display_time = max(5, min(300, self.config.get('display_time', 30)))
        self.transition_duration = max(1, min(30, self.config.get('transition_speed', 2)))

    def validate_config(self, config):
        """Validate and sanitize config values"""
        validated = {}
        
        # Validate sort mode
        sort_mode = config.get('sort_mode', 'sequential')
        if sort_mode not in ['sequential', 'random', 'newest', 'oldest']:
            sort_mode = 'sequential'
        validated['sort_mode'] = sort_mode

        # Validate matting mode
        matting_mode = config.get('matting_mode', 'white')
        if matting_mode not in ['auto', 'black', 'white']:
            matting_mode = 'white'
        validated['matting_mode'] = matting_mode

        # Validate display time
        display_time = config.get('display_time', 30)
        try:
            display_time = float(display_time)
            display_time = max(5, min(300, display_time))
        except (TypeError, ValueError):
            display_time = 30
        validated['display_time'] = display_time

        # Validate transition speed
        transition_speed = config.get('transition_speed', 2)
        try:
            transition_speed = float(transition_speed)
            transition_speed = max(1, min(30, transition_speed))
        except (TypeError, ValueError):
            transition_speed = 2
        validated['transition_speed'] = transition_speed

        validated['enable_portrait_pairs'] = bool(config.get('enable_portrait_pairs', True))

        portrait_gap = config.get('portrait_gap', 20)
        try:
            portrait_gap = int(portrait_gap)
            portrait_gap = max(0, min(100, portrait_gap))
        except (TypeError, ValueError):
            portrait_gap = 20
        validated['portrait_gap'] = portrait_gap

        return validated

    def update_config(self, new_config):
        """Update configuration with validation"""
        if new_config:
            validated_config = self.validate_config(new_config)
            
            # Check if sort mode specifically has changed
            sort_mode_changed = self.config.get('sort_mode') != validated_config.get('sort_mode')
            
            # Check if any config has changed
            changed = any(self.config.get(k) != validated_config.get(k) 
                         for k in validated_config)

            if changed:
                self.config = validated_config
                self.update_display_parameters()
                
                # If sort mode changed, force an update to the display
                if sort_mode_changed:
                    self.last_update = time.time() - (self.display_time + 1)
                # Only reload current surfaces if sort mode hasn't changed
                elif self.current_photo_paths:
                    self.current_surfaces, self.current_bg_color = self.load_image(self.current_photo_paths)

    def load_image(self, photo_paths):
        """Load one or two images"""
        try:
            if isinstance(photo_paths, tuple) and photo_paths[1] and self.config['enable_portrait_pairs']:
                main_path, paired_path = photo_paths
                main_image = Image.open(main_path)
                paired_image = Image.open(paired_path)

                # Correct orientation based on EXIF data
                main_image = ImageOps.exif_transpose(main_image)
                paired_image = ImageOps.exif_transpose(paired_image)

                main_image = main_image.convert('RGB')
                paired_image = paired_image.convert('RGB')

                available_width = (self.WIDTH - self.config['portrait_gap']) // 2
                available_height = self.HEIGHT

                main_scale = min(
                    available_width / main_image.size[0],
                    available_height / main_image.size[1]
                )
                pair_scale = min(
                    available_width / paired_image.size[0],
                    available_height / paired_image.size[1]
                )

                scale = min(main_scale, pair_scale)

                main_image = main_image.resize((
                    int(main_image.size[0] * scale),
                    int(main_image.size[1] * scale)
                ), Image.Resampling.LANCZOS)
                paired_image = paired_image.resize((
                    int(paired_image.size[0] * scale),
                    int(paired_image.size[1] * scale)
                ), Image.Resampling.LANCZOS)

                main_surface = pygame.image.fromstring(
                    main_image.tobytes(), main_image.size, main_image.mode
                )
                paired_surface = pygame.image.fromstring(
                    paired_image.tobytes(), paired_image.size, paired_image.mode
                )

                return [main_surface, paired_surface], self.get_background_color(main_image)

            else:
                image = Image.open(photo_paths[0])

                # Correct orientation based on EXIF data
                image = ImageOps.exif_transpose(image)
                image = image.convert('RGB')

                scale = min(self.WIDTH / image.size[0], self.HEIGHT / image.size[1])
                image = image.resize((
                    int(image.size[0] * scale),
                    int(image.size[1] * scale)
                ), Image.Resampling.LANCZOS)
                surface = pygame.image.fromstring(
                    image.tobytes(), image.size, image.mode
                )

                return [surface], self.get_background_color(image)

        except Exception as e:
            print(f"Error loading image: {e}")
            return [], self.get_background_color(None)

    def _draw_frame(self, progress):
        """Draw a frame with the given progress value"""
        if self.transitioning:
            # Use smooth color interpolation for background
            r = int(self.current_bg_color[0] * (1 - progress) + self.next_bg_color[0] * progress)
            g = int(self.current_bg_color[1] * (1 - progress) + self.next_bg_color[1] * progress)
            b = int(self.current_bg_color[2] * (1 - progress) + self.next_bg_color[2] * progress)
            self.screen.fill((r, g, b))

            if self.current_surfaces:
                self._draw_surfaces(self.current_surfaces, int(255 * (1 - progress)))

            if self.next_surfaces:
                self._draw_surfaces(self.next_surfaces, int(255 * progress))
        else:
            self.screen.fill(self.current_bg_color)
            if self.current_surfaces:
                self._draw_surfaces(self.current_surfaces, 255)

        pygame.display.flip()

    def _draw_surfaces(self, surfaces, alpha):
            """Draw surfaces with the given alpha value"""
            if not surfaces:
                return

            if len(surfaces) == 1:
                surface = surfaces[0]
                surface_copy = surface.copy()
                surface_copy.set_alpha(alpha)
                rect = surface_copy.get_rect(center=(self.WIDTH // 2, self.HEIGHT // 2))
                self.screen.blit(surface_copy, rect)
            else:
                gap = self.config['portrait_gap']
                total_width = sum(s.get_width() for s in surfaces) + gap
                start_x = (self.WIDTH - total_width) // 2

                for surface in surfaces:
                    surface_copy = surface.copy()
                    surface_copy.set_alpha(alpha)
                    rect = surface_copy.get_rect(midleft=(start_x, self.HEIGHT // 2))
                    start_x += surface.get_width() + gap
                    self.screen.blit(surface_copy, rect)

    def get_server_config(self):
        """Fetch configuration from server with fallback."""
        try:
            response = requests.get(f'{self.sync_client.server_url}/api/config')
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching config: {e}")
            return self.config

    def run_config_update(self):
        while True:
            try:
                new_config = self.get_server_config()
                self.update_config(new_config)
            except Exception as e:
                print(f"Error updating config: {e}")
            time.sleep(5)

    def get_background_color(self, image):
        matting_mode = self.config.get('matting_mode', 'white')
        if matting_mode == 'black':
            return (0, 0, 0)
        elif matting_mode == 'white':
            return (255, 255, 255)
        elif image is not None:
            return self.get_dominant_color(image)
        return (0, 0, 0)

    def get_dominant_color(self, image):
        img = image.copy()
        img.thumbnail((100, 100))
        pixels = np.float32(img).reshape(-1, 3)
        dominant_color = pixels.mean(axis=0)
        return tuple(map(int, dominant_color))

    def run_sync(self):
        """Run sync process in background"""
        while True:
            try:
                self.sync_client.sync()
                self.sync_client.check_for_updates()
                time.sleep(self.sync_client.sync_interval)
            except Exception as e:
                print(f"Error in sync thread: {e}")
                time.sleep(10)

    def run(self):
        """Main display loop"""
        clock = pygame.time.Clock()
        
        print("\nPhoto Frame Display Started")
        print(f"Matting Mode: {self.config.get('matting_mode', 'auto')}")
        print(f"Portrait Pairing: {'Enabled' if self.config.get('enable_portrait_pairs') else 'Disabled'}")
        print(f"Sort Mode: {self.config.get('sort_mode', 'sequential')}")
        
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        return
            
            try:
                self.update_display()
            except Exception as e:
                print(f"Error updating display: {e}")
                time.sleep(0.1)
            
            # Run at higher frame rate for smoother transitions
            clock.tick(120)

class PhotoDisplayError(Exception):
    """Custom exception for photo display errors"""
    pass

def main():
    try:
        display = PhotoDisplay()
        display.run()
    except Exception as e:
        print(f"\nFatal error: {e}")
    finally:
        pygame.quit()
        sys.exit()

if __name__ == '__main__':
    main()