#!/usr/bin/env python3
"""
Script principal para executar Flask + Discord Bot simultaneamente
"""

import os
import threading
import time
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

from app import app
from bot import run_bot
from config import FLASK_HOST, FLASK_PORT

def run_flask():
    """Executa o servidor Flask"""
    print("🚀 Iniciando servidor Flask...")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)

def run_discord_bot():
    """Executa o bot Discord"""
    print("🤖 Iniciando bot Discord...")
    time.sleep(2)  # Pequena pausa para Flask iniciar primeiro
    run_bot()

if __name__ == "__main__":
    # Thread para Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Executar bot na thread principal
    run_discord_bot()