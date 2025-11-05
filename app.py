import os
import json
import time
import uuid
import logging
import glob
from flask import Flask, request, render_template, jsonify, send_file
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from PIL import Image, ImageDraw
import io
import base64
from openai import OpenAI
import requests
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Allowed file extensions for images
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Initialize OpenAI client (will be set if API key is available)
openai_api_key = os.environ.get('OPENAI_API_KEY')
try:
    openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None
except Exception as e:
    print(f"Warning: Could not initialize OpenAI client: {e}")
    openai_client = None

# Story templates
STORY_TEMPLATES = {
    'little_red_riding_hood': {
        'title': 'Little Red Riding Hood',
        'character_name': 'Little Red Riding Hood',
        'folder': 'LRRH'
    },
    'jack_and_the_beanstalk': {
        'title': 'Jack and the Beanstalk',
        'character_name': 'Jack',
        'folder': 'JATB'
    }
}

# Progress tracking (with automatic cleanup)
progress_tracker = {}
CLEANUP_INTERVAL_HOURS = 24  # Clean up old sessions after 24 hours

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_old_sessions():
    """Remove old progress entries and files"""
    current_time = datetime.now()
    expired_sessions = []
    
    for session_id, info in list(progress_tracker.items()):
        # Remove sessions older than CLEANUP_INTERVAL_HOURS
        if 'created_at' in info:
            created = info['created_at']
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            if current_time - created > timedelta(hours=CLEANUP_INTERVAL_HOURS):
                expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        try:
            # Clean up files
            if 'pdf_path' in progress_tracker[session_id]:
                pdf_path = progress_tracker[session_id]['pdf_path']
                if pdf_path and os.path.exists(pdf_path):
                    os.remove(pdf_path)
            
            # Remove uploaded images
            upload_pattern = os.path.join(app.config['UPLOAD_FOLDER'], f'{session_id}_*')
            for file_path in glob.glob(upload_pattern):
                if os.path.exists(file_path):
                    os.remove(file_path)
            
            # Remove from tracker
            del progress_tracker[session_id]
            logger.info(f"Cleaned up expired session: {session_id}")
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {e}")

def analyze_image(image_path):
    """Analyze uploaded image to extract child appearance details"""
    if not openai_client:
        return "a child with kind features"
    try:
        # Read and encode image as base64
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        # Detect image format
        img = Image.open(io.BytesIO(image_data))
        img_format = img.format.lower() if img.format else 'jpeg'
        mime_type = f'image/{img_format}'
        
        # Encode to base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        image_url = f"data:{mime_type};base64,{base64_image}"
        
        # Use OpenAI Vision API to describe the child
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this child's appearance in detail, including: hair color and style, eye color, skin tone, facial features, and any distinctive characteristics. Be specific and consistent. Format as: 'A [age]-year-old [gender] with [hair description], [eye color] eyes, [skin tone], and [other features]."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        }
                    ]
                }
            ],
            max_tokens=200
        )
        
        description = response.choices[0].message.content
        return description
    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        return "a child with kind features"

