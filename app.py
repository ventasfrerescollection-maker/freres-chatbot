# ------------------------------------------------------------
# ARCHIVO: app.py
# PROYECTO: Chatbot de Messenger – Frere’s Collection
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

# Cliente Firestore
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
# Estructura típica:
# {
#   "estado": "inicio" | "registrando_nombre" | "logueado" | "elige_categoria" | "mostrando_producto" | ...
#   "nombre": "...",
#   "telefono": "...",
#   "categorias_pendientes": [...],
#   "categoria_actual": "...",
#   "productos_categoria": [{"id": "123", "datos": {...}}, ...],
#   "indice_producto": 0,
#   "carrito": [ { "id": "123", "nombre": "...", "precio": 100, "categoria": "Bolsos" }, ... ]
# }
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
# AUXILIARES: CATEGORÍAS, PRODUCTOS, CARRITO, PEDIDOS
# ------------------------------------------------------------
def construir_categorias_y_guardar_en_estado(sender_id):
    """
    Obtiene las categorías desde Firebase y las guarda en el estado del usuario.
    También prepara el carrito si no existe.
    """
    productos = obtener_productos()
    categorias = {}

    for p in productos.values():
        cat = p.get("categoria", "Sin categoria")
        categorias[cat] = categorias.get(cat, 0) + 1

    categorias_lista = list(categorias.keys())

    if sender_id not in user_state:
        user_state[sender_id] = {}

    user_state[sender_id].setdefault("carrito", [])
    user_state[sender_id]["estado"] = "elige_categoria"
    user_state[sender_id]["categorias_pendientes"] = categorias_lista

    if not categorias_lista:
        return "😕 No hay productos en este momento."

    msg = "🛍️ *Categorías con productos:*\n\n"
    for i, cat in enumerate(categorias_lista, 1):
        msg += f"{i}. {cat}\n"

    msg += "\n👉 Escribe el número o el nombre de la categoría que quieres ver."
    return msg

def preparar_productos_de_categoria(sender_id, categoria):
    """
    Llena en user_state la lista de productos de la categoría elegida
    y posiciona el índice en el primer producto.
    """
    productos = obtener_productos()
    lista = []

    for id_prod, datos in productos.items():
        if datos.get("categoria", "").lower() == categoria.lower():
            lista.append({"id": id_prod, "datos": datos})

    user_state[sender_id]["categoria_actual"] = categoria
    user_state[sender_id]["productos_categoria"] = lista
    user_state[sender_id]["indice_producto"] = 0

    if not lista:
        return False
    return True

def mostrar_producto_actual(sender_id):
    """
    Devuelve el texto para mostrar el producto actual de la categoría.
    Si ya no hay más productos en la categoría, pasa a manejar el fin de categoría.
    """
    estado = user_state.get(sender_id, {})
    productos_cat = estado.get("productos_categoria", [])
    indice = estado.get("indice_producto", 0)

    if indice >= len(productos_cat):
        # Ya no hay productos en esta categoría
        return manejar_fin_de_categoria(sender_id)

    prod_info = productos_cat[indice]
    pid = prod_info["id"]
    datos = prod_info["datos"]

    nombre = datos.get("nombre", "Sin nombre")
    precio = datos.get("precio", "N/A")
    img = datos.get("imagen_url", "")

    texto = (
        f"🔹 *{nombre}*\n"
        f"💰 ${precio} MXN\n"
        f"🆔 ID: {pid}\n\n"
        "Para agregarlo al pedido, puedes escribir:\n"
        f"• *pedido {pid}*\n"
        f"• *si {pid}*\n"
        f"• Solo el ID: *{pid}*\n"
        "O escribe *no* para ver el siguiente producto.\n"
        "También puedes escribir *finalizar pedido* para cerrar tu compra."
    )

    # Enviar imagen si existe
    if img:
        enviar_imagen(sender_id, img)

    return texto

def manejar_fin_de_categoria(sender_id):
    """
    Se llama cuando ya no hay más productos en la categoría actual.
    Pregunta si quiere ver otra categoría o finalizar pedido.
    Si no quedan categorías y hay carrito -> finaliza pedido.
    Si no quedan categorías ni carrito -> vuelve a logueado.
    """
    estado = user_state.get(sender_id, {})
    cat_actual = estado.get("categoria_actual", "esa categoría")

    # Quitar categoría actual de pendientes
    categorias_pendientes = estado.get("categorias_pendientes", [])
    if cat_actual in categorias_pendientes:
        categorias_pendientes.remove(cat_actual)
    user_state[sender_id]["categorias_pendientes"] = categorias_pendientes

    carrito = estado.get("carrito", [])

    if categorias_pendientes:
        msg = (
            f"✅ Ya no hay más productos en *{cat_actual}*.\n\n"
            "¿Quieres ver otra categoría?\n\n"
            "Categorías restantes:\n"
        )
        for i, cat in enumerate(categorias_pendientes, 1):
            msg += f"{i}. {cat}\n"
        msg += "\n👉 Escribe el número o el nombre de la categoría.\n"
        msg += "O escribe *finalizar pedido* para cerrar tu compra."
        user_state[sender_id]["estado"] = "elige_categoria"
        return msg
    else:
        # No hay más categorías
        if carrito:
            return finalizar_pedido(sender_id)
        else:
            user_state[sender_id]["estado"] = "logueado"
            return (
                "😕 Ya no quedan categorías con productos y no agregaste nada al carrito.\n"
                "Si quieres, escribe *catalogo* para ver de nuevo."
            )

