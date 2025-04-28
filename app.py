from flask import Flask, request, session, render_template, redirect, url_for
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth
import os
import dash
from dash import Dash, html, dcc
import dash_bootstrap_components as dbc
from firebase_admin import firestore

from navbar import navbar
from config import config

dotenv_path = os.path.join("secrets", "env-file")
load_dotenv(dotenv_path=dotenv_path)

# Init Flask
server = Flask(__name__)
server.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret")

external_stylesheets = [dbc.themes.MINTY]

app = Dash(__name__, 
           server=server,
           use_pages=True,
           suppress_callback_exceptions=True,
           external_stylesheets=external_stylesheets,
           url_base_pathname="/dash/")

def protected_layout():
    if "user_id" not in session:
        return html.Div("Unauthorized. Please log in at /")
    
    return html.Div([
        navbar,
        config,
        dash.page_container,
        dcc.Store(id='config-store', storage_type="session", data={"trigger": True}),
        dcc.Store(id='transaction-data-store'),
        dcc.Store(id='transaction-subset-store'),
        dcc.Store(id='monarch-session-store', storage_type="session")
    ])

app.layout = protected_layout

# Routes
@server.route("/")
def index():
    return render_template("index.html",
        firebase_api_key=os.environ["FIREBASE_API_KEY"],
        firebase_auth_domain=os.environ["FIREBASE_AUTH_DOMAIN"],
        firebase_project_id=os.environ["FIREBASE_PROJECT_ID"],
        firebase_app_id=os.environ["FIREBASE_APP_ID"]
    )

@server.route("/login", methods=["POST"])
def login():
    id_token = request.json.get("idToken")
    decoded_token = auth.verify_id_token(id_token)
    session["user_id"] = decoded_token["uid"]
    session["email"] = decoded_token.get("email")
    return "OK", 200

@server.route("/dash/")
def redirect_to_dash():
    if "user_id" not in session:
        return redirect(url_for("index"))
    return app.index()  # renders Dash app layout

@server.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# if __name__ == '__main__':
#     app.run(host="0.0.0.0", port=8080, debug=False)

