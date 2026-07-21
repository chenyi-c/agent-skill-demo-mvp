import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import skills to trigger registration on startup
import app.services.skills
from app.api.routes import router

app = FastAPI(
    title="AI Agent Skill Web Demo MVP",
    description="A lightweight web demo MVP to verify AI Agent's capability to route and execute Custom Skills.",
    version="0.1.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)

# Mount static folder for CSS/JS assets if any
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
