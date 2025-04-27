import os
import firebase_admin
from firebase_admin import credentials, firestore

# Prevent multiple initializations
if not firebase_admin._apps:
    cred = credentials.Certificate(
        os.path.join("secrets", 
                     "firebase-service-account.json"
                     ))
    firebase_admin.initialize_app(cred)

db = firestore.client()