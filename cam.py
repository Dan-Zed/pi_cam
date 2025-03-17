from flask import Flask, render_template, Response, jsonify, send_from_directory
from picamera2 import Picamera2
from libcamera import controls
import io
import os
import time

app = Flask(__name__)
app.config['CAPTURE_FOLDER'] = 'captures'

# Create captures directory if it doesn't exist
if not os.path.exists(app.config['CAPTURE_FOLDER']):
    os.makedirs(app.config['CAPTURE_FOLDER'])

# Simple camera setup with type detection
picam2 = Picamera2()
camera_info = picam2.global_camera_info()
is_v3 = "imx708" in str(camera_info).lower()
print(f"Camera info: {camera_info}")
print(f"Detected {'Pi Camera V3' if is_v3 else 'HQ or other camera'}")

# Create base configurations with matching aspect ratios
if is_v3:
    if is_v3:
        # V3 camera - 16:9 aspect ratio
        width, height = 1920, 1080
        # Calculate center window coordinates (10% of width/height)
        window_width = int(width * 0.1)
        window_height = int(height * 0.1)
        window_x = int((width - window_width) / 2)
        window_y = int((height - window_height) / 2)
        
        preview_config = picam2.create_video_configuration(
            main={"size": (width, height)},  # 1080p for reliable streaming
            controls={
                "AfMode": controls.AfModeEnum.Continuous,
                "AfRange": controls.AfRangeEnum.Normal,  # Normal focus range
                "AfMetering": controls.AfMeteringEnum.Windows,  # Use window-based metering
                "AfWindows": [(window_x, window_y, window_width, window_height)],  # Center window in pixels
                "FrameDurationLimits": (100000, 100000)  # Limit frame rate to reduce focus hunting
            }
        )
        
        still_config = picam2.create_still_configuration(
            main={"size": (4608, 2592)},  # Full resolution 16:9
            controls={"AfMode": controls.AfModeEnum.Auto}
        )
    else:
        # HQ camera - 4:3 aspect ratio
        preview_config = picam2.create_video_configuration(
            main={"size": (1640, 1232)}  # Reliable streaming resolution
        )
        
        still_config = picam2.create_still_configuration(
            main={"size": (4056, 3040)}  # Full resolution 4:3
        )
    
    # Use preview config for video streaming
    video_config = preview_config
    
    still_config = picam2.create_still_configuration(
        main={"size": (4608, 2592)},  # Full resolution 16:9
        controls={"AfMode": controls.AfModeEnum.Auto}
    )
    
    # Use preview config instead of video config for V3
    video_config = preview_config
else:
    # HQ has 4:3 native resolution (4056 × 3040)
    video_config = picam2.create_video_configuration(main={"size": (640, 480)})  # 4:3
    still_config = picam2.create_still_configuration()

# Start with video configuration
picam2.configure(video_config)
picam2.start()

def get_next_capture_number():
    existing_files = [f for f in os.listdir(app.config['CAPTURE_FOLDER']) if f.startswith('capture_')]
    numbers = [int(f.split('_')[1].split('.')[0]) for f in existing_files if f.split('_')[1].split('.')[0].isdigit()]
    return max(numbers, default=0) + 1

def gen_frames():
    while True:
        stream = io.BytesIO()
        picam2.capture_file(stream, format='jpeg')
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + stream.getvalue() + b'\r\n')

@app.route('/')
def index():
    # Pass camera type to template
    return render_template('index.html', is_v3=is_v3)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture')
def capture():
    try:
        n = get_next_capture_number()
        filename = f'capture_{n}.jpg'
        filepath = os.path.join(app.config['CAPTURE_FOLDER'], filename)
        
        # Switch to still config for high-res capture
        picam2.stop()
        picam2.configure(still_config)
        picam2.start()
        
        # For V3, wait a moment for autofocus
        if is_v3:
            time.sleep(0.5)
            
        picam2.capture_file(filepath)
        
        # Switch back to video config
        picam2.stop()
        picam2.configure(video_config)
        picam2.start()
        
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        try:
            # Make sure we get back to video mode
            picam2.stop()
            picam2.configure(video_config)
            picam2.start()
        except:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/latest_capture')
def latest_capture():
    try:
        files = [f for f in os.listdir(app.config['CAPTURE_FOLDER']) if f.startswith('capture_')]
        if not files:
            return jsonify({'success': False, 'error': 'No captures found'}), 404
        latest = max(files, key=lambda x: int(x.split('_')[1].split('.')[0]))
        return jsonify({'success': True, 'filename': latest})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/captures/<path:filename>')
def serve_capture(filename):
    return send_from_directory(app.config['CAPTURE_FOLDER'], filename)

@app.route('/camera_info')
def camera_info():
    return jsonify({
        'is_v3': is_v3,
        'info': str(camera_info),
        'type': 'Pi Camera V3' if is_v3 else 'HQ or other camera'
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)