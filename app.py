from flask import Flask, request, jsonify
import os
from registro_usuario import registrar_usuario
from conexion_firebase import db  # Útil si deseas hacer consultas directas
from flujo_pedido import formatear_productos_para_usuario

app = Flask(__name__)

# ----------------------------
# RUTA DEL WEBHOOK PARA DIALOGFLOW
# ----------------------------
@app.route('/webhook', methods=['POST'])
def webhook_dialogflow():
    data = request.get_json()

    # Extraer mensaje, intención y sesión
    mensaje_usuario = data["queryResult"]["queryText"]
    intent_nombre = data["queryResult"]["intent"]["displayName"]
    session_id = data["session"].split("/")[-1]  # Este será el ID del usuario (puedes usarlo como teléfono)

    # Parámetros que llegan desde Dialogflow (como nombre, dirección)
    parametros = data["queryResult"].get("parameters", {})

    # ---- FLUJO DE REGISTRO DE USUARIO ----
    if intent_nombre == "RegistrarUsuario":
        nombre = parametros.get("nombre", "").strip()
        direccion = parametros.get("direccion", "").strip()

        if not nombre:
            return jsonify({"fulfillmentText": "¿Podrías indicarme tu nombre para registrarte?"})

        respuesta = registrar_usuario(telefono=session_id, nombre=nombre, direccion=direccion)
        return jsonify({"fulfillmentText": respuesta})

    # ---- SALUDO SIMPLE ----
    elif intent_nombre == "Saludo":
        return jsonify({"fulfillmentText": "¡Hola! Bienvenido a Frere's Collection 👛👜 ¿En qué puedo ayudarte hoy?"})

    # ---- MOSTRAR CATÁLOGO DE PRODUCTOS ----
    elif intent_nombre.lower() == "catalogo":
        respuesta = formatear_productos_para_usuario()
        return jsonify({"fulfillmentText": respuesta})

    # ---- RESPUESTA POR DEFECTO ----
    else:
        return jsonify({"fulfillmentText": "Ups, no he entendido a qué te refieres. ¿Puedes intentarlo de otra forma?"})

# ----------------------------
# EJECUCIÓN LOCAL
# ----------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
