import os
import json
import firebase_admin
from firebase_admin import credentials

def init_firebase():
    """Initialize Firebase Admin SDK. Supports:
    1. FIREBASE_CREDENTIALS env var (JSON string) - for Render/serverless
    2. GOOGLE_APPLICATION_CREDENTIALS env var (file path) - for Docker/VM
    3. Default credentials (GCP environments)
    """
    if firebase_admin._apps:
        return

    creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    creds_file = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    if creds_json:
        cred = credentials.Certificate(json.loads(creds_json))
        firebase_admin.initialize_app(cred)
    elif creds_file and os.path.exists(creds_file):
        cred = credentials.Certificate(creds_file)
        firebase_admin.initialize_app(cred)
    else:
        # Skip firebase init if no credentials available
        pass
