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


def require_server_admin(server_id):
    user = Auth.get_current_user()
    if not user:
        authorized, reason = False, "not_logged_in"
    else:
        authorized, reason = Auth.can_manage_server(server_id)

    print("AUTH DEBUG", {
        "server_id": server_id,
        "user_id": user.get("id") if user else None,
        "admin_guild_ids": session.get("admin_guild_ids"),
        "authorized": authorized,
        "reason": reason
    })

    return authorized, reason

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
    authorized, reason = require_server_admin(server_id)
    return jsonify({
        "server_id": server_id,
        "authorized": authorized,
        "reason": reason
    })

@app.route("/api/server/<server_id>/channels")
@login_required
def api_server_channels(server_id):
    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    channels = DiscordAPI.get_guild_channels(server_id)
    return jsonify({"channels": channels})

@app.route("/api/server/<server_id>/roles")
@login_required
def api_server_roles(server_id):
    authorized, reason = require_server_admin(server_id)
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

    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    config = db.get_config(server_id)
    return jsonify({"config": config})

@app.route("/api/config/canais")
@login_required
def api_get_config_canais():
    server_id = request.args.get("server_id")
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    db.ensure_default_canais(server_id)
    canais = db.get_config_canais(server_id)
    return jsonify({"success": True, "data": canais})

@app.route("/api/config/canais", methods=["POST"])
@login_required
def api_create_config_canal():
    data = request.get_json()
    if not data or "server_id" not in data or "nome" not in data or "tipo" not in data:
        return jsonify({"error": "invalid_data", "message": "server_id, nome e tipo são obrigatórios"}), 400

    server_id = data["server_id"]
    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    if db.get_config_canal_by_tipo(server_id, data["tipo"]):
        return jsonify({"error": "tipo_exists", "message": "Tipo já existe para este servidor"}), 400

    canal_id = data.get("canal_id")
    obrigatorio = int(data.get("obrigatorio", 0))
    ordem = int(data.get("ordem", 0))
    new_id = db.create_config_canal(server_id, data["nome"], data["tipo"], canal_id, obrigatorio, ordem)

    return jsonify({"success": True, "id": new_id, "message": "Canal criado com sucesso"})

@app.route("/api/config/canais/<int:canal_id>", methods=["PUT"])
@login_required
def api_update_config_canal(canal_id):
    data = request.get_json()
    if not data or "server_id" not in data:
        return jsonify({"error": "invalid_data", "message": "server_id é obrigatório"}), 400

    server_id = data["server_id"]
    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    success = db.update_config_canal(canal_id, server_id, data)
    if not success:
        return jsonify({"error": "not_found", "message": "Canal não encontrado"}), 404

    return jsonify({"success": True})

@app.route("/api/config/canais/<int:canal_id>", methods=["DELETE"])
@login_required
def api_delete_config_canal(canal_id):
    server_id = request.args.get("server_id")
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    result = db.delete_config_canal(canal_id, server_id)
    if result is None:
        return jsonify({"error": "not_found", "message": "Canal não encontrado"}), 404
    if not result:
        return jsonify({"error": "cannot_delete", "message": "Canal obrigatório não pode ser excluído"}), 400

    return jsonify({"success": True})

@app.route("/api/patentes")
@login_required
def api_get_patentes():
    server_id = request.args.get("server_id")
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    # Garantir que patentes padrão existem (com cargos no Discord)
    result = db.ensure_default_patentes(server_id)
    if not result.get("success"):
        return jsonify({
            "error": "failed_to_initialize_patentes",
            "message": result.get("error", "Erro desconhecido")
        }), 500
    
    patentes = db.get_patentes(server_id)
    return jsonify({"success": True, "data": patentes})

