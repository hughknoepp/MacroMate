import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    APP_NAME = 'MacroMate'  # shown in page titles and on the home page
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-this')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False