def agregar_producto_a_carrito(sender_id, id_prod):
    """
    Agrega un producto al carrito del usuario si existe en la base.
    Devuelve un texto de confirmación o error.
    """
    productos = obtener_productos()
    if id_prod not in productos:
        return "❌ No encontré un producto con ese ID."

    datos = productos[id_prod]
    nombre = datos.get("nombre", "Sin nombre")
    precio = datos.get("precio", 0)
    categoria = datos.get("categoria", "Sin categoria")

    if sender_id not in user_state:
        user_state[sender_id] = {}

    user_state[sender_id].setdefault("carrito", [])
    user_state[sender_id]["carrito"].append({
        "id": id_prod,
        "nombre": nombre,
        "precio": precio,
        "categoria": categoria
    })

    return f"🛒 Se agregó *{nombre}* (ID: {id_prod}) a tu pedido."

def finalizar_pedido(sender_id):
    """
    Cierra el pedido: lo guarda en Firestore con un ID y regresa
    un resumen + el ID de pedido.
    """
    estado = user_state.get(sender_id, {})
    carrito = estado.get("carrito", [])
    telefono = estado.get("telefono", "N/D")
    nombre = estado.get("nombre", "Cliente")

    if not carrito:
        return "🛍 No tienes productos en tu pedido. Escribe *catalogo* para ver productos."

    # Calcular total (si los precios son numéricos)
    total = 0
    for item in carrito:
        try:
            total += float(item.get("precio", 0))
        except Exception:
            pass

    pedido_data = {
        "telefono": telefono,
        "nombre": nombre,
        "fecha": datetime.now(),
        "estado": "pendiente",
        "productos": carrito,
        "total": total
    }

    doc_ref, _ = db.collection("pedidos").add(pedido_data)
    pedido_id = doc_ref.id

    # Limpiar carrito y estados de categorías
    user_state[sender_id]["carrito"] = []
    user_state[sender_id]["categorias_pendientes"] = []
    user_state[sender_id]["categoria_actual"] = None
    user_state[sender_id]["productos_categoria"] = []
    user_state[sender_id]["indice_producto"] = 0
    user_state[sender_id]["estado"] = "logueado"

    msg = "✅ Tu pedido ha sido registrado.\n\n"
    msg += f"🧾 *ID de pedido:* {pedido_id}\n\n"
    msg += "📦 Productos:\n"
    for item in pedido_data["productos"]:
        msg += f"• {item['nombre']} (ID: {item['id']}) – ${item['precio']} MXN\n"

    msg += f"\n💵 Total aproximado: ${total} MXN\n"
    msg += "\nGuarda este ID para consultar tu pedido más adelante."

    return msg

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

    estado = user_state.get(sender_id, {}).get("estado", "inicio")

    # --------------------------------------------------------
    # SALUDO
    # --------------------------------------------------------
    if any(p in message for p in ["hola", "buenas", "hello", "que tal"]):
        return (
            "👋 ¡Hola! Bienvenida a *Frere’s Collection* 💅👜\n"
            "Puedo ayudarte con:\n"
            "🛍️ *Catalogo*\n"
            "📝 *Registrar*\n"
            "🔐 *Iniciar sesion*\n"
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

        db.collection("usuarios").document(telefono).set({
            "nombre": nombre,
            "telefono": telefono,
            "direccion": direccion
        })

        user_state[sender_id]["estado"] = "logueado"
        user_state[sender_id]["nombre"] = nombre

        # Al terminar registro, iniciamos flujo de categorías
        msg_categorias = construir_categorias_y_guardar_en_estado(sender_id)
        return f"✨ ¡Registro completado, {nombre}! Ya puedes hacer pedidos.\n\n{msg_categorias}"

    # --------------------------------------------------------
    # LOGIN
    # --------------------------------------------------------
    if "iniciar sesion" in message or message == "entrar":
        user_state[sender_id] = {"estado": "login_telefono"}
        return "🔐 Escribe tu número telefónico registrado."

    if estado == "login_telefono":
        doc = db.collection("usuarios").document(message).get()
        if not doc.exists:
            return "❌ Ese número no está registrado. Escribe *registrar* para crear una cuenta."

        info = doc.to_dict()
        user_state[sender_id] = {
            "estado": "logueado",
            "telefono": message,
            "nombre": info.get("nombre", "Cliente")
        }

        msg_categorias = construir_categorias_y_guardar_en_estado(sender_id)
        return f"✨ Bienvenido de nuevo, {info.get('nombre')}.\n\n{msg_categorias}"

    # --------------------------------------------------------
    # CATÁLOGO MANUAL
    # --------------------------------------------------------
    if "catalogo" in message or "catalogo" in message:
        # Si está logueado, mostramos categorías con flujo de carrito
        if user_state.get(sender_id, {}).get("estado") == "logueado":
            return construir_categorias_y_guardar_en_estado(sender_id)
        else:
            # No logueado: solo mostrar categorías, pero sin carrito
            return construir_categorias_y_guardar_en_estado(sender_id)

    # --------------------------------------------------------
    # ELECCIÓN DE CATEGORÍA (DESPUÉS DE LOGIN/REGISTRO)
    # --------------------------------------------------------
    if estado == "elige_categoria":
        estado_user = user_state.get(sender_id, {})
        categorias_pend = estado_user.get("categorias_pendientes", [])

        if not categorias_pend:
            return "😕 No hay categorías disponibles ahora mismo."

        # El usuario puede responder con número o con texto
        categoria = None

        if message.isdigit():
            idx = int(message) - 1
            if 0 <= idx < len(categorias_pend):
                categoria = categorias_pend[idx]
        else:
            for cat in categorias_pend:
                if cat.lower() in message:
                    categoria = cat
                    break

        if not categoria:
            return "❌ No reconocí esa categoría. Escribe el número o el nombre que aparece en la lista."

        # Preparar productos de esa categoría
        tiene_productos = preparar_productos_de_categoria(sender_id, categoria)
        if not tiene_productos:
            return f"😕 No se encontraron productos en la categoría *{categoria}*."

        user_state[sender_id]["estado"] = "mostrando_producto"
        return mostrar_producto_actual(sender_id)

    # --------------------------------------------------------
    # MOSTRANDO PRODUCTO (AGREGAR / SIGUIENTE / FINALIZAR)
    # --------------------------------------------------------
    if estado == "mostrando_producto":
        # Finalizar pedido directo
        if "finalizar pedido" in message or message == "finalizar":
            return finalizar_pedido(sender_id)

        # Saltar producto (no)
        if message in ["no", "siguiente"]:
            user_state[sender_id]["indice_producto"] = user_state[sender_id].get("indice_producto", 0) + 1
            return mostrar_producto_actual(sender_id)

        # Intentos de agregar producto al carrito
        tokens = message.split()
        id_para_agregar = None

        # 1) "pedido 123"
        if message.startswith("pedido"):
            if len(tokens) >= 2 and tokens[1].isdigit():
                id_para_agregar = tokens[1]
            else:
                # Si no hay ID, tomar el producto actual
                est = user_state.get(sender_id, {})
                productos_cat = est.get("productos_categoria", [])
                idx = est.get("indice_producto", 0)
                if 0 <= idx < len(productos_cat):
                    id_para_agregar = productos_cat[idx]["id"]

        # 2) "si 123" o "sí 123"
        elif tokens[0] in ["si", "si,", "si."]:
            if len(tokens) >= 2 and tokens[1].isdigit():
                id_para_agregar = tokens[1]
            else:
                # si solo escribe "si", tomar producto actual
                est = user_state.get(sender_id, {})
                productos_cat = est.get("productos_categoria", [])
                idx = est.get("indice_producto", 0)
                if 0 <= idx < len(productos_cat):
                    id_para_agregar = productos_cat[idx]["id"]

        # 3) solo el ID (ej: "1023")
        elif message.isdigit():
            id_para_agregar = message

        if id_para_agregar:
            confirm = agregar_producto_a_carrito(sender_id, id_para_agregar)
            # Pasar al siguiente producto automáticamente
            user_state[sender_id]["indice_producto"] = user_state[sender_id].get("indice_producto", 0) + 1
            siguiente = mostrar_producto_actual(sender_id)
            return f"{confirm}\n\n{siguiente}"

        # Si nada de lo anterior encaja:
        return (
            "🤔 No te entendí en esta parte.\n"
            "Puedes escribir *pedido ID*, *si ID*, solo el *ID*, o *no* para ver el siguiente producto.\n"
            "También *finalizar pedido* para cerrar tu compra."
        )

    # --------------------------------------------------------
    # PEDIDO DIRECTO POR ID (FUERA DEL FLUJO)
    # --------------------------------------------------------
    if message.startswith("pedido"):
        estado_user = user_state.get(sender_id, {})
        if estado_user.get("estado") != "logueado":
            return "🔐 Necesitas iniciar sesión para hacer un pedido. Escribe *iniciar sesion*."

        tokens = message.split()
        if len(tokens) < 2:
            return "🛒 Escribe así: *pedido 1023*"

        id_prod = tokens[1]
        confirm = agregar_producto_a_carrito(sender_id, id_prod)
        return f"{confirm}\n\nSi quieres finalizar, escribe *finalizar pedido* o mira más productos con *catalogo*."

    # --------------------------------------------------------
    # FALLBACK PROFESIONAL
    # --------------------------------------------------------
    return (
        "🤔 No entendí muy bien…\n\n"
        "Puedo ayudarte con:\n"
        "🛍️ *Catalogo*\n"
        "📝 *Registrar*\n"
        "🔐 *Iniciar sesion*\n"
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
