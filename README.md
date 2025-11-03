# Fairy Tale Generator MVP

A fully automated system to generate personalized children's books from a single child photo.

## Features

- **Image Upload**: Upload a photo of a child
- **Story Selection**: Choose between Little Red Riding Hood or Jack and the Beanstalk
- **Gender Selection**: Select Boy or Girl
- **Automated Generation**: 
  - Analyzes the child's appearance
  - Generates a 12-page story outline
  - Creates 12 images with consistent character appearance
  - Compiles into a professional PDF
- **Progress Tracking**: Real-time progress bar and status updates
- **PDF Output**: 8.5" × 8.5" square pages with full bleed images

## Setup

### Prerequisites

- Python 3.8 or higher
- OpenAI API key with access to:
  - GPT-4o (for story generation and image analysis)
  - DALL-E 3 (for image generation)

**Important:** Each book generation uses:
- 1 GPT-4o call (image analysis)
- 1 GPT-4o call (story generation)
- 12 DALL-E 3 image generations

Estimated cost per book: ~$0.60-1.20 (depending on API pricing)

### Installation

1. Clone or download this repository

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set environment variables:

**Option A: Environment variables**
```bash
export OPENAI_API_KEY='your-api-key-here'
export SECRET_KEY='your-secret-key-for-production'
export FLASK_ENV='development'  # Use 'production' for deployment
export PORT=5000  # Optional, defaults to 5000
```

**Option B: Create `.env` file** (for local development)
```
OPENAI_API_KEY=your-api-key-here
SECRET_KEY=dev-secret-key
FLASK_ENV=development
PORT=5000
```

Then install python-dotenv and load it:
```bash
pip install python-dotenv
```

And add to `app.py`:
```python
from dotenv import load_dotenv
load_dotenv()
```

5. Run the application:

**Development:**
```bash
python app.py
```

**Production (with gunicorn):**
```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

6. Open your browser to `http://localhost:5000`

### Rate Limits & Considerations

- **DALL-E 3**: ~15-20 requests per minute (default tier)
- Built-in 1-second delay between image generations
- Generation time: ~2-5 minutes per book (depending on API response times)
- Progress updates every 2 seconds

## Deployment

### Render

1. Create a new Web Service
2. Connect your repository
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
5. Add environment variables:
   - `OPENAI_API_KEY`
   - `SECRET_KEY` (generate a secure random string)
   - `FLASK_ENV=production`
   - `PORT` (usually set automatically by Render)

### Heroku

1. Install Heroku CLI
2. Create `Procfile`:
```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```
3. Deploy:
```bash
heroku create your-app-name
heroku config:set OPENAI_API_KEY=your-key
heroku config:set SECRET_KEY=your-secret
git push heroku main
```

## Technical Specifications

- **Page Size**: 8.5" × 8.5" (612 × 612 points)
- **Full Bleed**: Images extend edge-to-edge with no white borders
- **Page Count**: 12 pages (cover + 11 story pages)
- **Image Format**: 1024×1024 pixels, square composition
- **Text Integration**: Text overlaid on images with semi-transparent background

## API Endpoints

- `GET /` - Main form page
- `POST /upload` - Upload image and start generation
  - Form data: `image` (file), `story_type` (string), `gender` (string)
  - Returns: `{session_id: string}`
- `GET /progress/<session_id>` - Get generation progress
  - Returns: `{progress: number, status: string, completed: bool, pdf_path: string?}`
- `GET /download/<session_id>` - Download generated PDF

## Project Structure

```
.
├── app.py                 # Main Flask application
├── templates/
│   └── index.html        # Frontend form and UI
├── uploads/              # Temporary uploaded images (gitignored)
├── outputs/              # Generated PDFs (gitignored)
├── requirements.txt      # Python dependencies
├── .gitignore           # Git ignore rules
└── README.md            # This file
```

## Development Notes

- Images are stored temporarily in `uploads/` directory
- Generated PDFs are stored in `outputs/` directory
- Progress is tracked in-memory (for MVP; consider Redis for production scaling)
- Rate limiting: 1 second delay between image generation requests
- Character consistency maintained through detailed prompts and consistent character descriptions

## Limitations (v0.1 MVP)

- Single child image input
- Two story options only
- In-memory progress tracking (not suitable for multiple servers)
- No face swapping (uses prompt-based consistency)
- Basic error handling

## Future Enhancements (v0.2+)

- AI evaluator for quality control
- Face swapping technology for better consistency
- More story options
- Custom story elements (favorite colors, pets, etc.)
- Interactive elements
- Better error recovery and retry logic

## License

MIT License - feel free to use and modify for your projects.

