import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# Leer el JSON desde variable de entorno
firebase_config = os.getenv("FIREBASE_CREDENTIALS")

if not firebase_config:
    raise ValueError("❌ No se encontró la variable FIREBASE_CREDENTIALS en Render")

# Convertir el texto JSON en un diccionario Python
cred_dict = json.loads(firebase_config)

# Inicializar Firebase solo si no está activo
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()

def obtener_productos():
    """Devuelve todos los productos de la colección 'productos'."""
    productos = {}
    try:
        docs = db.collection("productos").stream()
        for doc in docs:
            productos[doc.id] = doc.to_dict()
    except Exception as e:
        print("🔥 Error en obtener_productos():", e)
    return productos


