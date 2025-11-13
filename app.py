# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# CHATBOT DE FACEBOOK MESSENGER CON PYTHON + FIREBASE
# Basado en tus intents (Saludo, Catálogo, Color, Nuevos, Registro, Pedido)
# ------------------------------------------------------------

from flask import Flask, request, jsonify
import requests
import threading
import os
import unicodedata
import string
from datetime import datetime

# ------------------- IMPORTS DE TUS ARCHIVOS --------------------
from conexion_firebase import db, obtener_productos
from consultas_firebase import obtener_categorias_con_productos, obtener_productos_por_categoria
from flujo_pedido import crear_pedido
from registro_usuario import registrar_usuario


# ========================= CONFIG ================================
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")  # Token de Messenger
VERIFY_TOKEN = "freres_verificacion"

app = Flask(__name__)


# ================================================================
# 🧹 NORMALIZAR TEXTO (sin acentos, sin mayúsculas)
# ================================================================
def normalizar_texto(texto):
    if not texto:
        return ""
    nfkd_form = unicodedata.normalize('NFD', texto)
    texto_sin_acentos = "".join(c for c in nfkd_form if not unicodedata.combining(c))
    texto_lower = texto_sin_acentos.lower()
    translator = str.maketrans('', '', string.punctuation)
    return texto_lower.translate(translator).strip()


# ================================================================
# 📌 ENVIAR MENSAJE DE TEXTO A MESSENGER
# ================================================================
def enviar_texto(id_usuario, mensaje):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": id_usuario}, "message": {"text": mensaje}}
    requests.post(url, json=payload)


# ================================================================
# 📌 ENVIAR IMAGEN A MESSENGER
# ================================================================
def enviar_imagen(id_usuario, url_imagen):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": id_usuario},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {"url": url_imagen, "is_reusable": True}
            }
        }
    }
    requests.post(url, json=payload)


# ================================================================
# 📌 WEBHOOK VERIFICACIÓN FACEBOOK
# ================================================================
@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge
    return "Token de verificación inválido", 403


# ================================================================
# 📌 WEBHOOK MENSAJES (POST)
# ================================================================
@app.route("/webhook", methods=["POST"])
def recibir_mensaje():
    data = request.get_json()

    if data.get("object") != "page":
        return "IGNORED", 200

    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            if "message" in event:
                sender_id = event["sender"]["id"]
                texto = event["message"].get("text", "")

                hilo = threading.Thread(
                    target=procesar_mensaje,
                    args=(sender_id, texto)
                )
                hilo.start()

    return "EVENT_RECEIVED", 200


