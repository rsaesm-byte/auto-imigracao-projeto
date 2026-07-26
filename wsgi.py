"""Ponto de entrada do app web. Rode com: python wsgi.py
(ou `flask --app wsgi run` / `waitress-serve --call wsgi:create_app`)."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
