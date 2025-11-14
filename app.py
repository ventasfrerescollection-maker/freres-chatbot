
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

# Inicializar Firestore
db = firestore.client()

# ------------------------------------------------------------
# CONFIGURACIÓN DEL SERVIDOR
# ------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = "freres_verificacion"
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")

if not PAGE_ACCESS_TOKEN:
    print("❌ ERROR: No se encontró PAGE_ACCESS_TOKEN")
else:
    print("✅ PAGE_ACCESS_TOKEN cargado correctamente")

# Estados por usuario
user_state = {}

# ------------------------------------------------------------
# NORMALIZACIÓN DEL TEXTO
# ------------------------------------------------------------
def normalizar(t):
    if not t:
        return ""
    t = t.lower().strip()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.translate(str.maketrans("", "", string.punctuation))
    t = " ".join(t.split())
    return t

# ------------------------------------------------------------
# ENVÍO DE MENSAJES A MESSENGER
# ------------------------------------------------------------
def enviar_mensaje(id_usuario, texto):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    requests.post(url, json={
        "recipient": {"id": id_usuario},
        "message": {"text": texto}
    })

def enviar_imagen(id_usuario, url_img):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    requests.post(url, json={
        "recipient": {"id": id_usuario},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {"url": url_img, "is_reusable": True}
            }
        }
    })

# ------------------------------------------------------------
# HELPERS: CATEGORÍAS, PRODUCTOS, CARRITO
# ------------------------------------------------------------
def construir_categorias(sender_id):
    productos = obtener_productos()
    categorias = {}

    for p in productos.values():
        cat = p.get("categoria", "Sin categoria")
        categorias[cat] = categorias.get(cat, 0) + 1

    lista = list(categorias.keys())

    user_state[sender_id]["estado"] = "elige_categoria"
    user_state[sender_id]["categorias_pendientes"] = lista
    user_state[sender_id].setdefault("carrito", [])

    msg = "🛍 *Categorías disponibles:*\n\n"
    for i, c in enumerate(lista, 1):
        msg += f"{i}. {c}\n"
    msg += "\n👉 Escribe el número o nombre de la categoría."

    return msg


def preparar_categoria(sender_id, categoria):
    productos = obtener_productos()
    lista = []

    for idp, datos in productos.items():
        if datos.get("categoria", "").lower() == categoria.lower():
            lista.append({"id": idp, "datos": datos})

    user_state[sender_id]["categoria_actual"] = categoria
    user_state[sender_id]["productos_categoria"] = lista
    user_state[sender_id]["indice_producto"] = 0

    return len(lista) > 0


def mostrar_producto(sender_id):
    estado = user_state.get(sender_id, {})
    productos = estado.get("productos_categoria", [])
    idx = estado.get("indice_producto", 0)

    if idx >= len(productos):
        return fin_categoria(sender_id)

    prod = productos[idx]
    pid = prod["id"]
    datos = prod["datos"]

    nombre = datos.get("nombre", "Sin nombre")
    precio = datos.get("precio", "N/A")
    img = datos.get("imagen_url", "")

    if img:
        enviar_imagen(sender_id, img)

    return (
        f"🔹 *{nombre}*\n"
        f"💰 ${precio} MXN\n"
        f"🆔 ID: {pid}\n\n"
        "Para agregarlo al pedido puedes escribir:\n"
        f"• si {pid}\n"
        f"• pedido {pid}\n"
        f"• o solo el ID: {pid}\n\n"
        "Para pasar al siguiente: *no* o *siguiente*\n"
        "Para terminar: *finalizar pedido*"
    )


def fin_categoria(sender_id):
    estado = user_state[sender_id]
    ultimo = estado.get("ultimo_mensaje", "")

    # FIX: Finalizar pedido aunque queden categorías
    if any(x in ultimo for x in [
        "finalizar", "finalizar pedido", "cerrar pedido", "terminar", "fin", "ya"
    ]):
        if estado.get("carrito"):
            return finalizar_pedido(sender_id)

    cat_actual = estado.get("categoria_actual")
    pendientes = estado.get("categorias_pendientes", [])
    carrito = estado.get("carrito", [])

    if cat_actual in pendientes:
        pendientes.remove(cat_actual)

    if pendientes:
        estado["estado"] = "elige_categoria"
        msg = f"✔ Ya no hay más productos en *{cat_actual}*.\n\nOtras categorías:\n"
        for i, c in enumerate(pendientes, 1):
            msg += f"{i}. {c}\n"
        msg += "\n👉 Escribe otra categoría o *finalizar pedido*."
        return msg

    if carrito:
        return finalizar_pedido(sender_id)

    estado["estado"] = "logueado"
    return "No agregaste productos. Escribe *catalogo* para comenzar."


