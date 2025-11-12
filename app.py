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
from flask import Flask, request, jsonify # ¡Añadido jsonify!
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

# --- ¡NUEVO! Configuración de Dialogflow ---
DIALOGFLOW_PROJECT_ID = os.environ.get("DIALOGFLOW_PROJECT_ID")
# GOOGLE_APPLICATION_CREDENTIALS se maneja automáticamente por Render si subiste el JSON
DIALOGFLOW_LANGUAGE_CODE = "es"

if not PAGE_ACCESS_TOKEN or not DIALOGFLOW_PROJECT_ID:
    # Este log aparecerá al inicio si faltan las variables
    logging.critical("FATAL: Faltan variables de entorno (PAGE_ACCESS_TOKEN o DIALOGFLOW_PROJECT_ID)")

# ------------------------------------------------------------
# FUNCIÓN DE NORMALIZACIÓN DE TEXTO
# ------------------------------------------------------------
def normalizar_texto(texto: str, quitar_espacios=False) -> str:
    """
    Convierte un texto a minúsculas, quita espacios, elimina acentos y puntuación.
    """
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
# 2.5 PROCESAMIENTO EN SEGUNDO PLANO
# ------------------------------------------------------------
def procesar_mensaje_en_background(sender_id, message_text_original):
    """
    Llama a la lógica principal (con Dialogflow) y maneja el envío de respuesta.
    """
    logging.info(f"THREAD: Iniciando procesamiento para {sender_id} (Texto Original: '{message_text_original}')...")
    
    try:
        respuesta_final = manejar_mensaje(sender_id, message_text_original)
        
        if respuesta_final and isinstance(respuesta_final, str) and respuesta_final.strip():
            logging.info(f"THREAD: Respuesta generada. Llamando a 'enviar_mensaje'...")
            enviar_mensaje(sender_id, respuesta_final)
        else:
            logging.warning(f"THREAD: 'manejar_mensaje' devolvió {repr(respuesta_final)}. No se envía respuesta.")
        
        logging.info(f"THREAD: Fin de procesamiento para {sender_id}.")
        
    except Exception as e:
        logging.exception(f"THREAD: 🔥 Excepción en el hilo para {sender_id}: {e}")
        enviar_mensaje(sender_id, "Lo siento, tuve un problema técnico. Intenta de nuevo más tarde.")

# ------------------------------------------------------------
# 2️⃣ RECEPCIÓN DE MENSAJES (POST)
# ------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def receive_message():
    """
    Recibe el mensaje de Messenger y lo pasa al hilo de procesamiento.
    """
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
# ¡NUEVO! 3️⃣ RUTA DE FULFILLMENT (La "Cocina" para Dialogflow)
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
                # === INTENT: Catálogo general o por categoría ===
                # === INTENT: Catálogo general o filtrado por categoría ===
              # === INTENT: Buscar categoría específica ===
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
        elif intent_name in ["buscar_categoria", "catalogo"]:
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

        # === INTENT: Realizar pedido ===
        elif intent_name == "realizar_pedido":
            from flujo_pedido import crear_pedido
            try:
                resultado = crear_pedido("usuario_demo", ["P001", "P002"])
                respuesta_texto = resultado
            except Exception as e:
                logging.error(f"Error al crear pedido: {e}")
                respuesta_texto = "Ocurrió un error al crear tu pedido."

        # === INTENT: Registro ===
        elif intent_name == "Registro":
            respuesta_texto = "✍️ ¡Perfecto! Empecemos tu registro.\n¿Podrías decirme tu nombre completo?"

        # === INTENT: Iniciar sesión ===
        elif intent_name == "iniciar_sesion":
            respuesta_texto = "🔐 Por favor, escribe tu número de teléfono a 10 dígitos para iniciar sesión."

        # === INTENT: Horario ===
        elif intent_name == "horario":
            respuesta_texto = "🕒 Nuestro horario de atención es de lunes a sábado de 10 a.m. a 7 p.m., y domingos de 10 a.m. a 4 p.m."

        # === INTENT: Contacto ===
        elif intent_name == "contacto":
            respuesta_texto = "📱 Puedes contactarnos por WhatsApp al +52 55 1234 5678 💬"

        # === INTENT: Saludo ===
        elif intent_name == "Saludo":
            respuesta_texto = "👋 ¡Hola! Bienvenido(a) a Frere’s Collection. ¿En qué te puedo ayudar hoy? 💼✨"

        # === INTENT: Despedida ===
        elif intent_name == "despedida":
            respuesta_texto = "💖 ¡Gracias por preferirnos! Estaré aquí cuando quieras ver más 👜✨"

        # === INTENT: Cerrar sesión ===
        elif intent_name == "cerrar_sesion":
            respuesta_texto = "👋 Has cerrado sesión correctamente. ¡Vuelve pronto!"

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
# 4️⃣ LÓGICA DE RESPUESTA (Router Principal)
# ------------------------------------------------------------

