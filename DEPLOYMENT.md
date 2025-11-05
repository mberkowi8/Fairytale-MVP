# Deployment Guide

## Quick Start - Deploy to Render (Recommended)

### Step 1: Push to GitHub
```bash
git add .
git commit -m "Ready for production deployment"
git push origin main
```

### Step 2: Deploy on Render

1. **Go to [render.com](https://render.com)** and sign up/login
2. **Create New Web Service**
   - Connect your GitHub repository: `https://github.com/mberkowi8/Fairytale-MVP.git`
   - Select the repository and branch (main)

3. **Configure Service:**
   - **Name**: `fairy-tale-generator` (or your preferred name)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Instance Type**: Starter (Free) or higher for production

4. **Set Environment Variables:**
   Click "Environment" and add:
   - `OPENAI_API_KEY` = (your OpenAI API key)
   - `SECRET_KEY` = (generate a secure random string)
   - `FLASK_ENV` = `production`
   - `PORT` = (usually auto-set by Render, but you can set to `8000`)

5. **Deploy**
   - Click "Create Web Service"
   - Wait for build to complete (~2-3 minutes)
   - Your app will be live at: `https://your-app-name.onrender.com`

### Step 3: Test
- Visit your live URL
- Test the form with a child's photo
- Check that face replacement works

---

## Alternative: Deploy to Heroku

### Step 1: Install Heroku CLI
```bash
# macOS
brew tap heroku/brew && brew install heroku

# Or download from: https://devcenter.heroku.com/articles/heroku-cli
```

### Step 2: Login and Create App
```bash
heroku login
heroku create your-app-name
```

### Step 3: Set Environment Variables
```bash
heroku config:set OPENAI_API_KEY=your-openai-api-key
heroku config:set SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
heroku config:set FLASK_ENV=production
```

### Step 4: Deploy
```bash
git push heroku main
heroku open
```

---

## Test Locally in Production Mode

Before deploying, test locally:

```bash
# Set environment variables
export OPENAI_API_KEY="your-key-here"
export SECRET_KEY="your-secret-key-here"
export FLASK_ENV="production"
export PORT=8000

# Run with gunicorn
gunicorn app:app --bind 0.0.0.0:8000
```

Visit: `http://localhost:8000`

---

## Important Notes

1. **Environment Variables**: Make sure to set all required environment variables in your deployment platform
2. **File Storage**: The app uses local file storage (`uploads/` and `outputs/`). For production, consider:
   - Using cloud storage (AWS S3, Cloudinary, etc.)
   - Or ensure your hosting platform has persistent storage
3. **Rate Limiting**: OpenAI has rate limits. The app includes delays, but monitor usage
4. **Memory**: Face replacement can be memory-intensive. Consider upgrading if you see issues
5. **Timeout**: Book generation can take 2-5 minutes. Ensure your hosting platform allows long-running requests

---

## Troubleshooting

### Build Fails
- Check `requirements.txt` is up to date
- Verify Python version in `runtime.txt` matches your platform

### App Crashes
- Check logs: `heroku logs --tail` or Render dashboard
- Verify environment variables are set
- Check OpenAI API key is valid

### Images Not Loading
- Verify template folders (LRRH, JATB) are in the repository
- Check file paths are correct

### Face Replacement Not Working
- Verify OpenAI API key has access to DALL-E image editing
- Check API rate limits haven't been exceeded

