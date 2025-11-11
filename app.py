from flask import Flask, request, jsonify
import os
from registro_usuario import registrar_usuario
from conexion_firebase import db
from flujo_pedido import formatear_productos_para_usuario

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook_dialogflow():
    data = request.get_json()

    mensaje_usuario = data["queryResult"]["queryText"]
    intent_nombre = data["queryResult"]["intent"]["displayName"]
    session_id = data["session"].split("/")[-1]
    parametros = data["queryResult"].get("parameters", {})

    # --- INTENTS PERSONALIZADOS SEGÚN TU DIALOGFLOW ---
    if intent_nombre == "Registro":
        nombre = parametros.get("nombre", "").strip()
        direccion = parametros.get("direccion", "").strip()

        if not nombre:
            return jsonify({"fulfillmentText": "¿Podrías indicarme tu nombre para registrarte?"})

        respuesta = registrar_usuario(telefono=session_id, nombre=nombre, direccion=direccion)
        return jsonify({"fulfillmentText": respuesta})

    elif intent_nombre == "Saludo":
        return jsonify({"fulfillmentText": "¡Hola! Bienvenido a Frere's Collection 👛👜 ¿En qué puedo ayudarte hoy?"})

    elif intent_nombre == "catalogo":
        respuesta = formatear_productos_para_usuario()
        return jsonify({"fulfillmentText": respuesta})

    elif intent_nombre == "despedida":
        return jsonify({"fulfillmentText": "¡Hasta luego! Gracias por visitar Frere's Collection 🌸"})

    elif intent_nombre == "horario":
        return jsonify({"fulfillmentText": "Nuestro horario de atención es de lunes a sábado, de 9 a.m. a 7 p.m."})

    elif intent_nombre == "contacto":
        return jsonify({"fulfillmentText": "Puedes escribirnos directamente por este medio o al WhatsApp 📱444 123 4567."})

    elif intent_nombre == "Default Fallback Intent":
        return jsonify({"fulfillmentText": "Ups, no he entendido a qué te refieres. ¿Puedes intentarlo de otra forma?"})

    # Puedes seguir agregando aquí: iniciar_sesion, realizar_pedido, productos_nuevos, etc.

    else:
        return jsonify({"fulfillmentText": "Lo siento, no tengo una respuesta para eso aún."})

# EJECUCIÓN LOCAL
# EJECUCIÓN COMPATIBLE CON RENDER
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # Render asigna el puerto dinámicamente
    print(f"🚀 Servidor ejecutándose en el puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=False)