@app.route("/api/patentes", methods=["POST"])
@login_required
def api_create_patente():
    data = request.get_json()
    if not data or "server_id" not in data or "nome" not in data:
        return jsonify({"error": "invalid_data", "message": "server_id e nome são obrigatórios"}), 400

    server_id = data["server_id"]
    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    role_id = data.get("role_id")
    
    # Se não forneceu role_id, criar cargo no Discord
    if not role_id:
        role_result = DiscordAPI.ensure_discord_role(server_id, data["nome"])
        if "error" in role_result:
            return jsonify({
                "error": "failed_to_create_discord_role",
                "message": role_result.get("message", "Erro desconhecido")
            }), 500
        role_id = role_result.get("id")
    
    xp_necessario = int(data.get("xp_necessario", 0))
    ordem = int(data.get("ordem", 0))
    pode_excluir = int(data.get("pode_excluir", 1))
    new_id = db.create_patente(server_id, data["nome"], role_id, xp_necessario, ordem, pode_excluir)

    return jsonify({"success": True, "id": new_id, "message": "Patente criada com sucesso"})

@app.route("/api/patentes/<int:patente_id>", methods=["PUT"])
@login_required
def api_update_patente(patente_id):
    data = request.get_json()
    if not data or "server_id" not in data:
        return jsonify({"error": "invalid_data", "message": "server_id é obrigatório"}), 400

    server_id = data["server_id"]
    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    success = db.update_patente(patente_id, server_id, data)
    if not success:
        return jsonify({"error": "not_found", "message": "Patente não encontrada"}), 404

    return jsonify({"success": True})

@app.route("/api/patentes/<int:patente_id>", methods=["DELETE"])
@login_required
def api_delete_patente(patente_id):
    server_id = request.args.get("server_id")
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    result = db.delete_patente(patente_id, server_id)
    if result is None:
        return jsonify({"error": "not_found", "message": "Patente não encontrada"}), 404
    if not result:
        return jsonify({"error": "cannot_delete", "message": "Patente fixa não pode ser excluída"}), 400

    return jsonify({"success": True})

@app.route("/api/config", methods=["POST"])
@login_required
def api_save_config():
    data = request.get_json()
    if not data or "server_id" not in data:
        return jsonify({"error": "invalid_data"}), 400

    server_id = data["server_id"]
    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

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

    authorized, _ = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    ranking = db.get_ranking(server_id, limit)
    return jsonify({"ranking": ranking})

@app.route("/api/stats")
@login_required
def api_stats():
    user = Auth.get_current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    server_id = request.args.get("server_id")
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    authorized, _ = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    stats = db.get_stats(server_id)
    return jsonify(stats)

@app.route("/api/usuario/<discord_id>/xp", methods=["POST"])
@login_required
def api_add_xp(discord_id):
    data = request.get_json()
    server_id = data.get("server_id")
    xp = data.get("xp", 0)
    motivo = data.get("motivo", "")

    if not server_id or xp <= 0:
        return jsonify({"error": "invalid_data"}), 400

    authorized, _ = require_server_admin(server_id)
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

    authorized, reason = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized", "reason": reason}), 403

    treinos = db.get_treinos(server_id)
    return jsonify({"treinos": treinos})

@app.route("/api/treinos", methods=["POST"])
@login_required
def api_create_treino():
    data = request.get_json()
    if not data or "server_id" not in data:
        return jsonify({"error": "invalid_data"}), 400

    server_id = data["server_id"]
    authorized, _ = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    titulo = data.get("titulo", "Treino")
    descricao = data.get("descricao", "")
    horario_inicio = data.get("horario_inicio", "")
    canal_id = data.get("canal_id", "")
    pontos = int(data.get("pontos", 2)) if data.get("pontos") is not None else 2
    target_role_id = data.get("target_role_id", "")

    treino_id = db.create_treino(server_id, str(session["user"]["id"]), titulo, descricao, horario_inicio, canal_id, pontos, target_role_id)
    treino = db.get_treino(treino_id)

    return jsonify({"treino": treino})

@app.route("/api/treinos/<int:treino_id>")
@login_required
def api_get_treino(treino_id):
    treino = db.get_treino(treino_id)
    if not treino:
        return jsonify({"error": "treino_not_found"}), 404

    authorized, _ = require_server_admin(treino["server_id"])
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

    authorized, _ = require_server_admin(treino["server_id"])
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

    authorized, _ = require_server_admin(treino["server_id"])
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
    authorized, _ = require_server_admin(server_id)
    if not authorized:
        return jsonify({"error": "unauthorized"}), 403

    db.set_treino_resposta(treino_id, server_id, str(session["user"]["id"]), resposta)
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True)
