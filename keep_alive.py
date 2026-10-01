try:
    from flask import Flask
    from threading import Thread

    app = Flask(__name__)

    @app.route('/')
    def home():
        return "Bot is online!"

    @app.route('/health')
    def health():
        return "OK", 200

    def run():
        # Render / Railway / Docker zetten PORT automatisch, lokaal default 8080
        import os
        port = int(os.environ.get("PORT", 8080))
        print(f"Keep-alive webserver op 0.0.0.0:{port}", flush=True)
        app.run(host="0.0.0.0", port=port, use_reloader=False)

    def keep_alive():
        t = Thread(target=run, daemon=True)
        t.start()
except ImportError:
    # Flask niet geinstalleerd (lokaal) -> gewoon niks doen, bot werkt toch
    def keep_alive():
        pass
