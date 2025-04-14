import dash
from dash import html, dcc, callback, Input, Output, State, ctx, Patch
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import json
import pandas as pd
import numpy as np
import os
import calendar

from lib.utils import functions

dash.register_page(__name__, path='/budget')

CSP_GROUPS = ['Income', 'Fixed Costs', 'Investments', 'Savings', 'Guilt Free']
HEADER_ROWS = CSP_GROUPS + ['Total']

### UI COMPONENTS ###
year_dropdown = dcc.Dropdown(
    id='budget-year',
    clearable=False
)

remaining_to_budget = dbc.Button(
    id='assign-gf',
    size="md",
    color='bg-info',
    class_name='p-3',
    disabled=False,
)

grid = dag.AgGrid(
    id="my-grid",
    defaultColDef={"editable": True, "sortable": False},
    style={"width": "100%", "flex": "1"},
    getRowId="params.data.id",
    dashGridOptions={
        "domLayout": "normal",
        'undoRedoCellEditing': True,  # does not work with total row since update_total replaces rowData, even within a transaction
        'undoRedoCellEditingLimit': 12,
        'suppressMaintainUnsortedOrder': True,  # performance boost on editing 
    }
    # rowClassRules = {"bg-info": f"{header_rows}.includes(params.data.category)"},  # To use theme default
)

save_budget = dbc.Button(
    "Save Budget",
    id='save-budget',
    size="md",
    color="primary",
    class_name="me-md-2",
    disabled=False,
)

### LAYOUT ###
layout = html.Div([
    dbc.Container([
        dbc.Row(
            [
                dbc.Col(html.H1('Budget'), width=10),
                dbc.Col(year_dropdown, width=2)
            ], className="pt-3 pb-3"),
        html.Div(remaining_to_budget, className="d-grid pb-3"),
        html.Div(grid, style={"height": "65vh", "display": "flex", "flexDirection": "column"}),
        html.Div(
            [
                save_budget
            ],
            className="d-grid pt-3 pb-3 d-md-flex justify-content-md-end",
        )
    ])
])


### CALLBACKS ###
@callback(
    [Output("budget-year", "options"),
    Output("budget-year", "value")],
    Input("use-case", "value"),
    [State("budget-year", "value"),
     State('config-store', 'data')]
)
def initialize_budget_year(user, budget_year, config):
    config = json.loads(config)

    budget_dict = config["users"][user]['budget']

    budget_years = [year for year, months in budget_dict.items()]

    options=[
        {'label': str(year), 'value': str(year)}
        for year in budget_years
    ]

    if not budget_year:
        budget_year=str(budget_years[-1]) if budget_years else None

    return options, budget_year


@callback(
    [Output("my-grid", "rowData"),
     Output("my-grid", "columnDefs"),
     Output("my-grid", "getRowStyle")],
    Input("budget-year", "value"),
    State('config-store', 'data'),
    State('use-case', 'value')
)
def populate_budget(year, config, user):    
    year = int(year)
    config = json.loads(config)
    budget = functions.read_budget(config, user)
    
    budget = budget.loc[:, (year, 1):(year, 12)]

    budget.columns = [
        f"{calendar.month_abbr[int(month)]}" 
        for year, month in budget.columns
    ]

    csp_labels = pd.DataFrame.from_dict(config["users"][user]['csp_labels'],
                                        orient='index', 
                                        columns=['csp_label'])

    budget = pd.merge(budget, csp_labels, left_index=True,
                      right_index=True, how='left')

    new_rows = pd.DataFrame(np.nan, index=CSP_GROUPS, columns=budget.columns)
    budget = pd.concat([budget, new_rows])

    budget = functions.order_budget(budget, config, user)
    budget['id'] = budget.index
    month_columns = [col for col in budget.columns if col not in ["category", "csp_label", "id"]]

    # Convert DataFrame to rowData for Dash AG Grid
    row_data = budget.to_dict("records")
    
    columnDefs = [
    {"field": "category", "editable": False},
    ] + [
        {
            "field": col,
            "type": "number",
            "editable": {"function": f"!{HEADER_ROWS}.includes(params.data.category)"},
            "width": 100,
            "minWidth": 50,
            "resizable": True,
            "valueFormatter": {
                "function": "params.value && params.value !== 0 ? '$' + params.value.toLocaleString() : ''"
            },
            'valueParser': {'function': 'Number(params.newValue)'}
        }
        for col in month_columns
    ] + [
        {"field": "csp_label", "editable": False, "hide": True},
    ]
    
    getRowStyle = {
        "styleConditions": [
            {
                "condition": f"{HEADER_ROWS}.includes(params.data.category)",
                "style": {"backgroundColor": "#333", "color": "white", "font-weight": "bold"},
            },
        ]}

    return row_data, columnDefs, getRowStyle


