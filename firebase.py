import os
import firebase_admin
from firebase_admin import credentials, firestore

# Prevent multiple initializations
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(
            os.path.join("secrets", 
                        "firebase-service-account.json"
                        ))
        firebase_admin.initialize_app(cred)
    except:
        raise ValueError("Firebase credentials not found")

db = firestore.client()