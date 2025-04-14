import dash
from dash import Dash, html, dcc
import dash_bootstrap_components as dbc

from navbar import navbar
from config import config

external_stylesheets = [dbc.themes.MINTY]

app = Dash(__name__, 
           use_pages=True, 
           external_stylesheets=external_stylesheets)
app.config.suppress_callback_exceptions = True

app.layout = html.Div([
    navbar,
    config,
    dash.page_container,
    dcc.Store(id='config-store', storage_type="session", data={"trigger": True}),
    dcc.Store(id='transaction-data-store'),
    dcc.Store(id='transaction-subset-store')
])

if __name__ == '__main__':
    app.run(debug=True)