# ================================================================
# 📌 PROCESAR MENSAJE
# ================================================================
def procesar_mensaje(sender_id, mensaje):
    texto = normalizar_texto(mensaje)

    # ------------------------------------------
    # INTENT: SALUDO
    # ------------------------------------------
    if any(p in texto for p in ["hola", "que tal", "buenos dias", "buenas tardes", "buenas noches"]):
        enviar_texto(sender_id, "¡Hola! Bienvenido(a) a Frere's Collection. ¿En qué te puedo ayudar? 💼✨")
        return

    # ------------------------------------------
    # INTENT: DESPEDIDA
    # ------------------------------------------
    if any(p in texto for p in ["adios", "hasta luego", "eso es todo", "gracias"]):
        enviar_texto(sender_id, "💖 ¡Gracias por preferirnos! Estaré aquí cuando quieras ver más 👜✨")
        return

    # ------------------------------------------
    # INTENT: CONTACTO
    # ------------------------------------------
    if any(p in texto for p in ["whatsapp", "telefono", "numero", "contacto"]):
        enviar_texto(sender_id, "📱 Puedes contactarnos por WhatsApp al +52 55 1234 5678 💬")
        return

    # ------------------------------------------
    # INTENT: HORARIO
    # ------------------------------------------
    if any(p in texto for p in ["horario", "horarios", "a que hora abren", "a que hora cierran"]):
        enviar_texto(sender_id,
                     "🕒 Nuestro horario es de lunes a sábado de 10 a.m. a 7 p.m. y domingos de 10 a.m. a 4 p.m.")
        return

    # ------------------------------------------
    # INTENT: REGISTRO
    # ------------------------------------------
    if any(p in texto for p in ["registrarme", "crear cuenta", "quiero registrarme", "soy nuevo", "soy nueva"]):
        enviar_texto(sender_id, "✍️ ¡Perfecto! Empecemos tu registro.\nEscribe tu nombre completo.")
        return

    # ------------------------------------------
    # INTENT: INICIAR SESIÓN
    # ------------------------------------------
    if any(p in texto for p in ["iniciar sesion", "entrar a mi cuenta", "ya tengo cuenta"]):
        enviar_texto(sender_id, "🔐 Por favor escribe tu número de teléfono a 10 dígitos.")
        return

    # ------------------------------------------
    # INTENT: CATÁLOGO GENERAL
    # ------------------------------------------
    if any(p in texto for p in ["catalogo", "ver catalogo", "que productos tienes", "muestrame los productos"]):
        enviar_texto(sender_id, "🛍️ Tenemos varias categorías disponibles.\nEscribe la categoría que te interesa.")
        categorias = obtener_categorias_con_productos()
        msg = "📂 Categorías disponibles:\n\n"
        for cat, total in categorias:
            msg += f"• {cat} ({total} productos)\n"
        enviar_texto(sender_id, msg)
        return

    # ------------------------------------------
    # INTENT: PRODUCTOS NUEVOS
    # ------------------------------------------
    if any(p in texto for p in ["lo mas nuevo", "novedades", "productos recientes", "que hay de nuevo"]):
        enviar_texto(sender_id, "✨ Te mostraré los productos más nuevos.")
        productos_ref = db.collection("productos").order_by("fecha_alta", direction="DESCENDING").limit(5).stream()

        for p in productos_ref:
            d = p.to_dict()
            enviar_texto(sender_id,
                         f"✨ {d.get('nombre')}\n💵 ${d.get('precio')} MXN\n🖼️ {d.get('imagen_url')}")
            if d.get("imagen_url"):
                enviar_imagen(sender_id, d["imagen_url"])
        return

    # ------------------------------------------
    # INTENT: BÚSQUEDA POR COLOR
    # ------------------------------------------
    colores = ["rojo", "negro", "azul", "blanco", "rosa", "morado", "verde", "dorado", "plateado", "beige"]
    for color in colores:
        if color in texto:
            enviar_texto(sender_id, f"🎨 Buscando productos en color {color}...")
            productos = db.collection("productos").where("colores", "array_contains", color.capitalize()).stream()

            encontrados = False
            for p in productos:
                encontrados = True
                d = p.to_dict()
                enviar_texto(sender_id,
                             f"🧸 {d.get('nombre')}\n💵 ${d.get('precio')} MXN\n🖼️ {d.get('imagen_url')}")
                if d.get("imagen_url"):
                    enviar_imagen(sender_id, d["imagen_url"])

            if not encontrados:
                enviar_texto(sender_id, f"No encontré productos de color {color}.")
            return

    # ------------------------------------------
    # INTENT: REALIZAR PEDIDO
    # ------------------------------------------
    if any(p in texto for p in ["pedido", "realizar pedido", "realizar orden", "pedir producto"]):
        enviar_texto(sender_id, "🧾 ¿Quieres envío a domicilio o recoger en punto de entrega?")
        return

    # ================================================================
    # SI NO SE RECONOCE INTENT → MENSAJE DEFAULT
    # ================================================================
    enviar_texto(sender_id, "😅 No entendí bien tu mensaje. ¿Puedes repetirlo o probar con otra frase?")


# ================================================================
# 🚀 EJECUCIÓN EN RENDER
# ================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🔥 Servidor ejecutándose en 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
