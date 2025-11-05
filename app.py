import os
import json
import time
import uuid
import logging
import glob
from flask import Flask, request, render_template, jsonify, send_file
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from PIL import Image
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
        'character_name': 'Little Red Riding Hood'
    },
    'jack_and_the_beanstalk': {
        'title': 'Jack and the Beanstalk',
        'character_name': 'Jack'
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

def generate_story_outline(story_type, gender, character_description):
    """Generate 12-page story outline in JSON format"""
    if not openai_client:
        # Return fallback story if API not configured
        return generate_fallback_story(story_type, gender, character_description)
    
    template = STORY_TEMPLATES[story_type]
    story_title = template['title']
    character_name = template['character_name']
    
    if story_type == 'little_red_riding_hood':
        story_prompt = f"""Create a 12-page children's story based on Little Red Riding Hood, starring {character_name} (a {gender} described as {character_description}).

Structure it as a JSON object with:
- story_title: "{story_title}"
- pages: array of 12 objects, each with:
  - page_number: 1-12
  - scene_description: brief scene description
  - text: 2-3 sentences for this page (child-friendly, age-appropriate)
  - image_prompt: detailed prompt for image generation maintaining consistent character appearance: {character_description}

The story should:
- Page 1: Cover page with {character_name}
- Pages 2-11: The adventure story
- Page 12: Happy ending

Return ONLY valid JSON, no markdown formatting."""
    else:  # jack_and_the_beanstalk
        story_prompt = f"""Create a 12-page children's story based on Jack and the Beanstalk, starring {character_name} (a {gender} described as {character_description}).

Structure it as a JSON object with:
- story_title: "{story_title}"
- pages: array of 12 objects, each with:
  - page_number: 1-12
  - scene_description: brief scene description
  - text: 2-3 sentences for this page (child-friendly, age-appropriate)
  - image_prompt: detailed prompt for image generation maintaining consistent character appearance: {character_description}

The story should:
- Page 1: Cover page with {character_name}
- Pages 2-11: The adventure story with the beanstalk
- Page 12: Happy ending

Return ONLY valid JSON, no markdown formatting."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a children's story writer. Always return valid JSON only."},
                {"role": "user", "content": story_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        # Remove Markdown code blocks if present
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        content = content.strip()
        
        story_json = json.loads(content)
        
        # Ensure story has required structure
        if 'pages' not in story_json or not isinstance(story_json['pages'], list):
            raise ValueError("Invalid story structure")
        
        # Ensure we have exactly 12 pages
        if len(story_json['pages']) != 12:
            # Pad or trim to 12 pages
            if len(story_json['pages']) < 12:
                while len(story_json['pages']) < 12:
                    story_json['pages'].append({
                        "page_number": len(story_json['pages']) + 1,
                        "scene_description": "Story continues",
                        "text": "The adventure continues...",
                        "image_prompt": f"{character_description}, children's book illustration"
                    })
            else:
                story_json['pages'] = story_json['pages'][:12]
        
        return story_json
    except Exception as e:
        logger.error(f"Error generating story: {e}")
        # Fallback story structure
        return generate_fallback_story(story_type, gender, character_description)

def generate_fallback_story(story_type, gender, character_description):
    """Fallback story if AI generation fails"""
    template = STORY_TEMPLATES[story_type]
    pages = []
    
    if story_type == 'little_red_riding_hood':
        scenes = [
            "Cover: {character_name} in red hood",
            "{character_name} leaves home with a basket",
            "Walking through the forest",
            "Meeting the wolf in the forest",
            "The wolf rushes ahead",
            "{character_name} arrives at grandmother's house",
            "The wolf is in grandmother's bed",
            "The wolf reveals himself",
            "A brave woodcutter arrives",
            "The woodcutter saves {character_name}",
            "Safe return home",
            "Happy ending with family"
        ]
    else:  # jack_and_the_beanstalk
        scenes = [
            "Cover: {character_name} at home",
            "{character_name} trades cow for magic beans",
            "Beans grow into giant beanstalk",
            "{character_name} climbs the beanstalk",
            "Reaching the clouds",
            "Finding a giant's castle",
            "Entering the castle",
            "Taking the golden goose",
            "The giant wakes up",
            "Climbing down quickly",
            "Cutting down the beanstalk",
            "Happy ending with family"
        ]
    
    for i, scene in enumerate(scenes, 1):
        pages.append({
            "page_number": i,
            "scene_description": scene.format(character_name=template['character_name']),
            "text": f"This is page {i} of the story.",
            "image_prompt": f"{scene.format(character_name=template['character_name'])}, featuring {character_description}, children's book illustration style, vibrant colors"
        })
    
    return {
        "story_title": template['title'],
        "pages": pages
    }

def generate_image(prompt, character_description, story_context="", page_num=1):
    """Generate an image using OpenAI DALL-E"""
    if not openai_client:
        # Return placeholder if API not configured
        return Image.new('RGB', (1024, 1024), color='lightblue')
    try:
        # Enhanced prompt with consistency requirements
        # Limit prompt length (DALL-E has max length limits)
        base_prompt = prompt[:400] if len(prompt) > 400 else prompt
        char_desc = character_description[:200] if len(character_description) > 200 else character_description
        
        full_prompt = f"{base_prompt}. Character: {char_desc}. Consistent character appearance, children's book illustration style, Disney Brave aesthetic, vibrant colors, square composition, page {page_num} of 12"
        
        response = openai_client.images.generate(
            model="dall-e-3",
            prompt=full_prompt[:1000],  # DALL-E 3 has prompt length limits
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        image_url = response.data[0].url
        
        # Download the image with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                img_response = requests.get(image_url, timeout=30)
                img_response.raise_for_status()
                return Image.open(io.BytesIO(img_response.content))
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
        
    except Exception as e:
        logger.error(f"Error generating image (page {page_num}): {e}")
        # Return a placeholder image
        return Image.new('RGB', (1024, 1024), color='lightblue')

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
            
            # Wrap text to fit page width
            words = text.split()
            lines = []
            current_line = []
            max_width = page_size - 40  # 20pt margins on each side
            
            for word in words:
                test_line = ' '.join(current_line + [word]) if current_line else word
                if c.stringWidth(test_line, "Helvetica-Bold", 18) < max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            if current_line:
                lines.append(' '.join(current_line))
            
            # Draw text lines (show up to 4 lines)
            y_pos = 30
            for line in lines[-4:]:
                if line.strip():
                    c.drawString(20, y_pos, line[:80])  # Limit line length
                    y_pos += 28
        
        c.showPage()
    
    c.save()

def generate_book_async(session_id, image_path, story_type, gender):
    """Async function to generate the entire book"""
    try:
        progress_tracker[session_id] = {
            'progress': 0, 
            'status': 'Starting...', 
            'error': None,
            'created_at': datetime.now().isoformat()
        }
        logger.info(f"Starting book generation for session {session_id}")
        
        # Step 1: Analyze image
        progress_tracker[session_id] = {'progress': 5, 'status': 'Analyzing image...'}
        character_description = analyze_image(image_path)
        
        # Step 2: Generate story outline
        progress_tracker[session_id] = {'progress': 15, 'status': 'Generating story outline...'}
        story_outline = generate_story_outline(story_type, gender, character_description)
        
        # Step 3: Generate images
        images_with_text = []
        total_pages = len(story_outline.get('pages', []))
        
        for idx, page in enumerate(story_outline.get('pages', [])):
            progress = 15 + int((idx + 1) / total_pages * 75)
            progress_tracker[session_id] = {
                'progress': progress,
                'status': f'Creating page {page["page_number"]} of {total_pages}...'
            }
            
            # Generate image
            image_prompt = page.get('image_prompt', '')
            story_context = f"From {story_outline.get('story_title', '')}"
            page_num = page.get('page_number', idx + 1)
            image = generate_image(image_prompt, character_description, story_context, page_num)
            
            # Get text for this page
            page_text = page.get('text', '')
            
            images_with_text.append((image, page_text))
            
            # Rate limiting: small delay between requests
            time.sleep(1)
        
        # Step 4: Create PDF
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
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
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
            args=(session_id, file_path, story_type, gender)
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