def create_pdf(images_with_text, output_path):
    """Create an 8.5" × 8.5" PDF with full bleed images"""
    # 8.5 inches in points (72 points per inch)
    page_size = 8.5 * inch
    
    c = canvas.Canvas(output_path, pagesize=(page_size, page_size))
    
    for page_num, (image, text) in enumerate(images_with_text, 1):
        # Resize image to exactly match page size for full bleed
        # Convert PIL image to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize image to exact page dimensions (612x612 points = 8.5" x 8.5")
        # We need pixels: 8.5" at 72 DPI = 612, but for quality we'll use higher res
        target_size = int(page_size)
        image = image.resize((target_size, target_size), Image.Resampling.LANCZOS)
        
        # Save image to temp buffer
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='PNG', dpi=(72, 72))
        img_buffer.seek(0)
        
        # Draw image full bleed (edge to edge, no margins)
        c.drawImage(ImageReader(img_buffer), 0, 0, width=page_size, height=page_size, preserveAspectRatio=False, mask='auto')
        
        # Add text overlay at bottom with semi-transparent background
        if text and text.strip():
            text_height = 120  # Increased for better readability
            # Use solid white background (ReportLab doesn't support RGBA directly on Canvas)
            c.setFillColorRGB(1, 1, 1)  # White background
            c.rect(0, 0, page_size, text_height, fill=1, stroke=0)
            
            c.setFillColorRGB(0.1, 0.1, 0.1)  # Dark gray text for readability
            c.setFont("Helvetica-Bold", 18)
            
            # Split by newlines first (for cover title/subtitle), then wrap each line
            all_lines = []
            for paragraph in text.split('\n'):
                if paragraph.strip():
                    # Wrap this paragraph to fit page width
                    words = paragraph.split()
                    current_line = []
                    max_width = page_size - 40  # 20pt margins on each side
                    
                    for word in words:
                        test_line = ' '.join(current_line + [word]) if current_line else word
                        if c.stringWidth(test_line, "Helvetica-Bold", 18) < max_width:
                            current_line.append(word)
                        else:
                            if current_line:
                                all_lines.append(' '.join(current_line))
                            current_line = [word]
                    if current_line:
                        all_lines.append(' '.join(current_line))
            
            # Draw text lines (show up to 4 lines)
            y_pos = 30
            for line in all_lines[-4:]:
                if line.strip():
                    c.drawString(20, y_pos, line[:80])  # Limit line length
                    y_pos += 28
        
        c.showPage()
    
    c.save()

def load_template_story(story_type, child_name):
    """Load story text and metadata from template folder"""
    template = STORY_TEMPLATES[story_type]
    template_folder = os.path.join('templates', template['folder'])
    text_json_path = os.path.join(template_folder, 'text.json')
    
    try:
        with open(text_json_path, 'r', encoding='utf-8') as f:
            story_data = json.load(f)
        
        # Replace (child's name) in subtitle with actual child name
        subtitle = story_data.get('subtitle', '')
        if '(child\'s name)' in subtitle or '(child\'s name)' in subtitle:
            subtitle = subtitle.replace('(child\'s name)', child_name).replace('(child\'s name)', child_name)
        
        story_data['subtitle'] = subtitle
        return story_data
    except Exception as e:
        logger.error(f"Error loading template story: {e}")
        raise

def load_template_images(story_type):
    """Load template images from template folder"""
    template = STORY_TEMPLATES[story_type]
    template_folder = os.path.join('templates', template['folder'])
    
    images = []
    
    # Load cover image
    cover_path = os.path.join(template_folder, 'cover.png')
    if os.path.exists(cover_path):
        cover_img = Image.open(cover_path)
        if cover_img.mode != 'RGB':
            cover_img = cover_img.convert('RGB')
        images.append(('cover', cover_img))
    else:
        raise FileNotFoundError(f"Cover image not found: {cover_path}")
    
    # Load page images (Page 1.png through Page 12.png)
    for page_num in range(1, 13):
        page_path = os.path.join(template_folder, f'Page {page_num}.png')
        if os.path.exists(page_path):
            page_img = Image.open(page_path)
            if page_img.mode != 'RGB':
                page_img = page_img.convert('RGB')
            images.append((f'page_{page_num}', page_img))
        else:
            raise FileNotFoundError(f"Page {page_num} image not found: {page_path}")
    
    return images