# --- Función de router principal ---
def manejar_mensaje(sender_id, message_text_original):
    """
    Función principal que decide si el usuario está logueado o no,
    y pasa el control al flujo de Dialogflow o de Login/Registro.
    """
    if not db:
        logging.error("FATAL: El cliente de Firestore 'db' no está inicializado.")
        return "😕 Lo siento, estoy teniendo problemas técnicos. Intenta más tarde."

    estado_ref = db.collection("sesiones").document(sender_id)
    try:
        estado_doc = estado_ref.get()
        estado = estado_doc.to_dict() if estado_doc.exists else {"estado": "inicio"}
    except Exception as e:
        logging.error(f"Error al LEER estado de Firebase para {sender_id}: {e}")
        estado = {"estado": "inicio"}

    telefono_logueado = estado.get("telefono_usuario")
    estado_actual = estado.get("estado", "inicio")

    # --- PASO 1: Manejar flujos LOCALES (Login/Registro) ---
    # Estos flujos (que piden datos) son los únicos que manejamos
    # localmente ANTES de llamar a Dialogflow.
    
    if estado_actual in [
        "esperando_telefono_login", 
        "registro_pidiendo_nombre", 
        "registro_pidiendo_direccion", 
        "registro_pidiendo_telefono_nuevo"
    ]:
        # El usuario está a mitad de un registro/login.
        return manejar_flujo_anonimo(estado_ref, estado, message_text_original)
    
    # --- PASO 2: Si no está en un flujo local, llamar a Dialogflow ---

    session_id_para_dialogflow = telefono_logueado if telefono_logueado else sender_id

    try:
        if not dialogflow:
            raise ImportError("Módulo 'dialogflow' no importado")
        
        respuesta_df = detectar_intencion_dialogflow(session_id_para_dialogflow, message_text_original)
        intent_name = respuesta_df.intent.display_name
        
        logging.info(f"Intención detectada por Dialogflow: {intent_name}")
        
        # --- PASO 3: Lógica post-Dialogflow ---
        
        # Manejamos intenciones "locales" que Dialogflow detecta
        # pero que no necesitan un webhook de fulfillment.
        
        if intent_name == "Login": # Asume que tienes una intención "Login"
            estado_ref.set({"estado": "esperando_telefono_login"})
            return "¡Perfecto! Escribe tu número de teléfono a 10 dígitos para iniciar sesión."
        
        elif intent_name == "Registro": # Asume que tienes una intención "Registro"
            estado_ref.set({"estado": "registro_pidiendo_nombre"})
            return "¡Genial! Empecemos tu registro. Por favor, escribe tu Nombre Completo."

        elif intent_name == "Logout": # Asume que tienes una intención "Logout"
            estado_ref.set({"estado": "inicio"}) # Borra la sesión
            return "Has cerrado sesión. Vuelve pronto."
        
        # Para todas las demás intenciones (Saludo, Catálogo, Pedido, Fallback)...
        # ...confiamos en la respuesta que Dialogflow ya preparó.
        # Si la intención requería un Webhook (como "VerEstadoPedido"),
        # Dialogflow ya llamó a nuestra ruta '/dialogflow-fulfillment',
        # la cual hizo la consulta a Firebase y le devolvió el texto.
        
        logging.info(f"Respuesta de Dialogflow/Fulfillment: {respuesta_df.fulfillment_text}")
        return respuesta_df.fulfillment_text

    except Exception as e:
        logging.exception(f"Error al llamar a 'detectar_intencion_dialogflow': {e}")
        return "😕 Lo siento, tuve un problema conectándome con mi cerebro (Dialogflow)."


