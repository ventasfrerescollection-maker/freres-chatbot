# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# CHATBOT DE FACEBOOK MESSENGER + FIREBASE
# Con fallback mejorado y correcciones para Render
# ------------------------------------------------------------

from flask import Flask, request
import requests
import threading
import os
import unicodedata
import string
from datetime import datetime

# -------------------------------------------
# IMPORTS DE ARCHIVOS LOCALES (CORREGIDOS)
# Detectamos si el archivo existe antes de importarlo
# -------------------------------------------
import importlib.util

def try_import(module_name, fallback=None):
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        print(f"⚠ ADVERTENCIA: No se encontró el módulo {module_name}. Continuando sin él.")
        return fallback
    return importlib.import_module(module_name)

# === IMPORTACIONES SEGUROS PARA RENDER ===
conexion = try_import("conexion_firebase")
consultas = try_import("consultas_firebase")
flujo = try_import("flujo_pedido")
registro = try_import("registro_usuario")

# Si los módulos cargaron bien, queda así:
db = conexion.db if conexion else None
obtener_productos = conexion.obtener_productos if conexion else lambda: {}

obtener_categorias_con_productos = consultas.obtener_categorias_con_productos if consultas else lambda: []
obtener_productos_por_categoria = consultas.obtener_productos_por_categoria if consultas else lambda c: []

crear_pedido = flujo.crear_pedido if flujo else lambda *args, **kwargs: "⚠ No disponible"
registrar_usuario = registro.registrar_usuario if registro else lambda *args: "⚠ Registro no disponible"


# -------------------------------------------
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = "freres_verificacion"

app = Flask(__name__)


