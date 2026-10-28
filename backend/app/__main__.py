"""Run the backend (and the frontend it finds in ../frontend):   python -m app   (from the backend folder)"""
import uvicorn
from app import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=config.DEBUG)
