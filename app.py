# ------------------------------------------------------------
# ARCHIVO: app.py
# PROYECTO: Chatbot de Messenger – Frere’s Collection
# DESCRIPCIÓN:
#   Chatbot 100% Python con:
#   - Registro de usuarios
#   - Inicio de sesión
#   - Pedidos por ID
#   - Catálogo conectado a Firestore
#   - Sistema de estados
#   - Fallback profesional
#
# AUTOR: Fernando Ortiz (versión extendida)
# ------------------------------------------------------------


from flask import Flask, request
import requests
import logging
import os
import unicodedata
import string
from datetime import datetime

# Firebase
from conexion_firebase import obtener_productos
import firebase_admin
from firebase_admin import firestore

# Firestore client
db = firestore.client()

# ------------------------------------------------------------
# CONFIG SERVIDOR
# ------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = "freres_verificacion"
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")

if not PAGE_ACCESS_TOKEN:
    print("❌ ERROR: No se encontró PAGE_ACCESS_TOKEN en Render.")
else:
    print("✅ Token de página cargado correctamente.")

# Estados de usuarios
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
# ENVIAR MENSAJE TEXTO
# ------------------------------------------------------------
def enviar_mensaje(id_usuario, texto):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": id_usuario}, "message": {"text": texto}}
    requests.post(url, json=payload)

# ------------------------------------------------------------
# ENVIAR IMAGEN
# ------------------------------------------------------------
def enviar_imagen(id_usuario, imagen_url):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": id_usuario},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {"url": imagen_url, "is_reusable": True}
            }
        }
    }
    requests.post(url, json=payload)

# ------------------------------------------------------------
# 1️⃣ VERIFICACIÓN WEBHOOK
# ------------------------------------------------------------
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge
    return "Token inválido", 403

# ------------------------------------------------------------
# 2️⃣ RECIBIR MENSAJES
# ------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()

    if data.get("object") != "page":
        return "IGNORED", 200

    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            if "message" in event and not event["message"].get("is_echo"):
                sender_id = event["sender"]["id"]
                text = event["message"].get("text", "")
                msg_norm = normalizar(text)

                respuesta = manejar_mensaje(sender_id, msg_norm)

                if respuesta:
                    enviar_mensaje(sender_id, respuesta)

    return "EVENT_RECEIVED", 200

