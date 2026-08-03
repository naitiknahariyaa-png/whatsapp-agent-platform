"""
Startup wrapper — ensures services directory is in sys.path before uvicorn spawns
"""
import os
import sys

# Add services to path BEFORE importing uvicorn/main
services_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "services"))
if services_dir not in sys.path:
    sys.path.insert(0, services_dir)

# Now run the app
if __name__ == "__main__":
    import uvicorn
    from main import app
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)