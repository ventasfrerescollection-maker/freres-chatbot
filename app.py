@app.route('/webhook', methods=['POST'])
def webhook_dialogflow():
    data = request.get_json()
    
    # Extraer texto del usuario
    mensaje_usuario = data["queryResult"]["queryText"]
    session_id = data["session"].split("/")[-1]  # usar ID de sesión como sender_id

    # Procesar con tu lógica existente
    respuesta = manejar_mensaje(session_id, mensaje_usuario)

    # Responder a Dialogflow
    return jsonify({
        "fulfillmentText": respuesta
    })