# --- Flujo para usuarios ANÓNIMOS (SOLO PARA REGISTRO/LOGIN) ---
def manejar_flujo_anonimo(estado_ref, estado, message_text_original):
    estado_actual = estado.get("estado", "inicio")
    
    if estado_actual == "esperando_telefono_login":
        telefono = normalizar_texto(message_text_original, quitar_espacios=True)
        if not telefono.isdigit() or len(telefono) != 10:
            return "😕 Ese número no parece válido. Por favor, escribe tu número de teléfono a 10 dígitos (ej. 5512345678)."
        
        usuario_doc = db.collection("usuarios").document(telefono).get()
        if usuario_doc.exists:
            datos_usuario = usuario_doc.to_dict()
            nombre = datos_usuario.get("nombre", "Cliente")
            nuevo_estado = {"estado": "inicio", "telefono_usuario": telefono, "nombre_usuario": nombre}
            estado_ref.set(nuevo_estado)
            logging.info(f"Usuario {telefono} ha iniciado sesión.")
            return (
                f"👋 ¡Hola de nuevo, {nombre}! Has iniciado sesión. ¿En qué te puedo ayudar?\n"
                "Puedes preguntar por el *catálogo*, *horarios* o el *estado de un pedido*."
            )
        else:
            estado_ref.set({"estado": "inicio"})
            return "😕 No encontré un usuario con ese número. Escribe 'registrarme' para crear una cuenta o 'iniciar sesión' para intentarlo de nuevo."
    
    elif estado_actual == "registro_pidiendo_nombre":
        nombre_original = message_text_original.strip()
        if len(nombre_original) < 3:
            return "Por favor, escribe tu nombre completo."
        nuevo_estado = {"estado": "registro_pidiendo_direccion", "registro_cache": {"nombre": nombre_original}}
        estado_ref.set(nuevo_estado)
        return "¡Lindo nombre! Ahora, por favor escribe tu dirección de entrega."
    
    elif estado_actual == "registro_pidiendo_direccion":
        direccion_original = message_text_original.strip()
        registro_cache = estado.get("registro_cache", {})
        registro_cache["direccion"] = direccion_original
        nuevo_estado = {"estado": "registro_pidiendo_telefono_nuevo", "registro_cache": registro_cache}
        estado_ref.set(nuevo_estado)
        return "¡Perfecto! Finalmente, escribe tu número de teléfono a 10 dígitos. Este será tu ID de usuario."
    
    elif estado_actual == "registro_pidiendo_telefono_nuevo":
        telefono = normalizar_texto(message_text_original, quitar_espacios=True) 
        if not telefono.isdigit() or len(telefono) != 10:
            return "😕 Ese número no parece válido. Por favor, escribe tu número de teléfono a 10 dígitos (ej. 5512345678)."
        
        usuario_doc = db.collection("usuarios").document(telefono).get()
        if usuario_doc.exists:
            estado_ref.set({"estado": "inicio"})
            return "¡Un momento! Ese número de teléfono ya está registrado. Por favor, escribe 'iniciar sesión' para entrar con tu cuenta."
        else:
            registro_cache = estado.get("registro_cache", {})
            nombre = registro_cache.get("nombre", "N/A")
            direccion = registro_cache.get("direccion", "N/A")
            nuevo_usuario_data = {"nombre": nombre, "Direccion": direccion, "telefono": telefono, "Fecha_registro": date.today().strftime("%d/%m/%y"), "rol": "Cliente"}
            try:
                db.collection("usuarios").document(telefono).set(nuevo_usuario_data)
                nuevo_estado = {"estado": "inicio", "telefono_usuario": telefono, "nombre_usuario": nombre}
                estado_ref.set(nuevo_estado)
                logging.info(f"¡Nuevo usuario registrado! {telefono}")
                return (
                    f"👋 ¡Bienvenido, {nombre}! Tu registro está completo y has iniciado sesión. ¿En qué te puedo ayudar?\n"
                    "Puedes preguntar por el *catálogo*, *horarios* o el *estado de un pedido*."
                )
            except Exception as e:
                logging.error(f"Error al CREAR usuario en Firebase: {e}")
                estado_ref.set({"estado": "inicio"})
                return "😕 Hubo un error al crear tu cuenta. Por favor, intenta más tarde."
    
    # Si llega aquí, es un error de lógica
    return "Lo siento, me perdí. Volvamos a empezar. Escribe 'iniciar sesión' o 'registrarme'."


