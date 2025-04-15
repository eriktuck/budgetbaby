import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, Input, Output, State
import json
from monarchmoney import MonarchMoney, RequireMFAException
import asyncio
import pandas as pd
from datetime import datetime as dt
from io import StringIO
import uuid
import pickle
import base64

from lib.utils import functions

CONFIG_FILE = "data/config.json"

def pickle_and_encode(obj):
    pickled = pickle.dumps(obj)
    encoded = base64.b64encode(pickled).decode('utf-8')  # convert bytes to UTF-8 string
    return encoded

def decode_and_unpickle(encoded_str):
    decoded = base64.b64decode(encoded_str)
    obj = pickle.loads(decoded)
    return obj

# Populate use_case_dropdown options
with open(CONFIG_FILE, 'r') as file:
    CONFIG = json.load(file)

user_keys = list(CONFIG["users"].keys())
use_case_options = [
    {'label': user.title(), 'value': user}
    for user in user_keys
    ]
use_case_value = user_keys[0]

### UI COMPONENTS ###
use_case_dropdown = dcc.Dropdown(
    id='use-case',
    options = use_case_options,
    value=use_case_value,
    clearable=False
)

login_button = dbc.Button("Fetch", id="open-modal-button", color="dark", outline=True)

login_form = html.Div(
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Label("Email", html_for="username-input"),
                        dbc.Input(
                            type="email",
                            id="username-input",
                            placeholder="Enter Monarch email",
                        ),
                    ],
                    width=6,
                ),
                dbc.Col(
                    [
                        dbc.Label("Password", html_for="password-input"),
                        dbc.Input(
                            type="password",
                            id="password-input",
                            placeholder="Enter Monarch password",
                        ),
                    ],
                    width=6,
                ),
            ],
            className="g-3",
        ),
        html.Div(id="login-status", style={"marginTop": "10px", "color": "bg-secondary"}),
    ]
)

login_modal = dbc.Modal(
    [
        dbc.ModalHeader("Login to Monarch Money"),
        dbc.ModalBody(
            login_form
        ),
        dbc.ModalFooter(
            [
                dbc.Button("Login", id="login-button", color="primary"),
                dbc.Button("Close", id="close-login-modal-button", color="secondary"),
            ]
        ),
    ],
    id="login-modal",
    is_open=False,
)

transaction_date_picker = dcc.DatePickerRange(
    id='transaction-date-picker',
    start_date=dt.today().strftime('%Y-%m-01'),
    end_date=dt.today().strftime('%Y-%m-%d'),
    max_date_allowed=dt.today().strftime('%Y-%m-%d'),
    number_of_months_shown=2,
    persistence=True,
    updatemode='bothdates',
    style={'borderWidth': 0}  
    )

transaction_form = html.Div(
    [
        dbc.Row(
            [
                dbc.Col(
                    transaction_date_picker, 
                    width="auto",  # Content width
                    className="mx-auto"  # Bootstrap class for centering
                )
            ],
            justify="center",  # Bootstrap utility to center the row contents
        ),
    ]
)

transaction_modal = dbc.Modal(
    [
        dbc.ModalHeader("Fetch Updated Transactions"),
        dbc.ModalBody(
            [html.P("Select a range of dates to fetch updated transactions."),
            transaction_form]
        ),
        dbc.ModalFooter(
            [
                dbc.Button("Fetch", id="fetch-button", color="primary"),
                dbc.Button("Close", id="close-transaction-modal-button", color="secondary"),
            ]
        ),
    ],
    id="transaction-modal",
    is_open=False,
)

### LAYOUT ###
config = html.Div(
    [
        dbc.Container(
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            "Please select a use case",
                            className="text-end",
                        ),
                        width=8,
                    ),
                    dbc.Col(use_case_dropdown, width=3),
                    dbc.Col(
                        dbc.Button("Fetch", id="open-modal-button", color="dark", outline=True),
                        className="text-end",
                        width=1,
                    ),
                ],
                className="align-items-center",
            ),
        ),
        login_modal,
        transaction_modal,
    ],
    className="p-2 bg-light",
)


@callback(
    Output('config-store', 'data'),
    Input('navbar', 'id')  # Dummy input to fire on load
)
def store_config(dummy):
    """
    Store config file for selected user in browser memory.

    Parameters
    ----------
    dummy: str
        dummy input to fire callback on page load 

    Returns
    -------
    str
        JSON-serialized config file
    """
    return json.dumps(CONFIG)