def agregar_carrito(sender_id, pid):
    productos = obtener_productos()

    if pid not in productos:
        return "❌ Ese ID no existe."

    datos = productos[pid]

    user_state[sender_id].setdefault("carrito", [])
    user_state[sender_id]["carrito"].append({
        "id": pid,
        "nombre": datos.get("nombre"),
        "precio": datos.get("precio"),
        "categoria": datos.get("categoria")
    })

    return f"🛒 *{datos.get('nombre')}* agregado al pedido."


# ------------------------------------------------------------
# FINALIZAR PEDIDO (FIX DEFINITIVO — ID MANUAL)
# ------------------------------------------------------------
def finalizar_pedido(sender_id):
    estado = user_state[sender_id]
    carrito = estado.get("carrito", [])

    if not carrito:
        return "🛍 Tu carrito está vacío."

    # Calcular total
    total = sum(float(p.get("precio", 0)) for p in carrito)

    # Generar ID estable
    doc_ref = db.collection("pedidos").document()
    pedido_id = doc_ref.id

    pedido = {
        "telefono": estado.get("telefono"),
        "nombre": estado.get("nombre"),
        "fecha": datetime.now(),
        "estado": "pendiente",
        "productos": carrito,
        "total": total
    }

    doc_ref.set(pedido)

    user_state[sender_id]["estado"] = "elige_entrega"
    user_state[sender_id]["ultimo_pedido_id"] = pedido_id

    return (
        f"🧾 *Pedido registrado*: {pedido_id}\n\n"
        "📦 ¿Cómo deseas recibirlo?\n"
        "• Domicilio\n"
        "• Recoger en tienda\n\n"
        "Escribe una opción."
    )


# ------------------------------------------------------------
# CONSULTAR PEDIDO POR ID
# ------------------------------------------------------------
def consultar_pedido_por_id(pid):
    doc = db.collection("pedidos").document(pid).get()
    return doc.to_dict() if doc.exists else None


# ------------------------------------------------------------
# WEBHOOK GET
# ------------------------------------------------------------
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Token inválido", 403


# ------------------------------------------------------------
# WEBHOOK POST
# ------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def receive():
    data = request.get_json()

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and not event["message"].get("is_echo"):
                sender = event["sender"]["id"]
                texto = event["message"].get("text", "")
                msg = normalizar(texto)

                user_state.setdefault(sender, {})
                user_state[sender]["ultimo_mensaje"] = msg

                resp = manejar_mensaje(sender, msg)
                if resp:
                    enviar_mensaje(sender, resp)

    return "OK", 200


# ------------------------------------------------------------
# LÓGICA DEL BOT
# ------------------------------------------------------------
def manejar_mensaje(sender_id, msg):
    estado = user_state.get(sender_id, {}).get("estado", "inicio")

    # UNIVERSAL → Finalizar pedido desde cualquier modo
    if any(x in msg for x in ["finalizar", "finalizar pedido", "cerrar", "terminar", "fin", "ya"]):
        carrito = user_state.get(sender_id, {}).get("carrito", [])
        if carrito:
            return finalizar_pedido(sender_id)
        return "🛍 Tu carrito está vacío. Agrega un producto."

    # SALUDO
    if any(x in msg for x in ["hola", "buenas", "hello"]):
        return (
            "👋 Hola, soy Frere’s Collection.\n\n"
            "Puedo ayudarte con:\n"
            "🛍 Catalogo\n"
            "📝 Registrar\n"
            "🔐 Iniciar sesion\n"
            "📦 Consultar pedido\n"
            "🕒 Horario\n"
            "📞 Contacto"
        )

    # CONTACTO
    if "contacto" in msg or "whatsapp" in msg:
        return "📱 WhatsApp: *+52 55 1234 5678*"

    # HORARIO
    if "horario" in msg:
        return "🕒 Lunes a sábado: 10 AM – 7 PM."

    # CONSULTAR PEDIDO
    if msg.startswith("consultar") or msg.startswith("ver pedido") or msg.startswith("estado pedido"):
        partes = msg.split()
        if len(partes) < 2:
            return "❗ Usa: *consultar ID_DEL_PEDIDO*\nEjemplo: consultar z0Yjy1..."

        pid = partes[-1].strip()
        ped = consultar_pedido_por_id(pid)

        if not ped:
            return "❌ Pedido no encontrado."

        resp = f"🧾 *Pedido {pid}*\n📌 Estado: {ped['estado']}\n📦 Productos:\n"
        for p in ped["productos"]:
            resp += f"• {p['nombre']} – ${p['precio']} (ID: {p['id']})\n"

        resp += f"\n💵 Total: ${ped.get('total')}"
        return resp

    # REGISTRO
    if msg in ["registrar", "crear cuenta", "soy nuevo", "soy nueva"]:
        user_state[sender_id] = {"estado": "registrando_nombre"}
        return "📝 ¿Cuál es tu nombre completo?"

    if estado == "registrando_nombre":
        user_state[sender_id]["nombre"] = msg
        user_state[sender_id]["estado"] = "registrando_telefono"
        return "📱 Escribe tu número telefónico (10 dígitos)."

    if estado == "registrando_telefono":
        if not msg.isdigit() or len(msg) != 10:
            return "❌ Número inválido."
        user_state[sender_id]["telefono"] = msg
        user_state[sender_id]["estado"] = "registrando_direccion"
        return "📍 Escribe tu dirección completa."

    if estado == "registrando_direccion":
        nombre = user_state[sender_id]["nombre"]
        telefono = user_state[sender_id]["telefono"]

        db.collection("usuarios").document(telefono).set({
            "nombre": nombre,
            "telefono": telefono,
            "direccion": msg
        })

        user_state[sender_id]["estado"] = "logueado"
        user_state[sender_id]["direccion"] = msg

        return f"✨ Registro completado, {nombre}.\n\n" + construir_categorias(sender_id)

    # LOGIN
    if msg.startswith("iniciar sesion") or msg == "entrar":
        user_state[sender_id] = {"estado": "login"}
        return "🔐 Escribe tu número registrado."

    if estado == "login":
        doc = db.collection("usuarios").document(msg).get()
        if not doc.exists:
            return "❌ Número no registrado."
        data = doc.to_dict()

        user_state[sender_id] = {
            "estado": "logueado",
            "nombre": data["nombre"],
            "telefono": msg,
            "direccion": data["direccion"]
        }

        return f"✨ Bienvenido de nuevo, {data['nombre']}.\n\n" + construir_categorias(sender_id)

    # CATÁLOGO
    if "catalogo" in msg:
        return construir_categorias(sender_id)

    # ELEGIR CATEGORÍA
    if estado == "elige_categoria":
        categorias = user_state[sender_id].get("categorias_pendientes", [])
        cat = None

        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(categorias):
                cat = categorias[idx]
        else:
            for c in categorias:
                if c.lower() in msg:
                    cat = c
                    break

        if not cat:
            return "❌ Categoría no válida."

        if not preparar_categoria(sender_id, cat):
            return "❌ No hay productos en esa categoría."

        user_state[sender_id]["estado"] = "mostrando_producto"
        return mostrar_producto(sender_id)

    # ---------------- MOSTRAR PRODUCTO ----------------
