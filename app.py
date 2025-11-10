# app.py
from flask import Flask, request, jsonify
import os
from registro_usuario import registrar_usuario
from conexion_firebase import db  # Solo si deseas hacer consultas directas

app = Flask(__name__)

# ----------------------------
# FUNCIÓN PRINCIPAL DE RUTEO
# ----------------------------

@app.route('/webhook', methods=['POST'])
def webhook_dialogflow():
    data = request.get_json()

    # Extraer texto y sesión del usuario
    mensaje_usuario = data["queryResult"]["queryText"]
    intent_nombre = data["queryResult"]["intent"]["displayName"]
    session_id = data["session"].split("/")[-1]  # Esto será nuestro ID de usuario/cliente

    # Puedes extraer parámetros si la intención los contiene
    parametros = data["queryResult"].get("parameters", {})

    # Lógica por intención
    if intent_nombre == "RegistrarUsuario":
        nombre = parametros.get("nombre", "").strip()
        direccion = parametros.get("direccion", "").strip()

        # Si falta el nombre, notificarlo (aunque Dialogflow debería forzar esto)
        if not nombre:
            return jsonify({"fulfillmentText": "¿Podrías indicarme tu nombre para registrarte?"})

        # Registrar usuario en Firestore
        respuesta = registrar_usuario(telefono=session_id, nombre=nombre, direccion=direccion)
        return jsonify({"fulfillmentText": respuesta})

    elif intent_nombre == "Saludo":
        return jsonify({"fulfillmentText": "¡Hola! Bienvenido a Frere's Collection. ¿En qué puedo ayudarte?"})

    else:
        return jsonify({"fulfillmentText": "Ups, no he entendido a qué te refieres. ¿Puedes intentarlo de nuevo?"})


# ----------------------------
# EJECUCIÓN LOCAL (opcional)
# ----------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
