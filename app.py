# app.py

from flask import Flask, request, jsonify

app = Flask(__name__)  # ← ESTA LÍNEA es indispensable antes de usar @app.route

@app.route('/webhook', methods=['POST'])
def webhook_dialogflow():
    data = request.get_json()
    mensaje_usuario = data["queryResult"]["queryText"]
    session_id = data["session"].split("/")[-1]

    respuesta = manejar_mensaje(session_id, mensaje_usuario)

    return jsonify({
        "fulfillmentText": respuesta
    })
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
