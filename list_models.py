import os
import django
from django.conf import settings
import google.generativeai as genai

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Configure GenAI
genai.configure(api_key=settings.API_KEY_GEMINI)

# List models
print("Available models:")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(f"Name: {m.name}")