# ------------------------------------------------------------
# 5️⃣ FUNCIONES AUXILIARES Y DE ENVÍO
# ------------------------------------------------------------

# --- ¡NUEVO! Función de API de Dialogflow ---
def detectar_intencion_dialogflow(session_id, texto):
    """
    Envía el texto del usuario a la API de Dialogflow y devuelve la respuesta.
    Usa el sender_id de Messenger como session_id para Dialogflow
    """
    session_client = dialogflow.SessionsClient()
    session = session_client.session_path(DIALOGFLOW_PROJECT_ID, session_id)
    
    logging.info(f"Enviando a Dialogflow (Sesión: {session_id}): '{texto}'")
    
    text_input = dialogflow.TextInput(text=texto, language_code=DIALOGFLOW_LANGUAGE_CODE)
    query_input = dialogflow.QueryInput(text=text_input)
    
    try:
        response = session_client.detect_intent(request={"session": session, "query_input": query_input})
        return response.query_result
    except InvalidArgument as e:
        logging.error(f"Error de API de Dialogflow (InvalidArgument): {e}")
        raise e
    except Exception as e:
        logging.error(f"Error de API de Dialogflow (General): {e}")
        raise e


def enviar_mensaje(id_usuario, texto):
    """Envía texto simple al usuario a través de la API de Messenger."""
    if not PAGE_ACCESS_TOKEN:
        logging.error("No se puede enviar mensaje, PAGE_ACCESS_TOKEN no está configurado.")
        return
    
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": id_usuario}, "message": {"text": texto}}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        logging.info(f"Respuesta de API Messenger (Status {response.status_code}): {response.text}")
        if response.status_code != 200:
            logging.error(f"⚠️ Error al enviar mensaje: {response.text}")
        else:
            logging.info(f"✅ Mensaje enviado correctamente a {id_usuario}")
    except Exception as e:
        logging.exception(f"🔥 EXCEPCIÓN en requests.post (enviar_mensaje): {e}")


def enviar_imagen(id_usuario, imagen_url):
    """Envía una imagen al usuario (tipo attachment)."""
    if not PAGE_ACCESS_TOKEN:
        logging.error("No se puede enviar imagen, PAGE_ACCESS_TOKEN no está configurado.")
        return
        
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": id_usuario},
        "message": {
            "attachment": {"type": "image", "payload": {"url": imagen_url, "is_reusable": True}}
        },
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        logging.info(f"Respuesta de API Messenger (Imagen) (Status {response.status_code}): {response.text}")
        if response.status_code != 200:
            logging.error(f"⚠️ Error al enviar imagen: {response.text}")
        else:
            logging.info(f"🖼️ Imagen enviada correctamente a {id_usuario}")
    except Exception as e:
        logging.exception(f"🔥 EXCEPCIÓN en requests.post (enviar_imagen): {e}")
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Servidor Flask ejecutándose en 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)