@callback(
    Output("my-grid", "dashGridOptions"),
    [Input("my-grid", "cellValueChanged"),
    Input("my-grid", "rowData")],
)
def pin_total_row(cell_value_changed, row_data):
    df = pd.DataFrame(row_data).set_index("category")
    month_columns = [col for col in df.columns if col not in ["category", "csp_label", "id"]]

    for col in month_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Calculate total spending
    filt = df['csp_label'] != 'income'
    total_row = df.loc[filt, month_columns].sum().to_dict()

    grid_option_patch = Patch()
    grid_option_patch["pinnedBottomRowData"] = [{"category": "Total", **total_row}]
    return grid_option_patch


@callback(
    [Output("assign-gf", "children"),
     Output("assign-gf", "color"),
     Output("assign-gf", "disabled")],
    Input("my-grid", "cellValueChanged"),
    Input("my-grid", "rowData")
)
def update_total_button(cell_value_changed, row_data):
    df = pd.DataFrame(row_data).set_index('category')
    month_columns = [col for col in df.columns if col not in ["category", "csp_label", "id"]]

    filt = df['csp_label'] != 'income'
    total_spend = df.loc[filt, month_columns].sum().sum()

    total_income = df[df['csp_label'] == 'income'][month_columns].sum().sum()

    total_remaining = total_income - total_spend

    disabled=False
    if total_remaining > 0.12:
        text = f"${total_remaining:,.2f} Remaining! Click to assign to Guilt-Free spending."
        color = "primary"
    elif total_remaining < -0.12:
        text = f"${-total_remaining:,.2f} Over Budget! Click to subtract from Guilt-Free spending."
        color="danger"
    else:
        text = "Well Done! Every penny has a job."
        color="light"
        disabled=True

    return text, color, disabled


@callback(
    Output("my-grid", "rowData", allow_duplicate=True),
    Input("assign-gf", "n_clicks"),
    State("my-grid", "rowData"),
    prevent_initial_call=True
)
def assign_to_guilt_free(n, row_data):
    if n is None:
        return "Not clicked."
    else:
        df = pd.DataFrame(row_data).set_index("category")
        month_columns = [col for col in df.columns if col not in ["category", "csp_label", "id"]]
        
        filt = df['csp_label'] != 'income'
        total_spend = df.loc[filt, month_columns].sum().sum()
       
        total_income = df[df['csp_label'] == 'income'][month_columns].sum().sum()
       
        total_remaining = total_income - total_spend
        monthly_remaining = round(total_remaining / 12, 2)
        
        df.loc['guilt_free', month_columns] += monthly_remaining
        
        updated_row_data = df.reset_index().to_dict("records")

        return updated_row_data


@callback(
    Output('config-store', 'data', allow_duplicate=True),
    Input("save-budget", "n_clicks"),
    [State("my-grid", "rowData"),
     State('config-store', 'data'),
     State("budget-year", "value"),
     State("use-case", "value")],
    prevent_initial_call=True
)
def save_budget(n, row_data, config, budget_year, user):
    if n is None:
        raise PreventUpdate
    else:
        existing_config = json.loads(config)
        budget = pd.DataFrame(row_data).set_index('category')
        budget = budget.drop(columns=['csp_label', 'id'], index=CSP_GROUPS)

        month_mapping = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
        }

        budget = budget.reset_index().melt(
            id_vars="category", var_name="month", value_name="value"
        ).set_index('category')

        budget['month'] = budget['month'].map(month_mapping)
        budget['month'] = budget['month'].astype(int)

        # Group by year, month, and category
        grouped = budget.groupby(['month', budget.index])['value'].sum()

        # Convert to nested JSON-like dictionary
        config = {budget_year: {}}

        for (month, category), value in grouped.items():
            config[budget_year].setdefault(month, {})[category] = value   
        
        existing_config["users"][user]['budget'][budget_year] = config[budget_year]

        with open(os.path.join('data', 'config.json'), 'w') as f:
            json.dump(existing_config, f, indent=4)

        return json.dumps(existing_config)

