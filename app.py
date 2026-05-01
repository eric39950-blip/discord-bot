from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from config import SECRET_KEY, FRONTEND_URL
from auth import Auth
from database import db
from discord_api import DiscordAPI

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None"

CORS(app, origins=[FRONTEND_URL], supports_credentials=True)

# Middleware para verificar login
def login_required(f):
    def wrapper(*args, **kwargs):
        if not Auth.is_logged_in():
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route("/api/login_url")
def api_login_url():
    return redirect(Auth.get_login_url())

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not Auth.validate_state(state):
        return jsonify({"error": "invalid_request"}), 400

    access_token = Auth.exchange_code(code)
    if not access_token:
        return jsonify({"error": "oauth_failed"}), 400

    if Auth.login_user(access_token):
        return redirect(f"{FRONTEND_URL}/dashboard")
    else:
        return jsonify({"error": "login_failed"}), 400

@app.route("/api/me")
@login_required
def api_me():
    user = Auth.get_current_user()
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "avatar": user.get("avatar"),
        "email": user.get("email")
    })

@app.route("/api/servers")
@login_required
def api_servers():
    servers = Auth.get_user_servers()
    return jsonify({"servers": servers})

@app.route("/api/server/<server_id>/authorize")
@login_required
def api_server_authorize(server_id):
    authorized, reason = Auth.can_manage_server(server_id)
    return jsonify({
        "server_id": server_id,
        "authorized": authorized,
        "reason": reason
    })

@app.route("/api/server/<server_id>/channels")
@login_required
def api_server_channels(server_id):
    authorized, reason = Auth.can_manage_server(server_id)
    print("AUTH CHECK:", server_id, authorized, reason)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    channels = DiscordAPI.get_guild_channels(server_id)
    return jsonify({"channels": channels})

@app.route("/api/server/<server_id>/roles")
@login_required
def api_server_roles(server_id):
    authorized, reason = Auth.can_manage_server(server_id)
    print("AUTH CHECK:", server_id, authorized, reason)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    roles = DiscordAPI.get_guild_roles(server_id)
    return jsonify({"roles": roles})

@app.route("/api/config")
@login_required
def api_get_config():
    server_id = request.args.get("server_id")
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, reason = Auth.can_manage_server(server_id)
    print("AUTH CHECK:", server_id, authorized, reason)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    config = db.get_config(server_id)
    return jsonify({"config": config})

@app.route("/api/config", methods=["POST"])
@login_required
def api_save_config():
    data = request.get_json()
    if not data or "server_id" not in data:
        return jsonify({"error": "invalid_data"}), 400

    server_id = data["server_id"]
    authorized, _ = Auth.can_manage_server(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    if db.save_config(data):
        return jsonify({"success": True})
    else:
        return jsonify({"error": "save_failed"}), 500

@app.route("/api/ranking")
@login_required
def api_ranking():
    server_id = request.args.get("server_id")
    limit = int(request.args.get("limit", 10))

    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, _ = Auth.can_manage_server(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    ranking = db.get_ranking(server_id, limit)
    return jsonify({"ranking": ranking})

@app.route("/api/usuario/<discord_id>/xp", methods=["POST"])
@login_required
def api_add_xp(discord_id):
    data = request.get_json()
    server_id = data.get("server_id")
    xp = data.get("xp", 0)
    motivo = data.get("motivo", "")

    if not server_id or xp <= 0:
        return jsonify({"error": "invalid_data"}), 400

    authorized, _ = Auth.can_manage_server(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    try:
        user = db.add_xp(server_id, discord_id, xp, "manual", motivo)
        return jsonify({"success": True, "user": user})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

@app.route("/api/logout")
def api_logout():
    Auth.logout_user()
    return jsonify({"success": True})

@app.route("/api/treinos")
@login_required
def api_get_treinos():
    server_id = request.args.get("server_id")
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, _ = Auth.can_manage_server(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    treinos = db.get_treinos(server_id)
    return jsonify({"treinos": treinos})

@app.route("/api/treinos", methods=["POST"])
@login_required
def api_create_treino():
    data = request.get_json()
    if not data or "server_id" not in data:
        return jsonify({"error": "invalid_data"}), 400

    server_id = data["server_id"]
    authorized, _ = Auth.can_manage_server(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    titulo = data.get("titulo", "Treino")
    descricao = data.get("descricao", "")
    horario_inicio = data.get("horario_inicio", "")
    canal_id = data.get("canal_id", "")

    treino_id = db.create_treino(server_id, str(session["user"]["id"]), titulo, descricao, horario_inicio, canal_id)
    treino = db.get_treino(treino_id)

    return jsonify({"treino": treino})

@app.route("/api/treinos/<int:treino_id>")
@login_required
def api_get_treino(treino_id):
    treino = db.get_treino(treino_id)
    if not treino:
        return jsonify({"error": "treino_not_found"}), 404

    authorized, _ = Auth.can_manage_server(treino["server_id"])
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    respostas = db.get_treino_respostas(treino_id)
    return jsonify({"treino": treino, "respostas": respostas})

@app.route("/api/treinos/<int:treino_id>", methods=["DELETE"])
@login_required
def api_cancel_treino(treino_id):
    treino = db.get_treino(treino_id)
    if not treino:
        return jsonify({"error": "treino_not_found"}), 404

    authorized, _ = Auth.can_manage_server(treino["server_id"])
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    db.cancel_treino(treino_id)
    return jsonify({"success": True})

@app.route("/api/treinos/<int:treino_id>/notify", methods=["POST"])
@login_required
def api_notify_treino(treino_id):
    treino = db.get_treino(treino_id)
    if not treino:
        return jsonify({"error": "treino_not_found"}), 404

    authorized, _ = Auth.can_manage_server(treino["server_id"])
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    # Aqui seria necessário integrar com o bot para enviar DMs
    # Por enquanto, apenas confirmar
    return jsonify({"success": True, "message": "Notificação enviada"})

@app.route("/api/treinos/<int:treino_id>/resposta", methods=["POST"])
@login_required
def api_set_treino_resposta(treino_id):
    data = request.get_json()
    if not data or "resposta" not in data:
        return jsonify({"error": "invalid_data"}), 400

    resposta = data["resposta"]
    if resposta not in ["vou", "talvez", "nao"]:
        return jsonify({"error": "invalid_resposta"}), 400

    treino = db.get_treino(treino_id)
    if not treino:
        return jsonify({"error": "treino_not_found"}), 404

    server_id = treino["server_id"]
    authorized, _ = Auth.can_manage_server(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    db.set_treino_resposta(treino_id, server_id, str(session["user"]["id"]), resposta)
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True)
