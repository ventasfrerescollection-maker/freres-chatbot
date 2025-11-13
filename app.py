# ------------------------------------------------------------
# ARCHIVO: app.py
# PROYECTO: Chatbot de Messenger – Frere’s Collection
# DESCRIPCIÓN:
#   Chatbot 100% Python (sin Dialogflow), con estados,
#   catálogo, categorías, fallback avanzado y conexión
#   directa con Firebase.
#
# AUTOR: Fernando Ortiz (versión mejorada)
# ------------------------------------------------------------

# --- Importación de librerías necesarias ---
from flask import Flask, request
import requests
import logging
from conexion_firebase import obtener_productos   # Firebase
import unicodedata
import string

# ------------------------------------------------------------
# CONFIGURACIÓN INICIAL
# ------------------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = "freres_verificacion"

PAGE_ACCESS_TOKEN = "PAGE_ACCESS_TOKEN"   # <-- reemplazar

# Diccionario de estados por usuario
user_state = {}

# ------------------------------------------------------------
# NORMALIZAR TEXTO
# ------------------------------------------------------------
def normalizar(texto):
    if not texto:
        return ""
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.translate(str.maketrans("", "", string.punctuation))
    return texto.strip()


# ------------------------------------------------------------
# 1️⃣ VERIFICACIÓN WEBHOOK
# ------------------------------------------------------------
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verificado correctamente.")
        return challenge
    else:
        print("❌ Token de verificación inválido.")
        return "Token inválido", 403


# ------------------------------------------------------------
# 2️⃣ RECEPCIÓN DE MENSAJES
# ------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()

    if data.get("object") != "page":
        return "IGNORED", 200

    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            if "message" in event and not event.get("message", {}).get("is_echo"):
                sender_id = event["sender"]["id"]
                message_text = event["message"].get("text", "")
                message_text_norm = normalizar(message_text)

                respuesta = manejar_mensaje(sender_id, message_text_norm)

                if respuesta:
                    enviar_mensaje(sender_id, respuesta)

    return "EVENT_RECEIVED", 200


# ------------------------------------------------------------
# 3️⃣ LÓGICA PRINCIPAL DEL CHATBOT
# ------------------------------------------------------------
def manejar_mensaje(sender_id, message):
    estado_actual = user_state.get(sender_id, "inicio")

    # ---------------------------
    # INTENTS GLOBAL DE RESPUESTA
    # ---------------------------

    # Saludo
    if any(p in message for p in ["hola", "que tal", "buenas", "hello"]):
        return (
            "👋 ¡Hola! Bienvenida a *Frere’s Collection 💅👜*\n\n"
            "Puedo ayudarte con:\n"
            "🛍️ *Catálogo*\n"
            "🕒 *Horario*\n"
            "📞 *Contacto*"
        )

    # Horario
    if "horario" in message:
        return "🕒 Nuestro horario es de *lunes a sábado, de 10 a.m. a 7 p.m.*"

    # Contacto
    if "contacto" in message or "whatsapp" in message:
        return "📱 Puedes contactarnos por WhatsApp al *+52 55 1234 5678*."

    # ---------------------------
    # INTENT: CATÁLOGO PRINCIPAL
    # ---------------------------
    if "catalogo" in message or "catálogo" in message:
        productos = obtener_productos()
        categorias = {}

        for p in productos.values():
            cat = p.get("categoria", "Sin categoría")
            categorias[cat] = categorias.get(cat, 0) + 1

        if categorias:
            msg = "🛍️ *Categorías disponibles:*\n\n"
            for i, (cat, cant) in enumerate(categorias.items(), start=1):
                msg += f"{i}. {cat} ({cant})\n"
            msg += "\n👉 Escribe el número o el nombre de la categoría."

            # Guardamos estado
            user_state[sender_id] = {
                "estado": "esperando_categoria",
                "categorias": list(categorias.keys())
            }
            return msg
        else:
            return "😕 No hay productos en este momento."

    # ---------------------------
    # ESTADO: ESPERANDO CATEGORÍA
    # ---------------------------
    if isinstance(estado_actual, dict) and estado_actual.get("estado") == "esperando_categoria":
        categorias = estado_actual["categorias"]
        productos = obtener_productos()

        # si escribe número
        if message.isdigit():
            idx = int(message) - 1
            if 0 <= idx < len(categorias):
                categoria = categorias[idx]
            else:
                return "❌ Número inválido. Intenta de nuevo."
        else:
            categoria = next((c for c in categorias if c.lower() in message), None)

        if categoria:
            enviar_mensaje(sender_id, f"👜 *Productos en la categoría {categoria}:*")

            encontrados = False
            piezas_temp = "No disponible"

            for prod in productos.values():
                if prod.get("categoria", "").lower() == categoria.lower():
                    encontrados = True

                    nombre = prod.get("nombre", "Sin nombre")
                    precio = prod.get("precio", "N/A")
                    imagen = prod.get("imagen_url", "")
                    stock_info = prod.get("stock", {})
                    piezas_temp = stock_info.get("Piezas", "N/D")

                    enviar_mensaje(sender_id, f"🔹 *{nombre}* — 💰 ${precio} MXN")

                    if imagen:
                        enviar_imagen(sender_id, imagen)

            enviar_mensaje(sender_id, f"📦 Piezas disponibles: {piezas_temp}")

            user_state[sender_id] = "inicio"

            if not encontrados:
                return f"😕 No hay productos en la categoría *{categoria}*."

            return "✨ Escribe *catálogo* para volver al menú."

        else:
            return "❌ No reconocí esa categoría. Intenta de nuevo."

    # ---------------------------
    # FALLBACK PROFESIONAL
    # ---------------------------
    fallback = (
        "🤔 No entendí muy bien lo que quisiste decir…\n\n"
        "Puedo ayudarte con:\n"
        "🛍️ Ver *catálogo*\n"
        "🎨 Buscar por *categoría*\n"
        "🕒 Ver *horario*\n"
        "📞 Ver *contacto*\n\n"
        "¿Qué deseas hacer?"
    )

    return fallback


# ------------------------------------------------------------
# 4️⃣ FUNCIONES PARA ENVIAR MENSAJES
# ------------------------------------------------------------
def enviar_mensaje(id_usuario, texto):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": id_usuario}, "message": {"text": texto}}
    requests.post(url, json=payload)


def enviar_imagen(id_usuario, imagen_url):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": id_usuario},
        "message": {
            "attachment": {"type": "image", "payload": {"url": imagen_url, "is_reusable": True}}
        }
    }
    requests.post(url, json=payload)


# ------------------------------------------------------------
# 5️⃣ EJECUCIÓN DEL SERVIDOR
# ------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🔥 Servidor ejecutándose en {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
