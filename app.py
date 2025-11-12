# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# ARCHIVO: app.py
# PROYECTO: Chatbot de Messenger – Frere’s Collection
# DESCRIPCIÓN:
#   Versión robusta para PRODUCCIÓN con:
#   1. Integración con Dialogflow para NLU (Inteligencia).
#   2. "Fulfillment" local: Dialogflow le pide a esta app
#      que consulte Firebase.
#   3. Mantiene los flujos de Login/Registro.
#
# AUTOR: Fernando Ortiz (con ajustes de producción)
# ------------------------------------------------------------

# --- Importación de librerías necesarias ---
from flask import Flask, request, jsonify
import requests
import logging
import threading
import unicodedata
import string
import os
from datetime import date, datetime

# --- ¡NUEVO! Importaciones de Dialogflow ---
try:
    import google.cloud.dialogflow_v2 as dialogflow
    from google.api_core.exceptions import InvalidArgument
except ImportError:
    logging.critical("FATAL: Faltan librerías de Dialogflow. ¿Están en requirements.txt?")
    dialogflow = None

# --- Conexión a Firebase ---
try:
    from conexion_firebase import obtener_productos, db, firestore
except ImportError:
    logging.critical("FATAL: No se pudo encontrar 'conexion_firebase.py' o no define 'db' y 'firestore'.")
    db = None
    firestore = None
    def obtener_productos():
        return {}

# ------------------------------------------------------------
# CONFIGURACIÓN INICIAL
# ------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = "freres_verificacion"
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")
DIALOGFLOW_PROJECT_ID = os.environ.get("DIALOGFLOW_PROJECT_ID")
DIALOGFLOW_LANGUAGE_CODE = "es"

if not PAGE_ACCESS_TOKEN or not DIALOGFLOW_PROJECT_ID:
    logging.critical("FALTAN VARIABLES DE ENTORNO (PAGE_ACCESS_TOKEN o DIALOGFLOW_PROJECT_ID)")

# ------------------------------------------------------------
# FUNCIÓN DE NORMALIZACIÓN DE TEXTO
# ------------------------------------------------------------
def normalizar_texto(texto: str, quitar_espacios=False) -> str:
    if not texto:
        return ""
    nfkd_form = unicodedata.normalize('NFD', texto)
    texto_sin_acentos = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    texto_lower = texto_sin_acentos.lower()
    translator = str.maketrans('', '', string.punctuation)
    texto_sin_puntuacion = texto_lower.translate(translator)
    if quitar_espacios:
        texto_sin_puntuacion = texto_sin_puntuacion.replace(" ", "")
    return texto_sin_puntuacion.strip()

# ------------------------------------------------------------
# 1️⃣ VERIFICACIÓN DEL WEBHOOK (GET)
# ------------------------------------------------------------
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("✅ Webhook verificado correctamente.")
        return challenge
    else:
        logging.error("❌ Error de verificación del webhook.")
        return "Token de verificación inválido", 403

# ------------------------------------------------------------
# 2️⃣ RECEPCIÓN DE MENSAJES (POST)
# ------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()
    if data.get("object") != "page": return "IGNORED", 200
    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            if "message" in event and not event.get("message", {}).get("is_echo"):
                sender_id = event["sender"]["id"]
                message_text_original = event["message"].get("text", "")
                logging.info(f"📩 Mensaje recibido de {sender_id}: {message_text_original}")
                thread = threading.Thread(
                    target=procesar_mensaje_en_background,
                    args=(sender_id, message_text_original)
                )
                thread.start()
    return "EVENT_RECEIVED", 200