# ------------------------------------------------------------
# 3️⃣ LÓGICA DEL CHATBOT
# ------------------------------------------------------------
def manejar_mensaje(sender_id, message):

    # Obtener estado REAL
    estado = user_state.get(sender_id, {}).get("estado", "inicio")

    # --------------------------------------------------------
    # SALUDO
    # --------------------------------------------------------
    if any(p in message for p in ["hola", "buenas", "hello", "que tal"]):
        return (
            "👋 ¡Hola! Bienvenida a *Frere’s Collection* 💅👜\n"
            "Puedo ayudarte con:\n"
            "🛍️ *Catálogo*\n"
            "📝 *Registrar*\n"
            "🔐 *Iniciar sesión*\n"
            "🕒 *Horario*\n"
            "📞 *Contacto*"
        )

    # --------------------------------------------------------
    # CONTACTO
    # --------------------------------------------------------
    if "contacto" in message or "whatsapp" in message:
        return "📱 WhatsApp: *+52 55 1234 5678*"

    # --------------------------------------------------------
    # HORARIO
    # --------------------------------------------------------
    if "horario" in message:
        return "🕒 Lunes a sábado: 10 a.m. – 7 p.m."

    # --------------------------------------------------------
    # REGISTRO
    # --------------------------------------------------------
    if message in ["registrar", "crear cuenta", "soy nuevo", "soy nueva"]:
        user_state[sender_id] = {"estado": "registrando_nombre"}
        return "📝 ¡Perfecto! ¿Cuál es tu nombre completo?"

    # ETAPA 1: REGISTRAR NOMBRE
    if estado == "registrando_nombre":
        user_state[sender_id]["nombre"] = message
        user_state[sender_id]["estado"] = "registrando_telefono"
        return "📱 Excelente. Ahora escribe tu número telefónico (10 dígitos)."

    # ETAPA 2: REGISTRAR TELÉFONO
    if estado == "registrando_telefono":
        if not message.isdigit() or len(message) != 10:
            return "❌ El teléfono debe tener 10 dígitos."

        user_state[sender_id]["telefono"] = message
        user_state[sender_id]["estado"] = "registrando_direccion"
        return "📍 Perfecto. ¿Cuál es tu dirección completa?"

    # ETAPA 3: REGISTRAR DIRECCIÓN
    if estado == "registrando_direccion":
        nombre = user_state[sender_id]["nombre"]
        telefono = user_state[sender_id]["telefono"]
        direccion = message

        # Guardar en Firebase
        db.collection("usuarios").document(telefono).set({
            "nombre": nombre,
            "telefono": telefono,
            "direccion": direccion
        })

        user_state[sender_id] = {
            "estado": "logueado",
            "telefono": telefono,
            "nombre": nombre
        }

        return f"✨ ¡Registro completado, {nombre}! Ya puedes hacer pedidos."

    # --------------------------------------------------------
    # LOGIN
    # --------------------------------------------------------
    if "iniciar sesion" in message or "entrar" in message:
        user_state[sender_id] = {"estado": "login_telefono"}
        return "🔐 Escribe tu número telefónico registrado."

    if estado == "login_telefono":
        doc = db.collection("usuarios").document(message).get()
        if not doc.exists:
            return "❌ Ese número no está registrado. Escribe *registrar*."

        info = doc.to_dict()
        user_state[sender_id] = {
            "estado": "logueado",
            "telefono": message,
            "nombre": info.get("nombre", "Usuario")
        }

        return f"✨ Bienvenido de nuevo, {info.get('nombre')}."

    # --------------------------------------------------------
    # CATÁLOGO
    # --------------------------------------------------------
    if "catalogo" in message or "catálogo" in message:
        productos = obtener_productos()
        categorias = {}

        for p in productos.values():
            cat = p.get("categoria", "Sin categoria")
            categorias[cat] = categorias.get(cat, 0) + 1

        msg = "🛍️ *Categorías disponibles:*\n\n"
        for i, (cat, cant) in enumerate(categorias.items(), 1):
            msg += f"{i}. {cat} ({cant})\n"

        msg += "\n👉 Escribe el número o nombre de la categoría."

        user_state[sender_id] = {
            "estado": "esperando_categoria",
            "categorias": list(categorias.keys())
        }
        return msg

    # --------------------------------------------------------
    # MOSTRAR PRODUCTOS POR CATEGORÍA
    # --------------------------------------------------------
    if estado == "esperando_categoria":
        categorias = user_state[sender_id]["categorias"]
        productos = obtener_productos()

        # Número de categoría
        if message.isdigit():
            idx = int(message) - 1
            if 0 <= idx < len(categorias):
                categoria = categorias[idx]
            else:
                return "❌ Número inválido."
        else:
            categoria = next((c for c in categorias if c.lower() in message), None)

        if not categoria:
            return "❌ Categoría no reconocida."

        enviar_mensaje(sender_id, f"👜 *Productos en {categoria}:*")

        for id_prod, datos in productos.items():
            if datos.get("categoria", "").lower() == categoria.lower():
                nombre = datos.get("nombre", "Sin nombre")
                precio = datos.get("precio", "N/A")
                img = datos.get("imagen_url", "")

                enviar_mensaje(sender_id, f"🔹 *{nombre}*\n💰 ${precio} MXN\nID: {id_prod}")

                if img:
                    enviar_imagen(sender_id, img)

        user_state[sender_id]["estado"] = "logueado"
        return "✨ Escribe *pedido 1234* para pedir un producto por ID."

    # --------------------------------------------------------
    # PEDIDO POR ID
    # --------------------------------------------------------
    if message.startswith("pedido"):
        partes = message.split()

        if len(partes) < 2:
            return "🛒 Escribe así: *pedido 1023*"

        id_prod = partes[1]

        estado = user_state.get(sender_id, {})
        if estado.get("estado") != "logueado":
            return "🔐 Necesitas iniciar sesión."

        telefono = estado["telefono"]
        nombre = estado["nombre"]

        productos = obtener_productos()

        if id_prod not in productos:
            return "❌ No existe un producto con ese ID."

        prod = productos[id_prod]

        # Guardar pedido
        db.collection("pedidos").add({
            "telefono": telefono,
            "id_producto": id_prod,
            "fecha": datetime.now(),
            "estado": "pendiente"
        })

        return f"✔ Pedido registrado para *{prod['nombre']}*.\nGracias {nombre}, te contactaremos pronto."

    # --------------------------------------------------------
    # FALLBACK PROFESIONAL
    # --------------------------------------------------------
    return (
        "🤔 No entendí muy bien…\n\n"
        "Puedo ayudarte con:\n"
        "🛍️ *Catálogo*\n"
        "📝 *Registrar*\n"
        "🔐 *Iniciar sesión*\n"
        "🕒 *Horario*\n"
        "📞 *Contacto*"
    )


# ------------------------------------------------------------
# 5️⃣ EJECUCIÓN DEL SERVIDOR
# ------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🔥 Servidor ejecutándose en {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