if estado == "mostrando_producto":

    # Siguiente producto
    if msg in ["no", "siguiente", "next", "n", "skip"]:
        user_state[sender_id]["indice_producto"] += 1
            return mostrar_producto(sender_id)

    tokens = msg.split()
    pid = None

    # si ID
    if tokens[0] in ["si", "sí"] and len(tokens) > 1:
        token_id = tokens[1]
        productos = obtener_productos()
        if token_id in productos:
            pid = token_id

    # pedido ID
    elif tokens[0] == "pedido" and len(tokens) > 1:
        token_id = tokens[1]
        productos = obtener_productos()
        if token_id in productos:
            pid = token_id

    # mensaje completo es ID
    else:
        productos = obtener_productos()
        if msg in productos:
            pid = msg

    if pid:
        confirm = agregar_carrito(sender_id, pid)
        user_state[sender_id]["indice_producto"] += 1
        return confirm + "\n\n" + mostrar_producto(sender_id)

    return (
        "🤔 No entendí.\n"
        "Puedes escribir:\n"
        "• si ID\n"
        "• pedido ID\n"
        "• ID solo\n"
        "• no (para avanzar)\n"
        "• finalizar pedido"
    )

    # ENTREGA
    if estado == "elige_entrega":
        pid = user_state[sender_id]["ultimo_pedido_id"]

        if "domicilio" in msg:
            db.collection("pedidos").document(pid).update({
                "entrega": "domicilio",
                "direccion": user_state[sender_id]["direccion"]
            })
            user_state[sender_id]["estado"] = "logueado"
            return f"🚚 Enviado a domicilio.\n🧾 ID: {pid}"

        if "recoger" in msg or "tienda" in msg:
            db.collection("pedidos").document(pid).update({
                "entrega": "tienda"
            })
            user_state[sender_id]["estado"] = "logueado"
            return f"🏬 Listo para recoger en tienda.\n🧾 ID: {pid}"

        return "❌ Escribe *domicilio* o *recoger en tienda*."

    # FALLBACK
    return (
        "🤔 No entendí.\n\n"
        "Puedo ayudarte con:\n"
        "🛍 Catalogo\n"
        "📝 Registrar\n"
        "🔐 Iniciar sesion\n"
        "📦 Consultar pedido\n"
        "🕒 Horario\n"
        "📞 Contacto"
    )


# ------------------------------------------------------------
# EJECUCIÓN DEL SERVIDOR
# ------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🔥 Servidor ejecutándose en {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