# ------------------------------------------------------------
# 3️⃣ RUTA DE FULFILLMENT (Dialogflow)
# ------------------------------------------------------------
@app.route("/dialogflow-fulfillment", methods=["POST"])
def dialogflow_fulfillment():
    data = request.get_json(silent=True, force=True)
    if not data:
        return jsonify({"fulfillmentText": "Error: Solicitud inválida."})

    try:
        intent_name = data['queryResult']['intent']['displayName']
        parameters = data['queryResult'].get('parameters', {})
        texto_usuario = data['queryResult'].get('queryText', "")
        respuesta_texto = "No entendí bien tu solicitud."

        # === INTENT: Catálogo general ===
        if intent_name == "catalogo":
            productos_ref = db.collection("productos").stream()
            productos = [doc.to_dict() for doc in productos_ref]
            if productos:
                mensaje = "🛍️ Estos son algunos de nuestros productos:\n\n"
                for p in productos:
                    mensaje += f"🧸 {p.get('nombre','')}\n💵 ${p.get('precio','')} MXN\n📦 Stock: {p.get('stock',{}).get('Piezas','0')}\n🖼️ {p.get('imagen_url','')}\n\n"
                respuesta_texto = mensaje.strip()
            else:
                respuesta_texto = "😕 No hay productos disponibles en este momento."

        # === INTENT: Mostrar categorías ===
        elif intent_name == "ver_categorias":
            try:
                categorias = obtener_categorias_con_productos()
                if categorias:
                    mensaje = "🛍️ Estas son las categorías con productos disponibles:\n\n"
                    for cat, total in categorias:
                        mensaje += f"📂 {cat} ({total} productos)\n"
                    respuesta_texto = mensaje.strip()
                else:
                    respuesta_texto = "😕 No hay categorías registradas con productos."
            except Exception as e:
                logging.error(f"Error al obtener categorías Firebase: {e}")
                respuesta_texto = "Hubo un problema al consultar las categorías."

        # === INTENT: Buscar productos por categoría ===
        elif intent_name in ["buscar_categoria", "catalogo_categoria"]:
            try:
                categoria = parameters.get("categoria", "").capitalize()
                productos = obtener_productos_por_categoria(categoria)
                if productos:
                    mensaje = f"🎨 Productos en la categoría {categoria}:\n\n"
                    for p in productos:
                        mensaje += (
                            f"🧸 {p.get('nombre','(Sin nombre)')}\n"
                            f"💵 ${p.get('precio','N/D')} MXN\n"
                            f"📦 Stock: {p.get('stock',{}).get('Piezas','0')} unidades\n"
                            f"🖼️ {p.get('imagen_url','')}\n\n"
                        )
                    respuesta_texto = mensaje.strip()
                else:
                    respuesta_texto = f"No encontré productos en la categoría {categoria}."
            except Exception as e:
                logging.error(f"Error al buscar productos por categoría Firebase: {e}")
                respuesta_texto = "Ocurrió un error al consultar los productos."

        # === INTENT: Productos nuevos ===
        elif intent_name == "productos_nuevos":
            try:
                productos_ref = db.collection("productos").order_by("fecha_alta", direction=firestore.Query.DESCENDING).limit(5)
                productos = [doc.to_dict() for doc in productos_ref.stream()]
                if productos:
                    mensaje = "🆕 Estos son los productos más recientes:\n\n"
                    for p in productos:
                        mensaje += f"✨ {p.get('nombre','')} - ${p.get('precio','')} MXN\n🖼️ {p.get('imagen_url','')}\n\n"
                    respuesta_texto = mensaje.strip()
                else:
                    respuesta_texto = "Aún no hay productos nuevos registrados."
            except Exception as e:
                logging.error(f"Error en productos_nuevos: {e}")
                respuesta_texto = "Ocurrió un error al consultar los productos nuevos."

        # === INTENT: Búsqueda por color ===
        elif intent_name == "Busqueda_color":
            posibles_colores = ["rojo","azul","negro","blanco","verde","rosa","morado","dorado","plateado","beige"]
            color = next((p.capitalize() for p in texto_usuario.split() if p.lower() in posibles_colores), None)
            if not color:
                respuesta_texto = "🎨 Dime el color que te gustaría buscar (por ejemplo: rojo, negro o dorado)."
            else:
                try:
                    productos_ref = db.collection("productos").where("colores", "array_contains", color)
                    productos = [doc.to_dict() for doc in productos_ref.stream()]
                    if productos:
                        mensaje = f"🎨 Productos disponibles en color {color}:\n\n"
                        for p in productos:
                            mensaje += f"🧸 {p.get('nombre','')} - ${p.get('precio','')} MXN\n🖼️ {p.get('imagen_url','')}\n\n"
                        respuesta_texto = mensaje.strip()
                    else:
                        respuesta_texto = f"No encontré productos en color {color}."
                except Exception as e:
                    logging.error(f"Error buscando color: {e}")
                    respuesta_texto = "Hubo un error al buscar los productos por color."

        # === INTENT: Fallback ===
        elif intent_name == "Default Fallback Intent":
            respuesta_texto = "😅 No entendí bien. ¿Podrías repetirlo de otra forma?"

        # === RESPUESTA FINAL ===
        return jsonify({
            "fulfillmentMessages": [{"text": {"text": [respuesta_texto]}}]
        })

    except Exception as e:
        logging.error(f"Error en fulfillment: {e}")
        return jsonify({"fulfillmentText": "Error interno en el webhook."})

# ------------------------------------------------------------
# 4️⃣ FUNCIONES PRINCIPALES DE MENSAJERÍA Y LOGIN
# ------------------------------------------------------------
def procesar_mensaje_en_background(sender_id, message_text_original):
    try:
        respuesta_final = manejar_mensaje(sender_id, message_text_original)
        if respuesta_final and isinstance(respuesta_final, str) and respuesta_final.strip():
            enviar_mensaje(sender_id, respuesta_final)
    except Exception as e:
        logging.exception(f"🔥 Excepción en hilo para {sender_id}: {e}")
        enviar_mensaje(sender_id, "Lo siento, tuve un problema técnico. Intenta de nuevo más tarde.")

# ------------------------------------------------------------
# FUNCIONES AUXILIARES
# ------------------------------------------------------------
def detectar_intencion_dialogflow(session_id, texto):
    session_client = dialogflow.SessionsClient()
    session = session_client.session_path(DIALOGFLOW_PROJECT_ID, session_id)
    text_input = dialogflow.TextInput(text=texto, language_code=DIALOGFLOW_LANGUAGE_CODE)
    query_input = dialogflow.QueryInput(text=text_input)
    response = session_client.detect_intent(request={"session": session, "query_input": query_input})
    return response.query_result

def enviar_mensaje(id_usuario, texto):
    if not PAGE_ACCESS_TOKEN:
        logging.error("No se puede enviar mensaje, PAGE_ACCESS_TOKEN no está configurado.")
        return
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": id_usuario}, "message": {"text": texto}}
    requests.post(url, json=payload, timeout=10)

def enviar_imagen(id_usuario, imagen_url):
    if not PAGE_ACCESS_TOKEN:
        return
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": id_usuario},
        "message": {
            "attachment": {"type": "image", "payload": {"url": imagen_url, "is_reusable": True}}
        },
    }
    requests.post(url, json=payload, timeout=10)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Servidor Flask ejecutándose en 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