@callback(
    [Output("login-modal", "is_open"), 
     Output("transaction-modal", "is_open"),
     Output("login-status", "children"),
     Output('transaction-data-store', 'data', allow_duplicate=True),
     Output('monarch-session-store', 'data')],
    [Input("open-modal-button", "n_clicks"),
     Input("close-login-modal-button", "n_clicks"),
     Input("close-transaction-modal-button", "n_clicks"),
     Input("login-button", "n_clicks"),
     Input("fetch-button", "n_clicks")],
    [State("username-input", "value"), 
     State("password-input", "value"),
     State("date-picker-range", "start_date"),
     State("date-picker-range", "end_date"),
     State('transaction-data-store', 'data'),
     State('monarch-session-store', 'data')],
    prevent_initial_call=True,
)
def manage_and_handle_modals(
    open_clicks, close_login_clicks, close_transaction_clicks, 
    login_clicks, fetch_clicks, username, password, start_date, end_date, 
    stored_transaction_data, session_data
):
    """
    Manages modal states and functionality.
    
    Launches modal on open-modal-button click. If a user session is 
    found in session storage, the transactions modal is shown. 
    If not, the login modal is shown. Successful login
    triggers the transactions modal.

    User selects a date range and fetches transactions. Existing
    transactions are updated by truncating existing transactions in the
    date range selected and appending fetched transactions. Raw 
    transaction data are stored in transaction-data-store.
    """
    ctx = dash.callback_context

    if not ctx.triggered:
        return False, False, "", stored_transaction_data, session_data

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Close the modal
    if triggered_id == "close-login-modal-button":
        return False, False, "", stored_transaction_data, session_data
    if triggered_id == "close-transaction-modal-button":
        return False, False, "", stored_transaction_data, session_data
    
    # Check for existing session and open appropriate modal
    if triggered_id == "open-modal-button":
        if session_data:
            mm = decode_and_unpickle(session_data)
            try:
                # Validate session is still active
                asyncio.run(mm.get_accounts())
                return False, True, "", stored_transaction_data, session_data
            except:
                # Session expired, need to login again
                return True, False, "", stored_transaction_data, None
        else:
            # No session exists, open the login modal
            return True, False, "", stored_transaction_data, None

    # No saved session: login with username and password from login modal
    if triggered_id == "login-button":
        if not username or not password:
            return True, False, "Please enter both username and password.", stored_transaction_data, None
        
        async def login_to_monarch(email, password):
            mm = MonarchMoney()
            mm._headers['Device-UUID'] = '98d6a448-4798-437f-9927-950f643da374'
            
            try:
                await mm.login(email=email, password=password, 
                               use_saved_session=False, save_session=False)
                # Pickle and store session data
                print("LOGIN SUCCESSFUL")
                return False, True, "", stored_transaction_data, pickle_and_encode(mm)
            except Exception as e:
                print(f"Login failed: {str(e)}")
                return True, False, f"Login failed: {str(e)}", stored_transaction_data, None

        return asyncio.run(login_to_monarch(username, password))
    
    # Handle the fetch button
    if triggered_id == "fetch-button":
        async def fetch_transactions(mm, start_date, end_date):
            # Await the get_transactions call
            transactions = await mm.get_transactions(start_date=start_date, end_date=end_date, limit=None)
            
            # Convert to dataframe
            transactions = pd.DataFrame(transactions['allTransactions']['results'])
            transactions['date'] = pd.to_datetime(transactions['date'])

            # Return results
            return transactions

        try:
            if not session_data:
                raise Exception("No valid session found")

            # Fetch transactions for selected dates
            mm = decode_and_unpickle(session_data)      
            transactions = asyncio.run(fetch_transactions(mm, start_date, end_date))

            # Update existing transactions with new transactions
            start_date = dt.fromisoformat(start_date)
            end_date = dt.fromisoformat(end_date)
            existing_transactions = pd.read_json(StringIO(stored_transaction_data), orient='split')
            
            # Update transactions and store in transaction-data-store
            transactions = functions.update_transactions(existing_transactions, transactions, start_date, end_date, save=True)

            return False, False, "", transactions.to_json(date_format='iso', orient='split'), session_data
        
        except Exception as e:
            print(f"Failed to fetch transactions: {str(e)}")
            return False, True, "", stored_transaction_data, session_data

    # # Default: Both modals closed
    # return False, False, "", stored_transaction_data, session_data
