# Gaje Studio

Gaje Studio combines three browser tools: Roblox animation re-uploading through Open Cloud, a local-in-browser 3D maker using Three.js, and audio conversion/upload using yt-dlp, FFmpeg, and Roblox Open Cloud.

## Use responsibly

- Only process and upload audio that you own or are licensed/authorized to use. The audio tool requires an explicit confirmation before each job; that confirmation cannot verify ownership.
- Audio conversion changes format and volume only. It does not change playback speed or pitch.
- Only supported YouTube, TikTok, and SoundCloud URLs are accepted; only use URLs for content you are authorized to process.
- Roblox API keys are kept in the browser's local storage and sent to this server when needed to make Roblox API requests. Use a trusted device and remove saved keys when finished.
- The site uses one shared access password. Each browser session has its own generated files, history, and playlists; everyone with the password can use the tools. Avoid uploading sensitive content.

## Run locally

Python 3.10+ is recommended. On Windows, run `run.bat`. Or create a virtual environment, install `requirements.txt`, and run `python app.py`.

When `APP_ENV` is `development`, the password gate is disabled for localhost use. Production startup requires both `PUBLIC_ACCESS_PASSWORD` and `FLASK_SECRET_KEY`.

## Deploy to Render

1. Create a public GitHub repository named `gaje-studio` and push this project.
2. In Render, create a **Blueprint** from that GitHub repository and apply `render.yaml`.
3. Set `PUBLIC_ACCESS_PASSWORD` to a strong, unique secret in the Render service environment. Render generates `FLASK_SECRET_KEY`; keep it secret.
4. Wait for the health check to pass, then open the service URL and sign in with the shared password.

The Blueprint uses Render's free web service and ephemeral storage. Generated audio, temporary files, history, and playlists are isolated by browser session, but can disappear when the service restarts or deploys. The job queue also runs in memory and is cleared on restart. Do not store credentials or user media in Git.