def replace_face_in_image(template_image, child_image_path, character_description):
    """Replace face in template image with child's face using OpenAI DALL-E image editing"""
    if not openai_client:
        # If no API key, return original template
        return template_image
    
    try:
        # Save template image to temporary file for API
        temp_template_path = os.path.join(app.config['UPLOAD_FOLDER'], f'temp_template_{uuid.uuid4().hex[:8]}.png')
        template_image.save(temp_template_path, 'PNG')
        
        # Create a mask - we'll create a simple mask covering the face area
        # For now, we'll use a center mask (face is typically in center-upper area)
        # In production, you'd want to use face detection to create precise masks
        mask_image = Image.new('RGBA', template_image.size, (0, 0, 0, 0))
        # Create a mask covering center-upper portion (typical face location)
        width, height = template_image.size
        mask_box = (width // 4, height // 6, 3 * width // 4, height // 2)
        
        # Create mask with white (transparent in RGBA) for face area
        draw = ImageDraw.Draw(mask_image)
        # Draw ellipse for face mask
        draw.ellipse(mask_box, fill=(255, 255, 255, 255))
        
        temp_mask_path = os.path.join(app.config['UPLOAD_FOLDER'], f'temp_mask_{uuid.uuid4().hex[:8]}.png')
        mask_image.save(temp_mask_path, 'PNG')
        
        # Prepare prompt for face replacement
        prompt = f"Replace the character's face with a face matching this description: {character_description}. Maintain the exact same pose, expression, and style as the original image. Keep all other elements identical."
        
        # Use DALL-E image editing API
        with open(temp_template_path, 'rb') as template_file, open(temp_mask_path, 'rb') as mask_file:
            response = openai_client.images.edit(
                image=template_file,
                mask=mask_file,
                prompt=prompt,
                n=1,
                size="1024x1024"
            )
        
        # Download the edited image
        edited_image_url = response.data[0].url
        img_response = requests.get(edited_image_url, timeout=30)
        img_response.raise_for_status()
        edited_image = Image.open(io.BytesIO(img_response.content))
        
        # Clean up temp files
        try:
            os.remove(temp_template_path)
            os.remove(temp_mask_path)
        except:
            pass
        
        if edited_image.mode != 'RGB':
            edited_image = edited_image.convert('RGB')
        
        return edited_image
        
    except Exception as e:
        logger.error(f"Error replacing face in image: {e}")
        # Return original template if face replacement fails
        return template_image

def generate_book_async(session_id, image_path, story_type, gender, child_name):
    """Async function to generate the entire book using templates"""
    try:
        progress_tracker[session_id] = {
            'progress': 0, 
            'status': 'Starting...', 
            'error': None,
            'created_at': datetime.now().isoformat()
        }
        logger.info(f"Starting book generation for session {session_id}")
        
        # Step 1: Analyze child's image for face replacement
        progress_tracker[session_id] = {'progress': 5, 'status': 'Analyzing child\'s photo...'}
        character_description = analyze_image(image_path)
        
        # Step 2: Load template story
        progress_tracker[session_id] = {'progress': 10, 'status': 'Loading story template...'}
        story_data = load_template_story(story_type, child_name)
        
        # Step 3: Load template images
        progress_tracker[session_id] = {'progress': 20, 'status': 'Loading template images...'}
        template_images = load_template_images(story_type)
        
        # Step 4: Replace faces in template images
        images_with_text = []
        
        # Process cover image
        progress_tracker[session_id] = {'progress': 25, 'status': 'Replacing face in cover image...'}
        cover_img = template_images[0][1]
        cover_img = replace_face_in_image(cover_img, image_path, character_description)
        cover_text = f"{story_data.get('title', '')}\n{story_data.get('subtitle', '')}"
        images_with_text.append((cover_img, cover_text))
        
        # Add story pages with text and face replacement
        pages = story_data.get('pages', [])
        for idx, page in enumerate(pages):
            page_num = page.get('page_number', idx + 1)
            progress = 25 + int((idx + 1) / len(pages) * 65)
            progress_tracker[session_id] = {
                'progress': progress,
                'status': f'Replacing face in page {page_num} of {len(pages)}...'
            }
            
            # Get corresponding image (template_images[0] is cover, so Page 1 is at index 1, Page 2 at index 2, etc.)
            # page_num should be 1-12, so we use it directly as index
            if 1 <= page_num <= 12 and page_num < len(template_images):
                page_img = template_images[page_num][1]
                # Replace face in this page image
                page_img = replace_face_in_image(page_img, image_path, character_description)
                page_text = page.get('text', '')
                images_with_text.append((page_img, page_text))
            else:
                logger.warning(f"No image found for page {page_num}")
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
        
        # Step 5: Create PDF
        progress_tracker[session_id] = {'progress': 95, 'status': 'Creating PDF...'}
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{session_id}.pdf')
        create_pdf(images_with_text, output_path)
        
        progress_tracker[session_id] = {
            'progress': 100,
            'status': 'Complete!',
            'pdf_path': output_path,
            'completed': True,
            'completed_at': datetime.now().isoformat()
        }
        logger.info(f"Book generation completed for session {session_id}")
        
    except Exception as e:
        logger.error(f"Error in book generation for session {session_id}: {e}", exc_info=True)
        progress_tracker[session_id] = {
            'progress': 0,
            'status': f'Error: {str(e)}',
            'error': str(e),
            'completed': False
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    """Handle file upload and start book generation"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        story_type = request.form.get('story_type')
        gender = request.form.get('gender')
        child_name = request.form.get('child_name', '').strip()
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not child_name:
            return jsonify({'error': 'Child\'s name is required'}), 400
        
        # Validate file extension
        if not allowed_file(file.filename):
            return jsonify({'error': f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
        
        # Validate file is actually an image
        try:
            file.seek(0)
            img = Image.open(io.BytesIO(file.read()))
            img.verify()
            file.seek(0)  # Reset file pointer
        except Exception as e:
            logger.warning(f"Invalid image file uploaded: {e}")
            return jsonify({'error': 'File is not a valid image'}), 400
        
        if story_type not in STORY_TEMPLATES:
            return jsonify({'error': 'Invalid story type'}), 400
        
        if gender not in ['Boy', 'Girl']:
            return jsonify({'error': 'Invalid gender selection'}), 400
        
        if not openai_api_key:
            return jsonify({'error': 'OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.'}), 500
        
        # Generate unique session ID
        session_id = str(uuid.uuid4())
        
        # Save uploaded file with validated extension
        filename = secure_filename(file.filename)
        # Ensure filename has valid extension
        if not filename or '.' not in filename:
            filename = f'upload_{session_id[:8]}.jpg'
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f'{session_id}_{filename}')
        file.save(file_path)
        logger.info(f"File uploaded: {filename} for session {session_id}")
        
        # Clean up old sessions periodically
        cleanup_old_sessions()
        
        # Start async generation
        thread = threading.Thread(
            target=generate_book_async,
            args=(session_id, file_path, story_type, gender, child_name)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'session_id': session_id,
            'message': 'Generation started'
        })
        
    except RequestEntityTooLarge:
        return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred processing your request'}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large errors"""
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413

@app.route('/progress/<session_id>')
def progress(session_id):
    """Get generation progress"""
    if session_id not in progress_tracker:
        return jsonify({'error': 'Invalid session ID'}), 404
    
    return jsonify(progress_tracker[session_id])

@app.route('/download/<session_id>')
def download(session_id):
    """Download generated PDF"""
    if session_id not in progress_tracker:
        return jsonify({'error': 'Invalid session ID'}), 404
    
    progress_info = progress_tracker[session_id]
    
    if not progress_info.get('completed'):
        return jsonify({'error': 'Book not ready yet'}), 400
    
    pdf_path = progress_info.get('pdf_path')
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({'error': 'PDF file not found'}), 404
    
    # Generate friendly filename
    timestamp = datetime.now().strftime('%Y%m%d')
    filename = f'fairy_tale_book_{timestamp}.pdf'
    
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )

@app.route('/health')
def health():
    """Health check endpoint for deployment monitoring"""
    return jsonify({'status': 'healthy', 'service': 'fairy_tale_generator'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)