# ================================================================
# NORMALIZACIÓN DE TEXTO
# ================================================================
def normalizar_texto(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFD', texto)
    texto = "".join(c for c in nfkd if not unicodedata.combining(c))
    texto = texto.lower()
    return texto.translate(str.maketrans("", "", string.punctuation)).strip()


# ================================================================
# ENVIAR TEXTO A MESSENGER
# ================================================================
def enviar_texto(id_usuario, mensaje):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    data = {"recipient": {"id": id_usuario}, "message": {"text": mensaje}}
    requests.post(url, json=data)


# ================================================================
# ENVIAR IMAGEN A MESSENGER
# ================================================================
def enviar_imagen(id_usuario, url_imagen):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    data = {
        "recipient": {"id": id_usuario},
        "message": {
            "attachment": {"type": "image", "payload": {"url": url_imagen, "is_reusable": True}}
        }
    }
    requests.post(url, json=data)


# ================================================================
# VERIFICACIÓN WEBHOOK FACEBOOK
# ================================================================
@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge
    return "Token inválido", 403


# ================================================================
# RECIBIR MENSAJES FACEBOOK
# ================================================================
@app.route("/webhook", methods=["POST"])
def recibir_mensaje():
    data = request.get_json()

    if data.get("object") != "page":
        return "IGNORED", 200

    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            if "message" in event:
                sender = event["sender"]["id"]
                texto = event["message"].get("text", "")

                hilo = threading.Thread(target=procesar_mensaje, args=(sender, texto))
                hilo.start()

    return "EVENT_RECEIVED", 200


# ================================================================
# PROCESAR MENSAJE (INTENTS)
# ================================================================
def procesar_mensaje(sender_id, mensaje):
    texto = normalizar_texto(mensaje)

    # ---------------- SALUDO ----------------
    if any(p in texto for p in ["hola", "que tal", "buenos dias", "buenas tardes", "buenas noches"]):
        enviar_texto(sender_id, "¡Hola! Bienvenido(a) a Frere's Collection. ¿En qué te puedo ayudar? 💼✨")
        return

    # ---------------- DESPEDIDA ----------------
    if any(p in texto for p in ["adios", "hasta luego", "eso es todo", "gracias"]):
        enviar_texto(sender_id, "💖 ¡Gracias por preferirnos! Estaré aquí cuando quieras ver más 👜✨")
        return

    # ---------------- CONTACTO ----------------
    if any(p in texto for p in ["contacto", "telefono", "numero", "whatsapp"]):
        enviar_texto(sender_id, "📱 Puedes contactarnos por WhatsApp al +52 55 1234 5678 💬")
        return

    # ---------------- HORARIO ----------------
    if any(p in texto for p in ["horario", "horarios", "a que hora abren", "a que hora cierran"]):
        enviar_texto(sender_id, "🕒 Nuestro horario es de lunes a sábado de 10 a.m. a 7 p.m. y domingos 10 a.m. a 4 p.m.")
        return

    # ---------------- REGISTRO ----------------
    if any(p in texto for p in ["registrarme", "crear cuenta", "soy nuevo", "soy nueva"]):
        enviar_texto(sender_id, "✍️ ¡Perfecto! Empecemos tu registro. ¿Cuál es tu nombre completo?")
        return

    # ---------------- INICIAR SESIÓN ----------------
    if any(p in texto for p in ["iniciar sesion", "entrar a mi cuenta", "ya tengo cuenta"]):
        enviar_texto(sender_id, "🔐 Por favor escribe tu número de teléfono a 10 dígitos.")
        return

    # ---------------- CATÁLOGO ----------------
    if any(p in texto for p in ["catalogo", "que productos tienes", "muestrame los productos"]):
        categorias = obtener_categorias_con_productos()
        enviar_texto(sender_id, "🛍️ Estas son las categorías disponibles:")
        msg = ""
        for cat, total in categorias:
            msg += f"📂 {cat} ({total})\n"
        enviar_texto(sender_id, msg)
        return

    # ---------------- PRODUCTOS NUEVOS ----------------
    if any(p in texto for p in ["lo mas nuevo", "novedades", "productos recientes", "que hay de nuevo"]):
        enviar_texto(sender_id, "✨ Mostrando los productos más nuevos...")
        productos_ref = db.collection("productos").order_by("fecha_alta", direction="DESCENDING").limit(5).stream()
        for p in productos_ref:
            d = p.to_dict()
            enviar_texto(sender_id, f"✨ {d.get('nombre')} - ${d.get('precio')} MXN")
            if d.get("imagen_url"):
                enviar_imagen(sender_id, d["imagen_url"])
        return

    # ---------------- BÚSQUEDA POR COLOR ----------------
    colores = ["rojo", "negro", "azul", "blanco", "rosa", "verde", "dorado", "plateado"]
    for color in colores:
        if color in texto:
            enviar_texto(sender_id, f"🎨 Buscando productos en color {color}…")
            productos = db.collection("productos").where("colores", "array_contains", color.capitalize()).stream()
            encontrado = False
            for p in productos:
                encontrado = True
                d = p.to_dict()
                enviar_texto(sender_id,
                    f"🧸 {d.get('nombre')}\n💵 ${d.get('precio')} MXN\n🖼 {d.get('imagen_url')}"
                )
                if d.get("imagen_url"):
                    enviar_imagen(sender_id, d["imagen_url"])
            if not encontrado:
                enviar_texto(sender_id, f"No encontré productos de color {color}.")
            return

    # ---------------- REALIZAR PEDIDO ----------------
    if any(p in texto for p in ["pedido", "realizar pedido", "realizar orden", "pedir producto"]):
        enviar_texto(sender_id, "🧾 ¿Quieres envío a domicilio o recoger en punto de entrega?")
        return

    # ---------------- FALLBACK MEJORADO ----------------
    fallback = (
        "🤔 No estoy seguro de haber entendido tu mensaje…\n\n"
        "Puedo ayudarte con:\n"
        "🛍️ Ver catálogo\n"
        "🎨 Buscar productos por color\n"
        "✨ Ver productos nuevos\n"
        "🧾 Realizar un pedido\n"
        "📞 Información de contacto\n\n"
        "¿Qué deseas hacer?"
    )
    enviar_texto(sender_id, fallback)


# ================================================================
# EJECUCIÓN EN RENDER
# ================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🔥 Servidor ejecutándose en {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
