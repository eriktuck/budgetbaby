from datetime import datetime as dt
import json
import numpy as np
import os
import pandas as pd
import plotly.graph_objects as go
import glob

FILE_NAME = 'raw-transactions.pkl'

def read_transactions(file_name=FILE_NAME):
    """reads transactions from file"""
    transactions = pd.read_pickle(os.path.join('data', file_name))

    return transactions


def update_transactions(existing_transactions, new_transactions, 
                        start_date, end_date, save=False):
    filt = (
        (existing_transactions['date'] >= start_date) & 
        (existing_transactions['date'] <= end_date)
    )
    filtered_transactons = existing_transactions.loc[~filt]
    combined_transactions = pd.concat([filtered_transactons, new_transactions])
    combined_transactions = combined_transactions.sort_values('date', ascending=False)

    if save:
        combined_transactions.to_pickle(f"./data/{FILE_NAME}")

    return combined_transactions


def process_transactions(df, config, user):
    # Get config settings
    user_config = config["users"][user]
    category_names = config['cat_names']
    csp_from_group = user_config['csp_from_group']
    csp_from_category = user_config['csp_from_category']
    csp_labels = user_config['csp_labels']
    account_owner = config['account_owner']

    # Extract data from dictionary columns
    df['category_name'] = df['category'].apply(lambda x: x['name'])
    df['category_group'] = df['category_name'].map(category_names)
    df['account_name'] = df['account'].apply(lambda x: x['displayName'])

    # Drop categories
    drop_cats = user_config['drop_cats']
    filt = (df['category_name'].isin(drop_cats)) | (df['hideFromReports'] == True)
    df = df.loc[~filt]

    # Remap categories for CSP and set label (e.g., income, fixed)
    df = df.assign(
        csp_from_group=df['category_group'].map(csp_from_group),
        csp_from_category=df['category_name'].map(csp_from_category),
        csp=lambda x: x['csp_from_group'].fillna(x['csp_from_category']).fillna('guilt_free'),
        csp_label=lambda x: x['csp'].map(csp_labels),
        account_owner=df['account_name'].replace(account_owner)
    )

    # Subset transactions by account_owner 
    filt = df['account_owner'] == user #TODO
    df = df.loc[filt, :]

    return df


def read_budget(config, user):
    budget_dict = config['users'][user]['budget']

    budget = pd.DataFrame({
        (int(year), int(month)): values 
        for year, months in budget_dict.items() 
        for month, values in months.items()
    })

    return budget


def calc_proportions(df):
    # calculate overage
    filt = df['amount'] > df['budget']
    df.loc[filt, 'overage'] = (
        df.loc[filt, 'amount'] - df.loc[filt, 'budget']
    )
    df['overage'] = df['overage'].fillna(0)

    # calculate covered amount
    df['covered'] = df['amount'] - df['overage']

    # calculate remaining
    df['remaining'] = df['budget'] - df['amount']

    # calculate proportion and fill na with 100%
    df['proportion'] = df['covered'] / df['budget']
    df['proportion'] = df['proportion'].fillna(1)

    return df


def build_budget_report(transactions, budget, start_date, end_date, config, user):
    # Subset transactions by date
    filt = (
        (transactions['date'] >= start_date) & 
        (transactions['date'] <= end_date)
    )
    transactions = transactions.loc[filt, :]

    # Sum spending for period
    spend = transactions.groupby(['csp', 'csp_label'])['amount'].sum().abs()
    spend = spend.reset_index()

    # Sum budget for period
    period_budget = budget.loc[:, (start_date.year, start_date.month):(end_date.year, end_date.month)]
    total_budget = period_budget.sum(axis=1)
    total_budget = total_budget[total_budget>0]
    total_budget.name = 'budget'

    # Merge spending with budget
    df = pd.merge(spend, total_budget, left_on='csp', right_index=True, how='outer')

    # NA values are actually 0
    df = df.fillna(0)

    # Calculate total spending
    sum_row = df.loc[df['csp_label'] != 'income'].sum(numeric_only=True)

    # Add the label for the new row (e.g., 'Total Spending') in a non-numeric column
    sum_row['csp'] = 'Total Spending'
    sum_row['csp_label'] = 'spending'

    # Append the sum row to the original DataFrame
    df = pd.concat([df, pd.DataFrame([sum_row])], ignore_index=True)

    # Calculate total income
    sum_row = df.loc[df['csp_label'] == 'income'].sum(numeric_only=True)

    # Add the label for the new row (e.g., 'Total Spending') in a non-numeric column
    sum_row['csp'] = 'Total Income'
    sum_row['csp_label'] = 'income'

    # Append the sum row to the original DataFrame
    df = pd.concat([df, pd.DataFrame([sum_row])], ignore_index=True)
    
    # Calculate proportions by category
    df = calc_proportions(df)

    # Add CSP categories and sort to order
    df = df.set_index('csp')
    csp_groups = ['Income', 'Fixed Costs', 'Investments', 'Savings', 'Guilt Free']
    new_rows = pd.DataFrame(np.nan, index=csp_groups, columns=df.columns)
    df = pd.concat([df, new_rows])

    # Get category order
    cat_order = pd.DataFrame(config['users'][user]['cat_order'])
    cat_order = cat_order.reset_index()
    cat_order.columns = ['order', 'category']

    # Merge with category orders
    df_ordered = pd.merge(df, cat_order, left_index=True, 
                            right_on='category', how='left')

    # Sort by category order
    df_ordered.sort_values('order', inplace=True, ascending=False)

    # # Total spending by group
    # groups = df.groupby('csp_label').sum(numeric_only=True).reset_index()
    # groups = groups.set_index('csp_label').sort_index(ascending=False)

    # # Calculate proportions by group
    # groups = calc_proportions(groups)

    return df_ordered


def plot_report(budget_report, start_date, end_date):
    green = '#78C2AD'
    yellow = '#FFCE67'
    red = '#F3969A'
    body = '#888'
    heading = '#5a5a5a'

    x = abs(budget_report['proportion'])
    y = budget_report['category']
    text = budget_report['amount'] / budget_report['budget'] 
    hover_text = budget_report['amount']

    def stoplight_system(row):
        prop = (row['amount'] / row['budget']) if row['budget'] else row['amount']
        if row['csp_label'] == 'income':
            return green if prop > 0.99 else yellow if prop >= 0.8 else red
        else:
            return red if prop > 1.01 else yellow if prop >= 0.8 else green

    marker_color = budget_report.apply(stoplight_system, axis=1)
    
    bar_width = 0.8
    
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=x, 
        y=y,
        name='Budget',
        orientation='h',
        marker_color=marker_color,
        hovertext=hover_text,
        # hoverinfo='x', 
        hovertemplate='Actual: $%{hovertext:,.2f} <extra></extra>',
        hoverlabel=dict(bgcolor='#888', bordercolor='#888', 
                        font=dict(color='white')),
        text=text, 
        textposition='auto',
        texttemplate='%{text:.0%}',
        textfont=dict(size=10, color='white'),
        insidetextanchor='start',
        width=bar_width,
        showlegend=False,
        legendgroup='Fixed Costs'
    ))

    fig.update_layout(
        # title=go.layout.Title(text="Planned vs Actual", 
        #                       font=dict(color=heading)),
        xaxis=dict(showgrid=False, 
                visible=False,
                range=[0,1.45]),
        paper_bgcolor='white',
        plot_bgcolor='white',
        barmode='relative', # in case negative values
        annotations=[
            go.layout.Annotation(
                x=1.31, y=len(y)+.05,
                xanchor='right',
                text='<b>Budget<b>',
                font_color=heading,
                showarrow=False
            ),
            go.layout.Annotation(
                x=1.36, y=len(y)+.05,
                xanchor='left',
                text='<b>Remaining<b>',
                font_color=heading,
                showarrow=False
            )
        ],
        height=max(45, len(budget_report) * 30),
        margin=dict(l=180, t=10, b=10, pad=10),
        yaxis=dict(
            visible=True,
            scaleanchor="x",  # Ensures proportional scaling
        ),
    )
    
    # Add budget annotation
    for idx, budget in enumerate(budget_report['budget']):
        if budget > 0:
            fig.add_annotation(
                x=1.31, y=idx,
                xanchor='right',
                text=f'$ {budget:,.0f}',
                font_color=body,
                showarrow=False
            )
    
    # Add remaining annotation
    for idx, (remain, label) in enumerate(zip(budget_report['remaining'],budget_report['csp_label'])):
        if remain >= 0:
            fig.add_annotation(
                x=1.36, y=idx,
                xanchor='left',
                text=f'$ {remain:,.0f}',
                font_color=body,
                showarrow=False
            )
        elif remain < 0:
            fig.add_annotation(
                x=1.36, y=idx,
                xanchor='left',
                text=f'<b>+ ${abs(remain):,.0f}!</b>' if label == 'income' else f'<b>$ ({abs(remain):,.0f})</b>',
                font_color = green if label == 'income' else red,
                showarrow=False
            )
    
    
    # Add line for each Group
    for group in ['Income', 'Guilt Free', 'Fixed Costs', 'Investments', 
                  'Savings']:
        fig.add_shape(
            type='line',
            x0=0,
            y0=y.tolist().index(group),
            x1=1.45,
            y1=y.tolist().index(group),
            line=dict(
                width=.5,
                color='grey'
            ),
            layer='below',
            opacity=.6
        )

    # Add line for today
    start_to_today = (dt.today() - start_date).days
    total_days = (end_date - start_date).days
    progress = start_to_today/total_days
    
    if progress > 0 and progress < 0.1:
        fig.add_shape(
            type='line',
            x0=progress,
            x1=progress,
            y0=0-bar_width/2,
            y1=len(y)-bar_width/2,
            line=dict(color=body, dash='dot')
        )
    
        fig.add_annotation(
                    x=progress, y=len(y),
                    xanchor='left',
                    text='Today',
                    font_color = body,
                    showarrow=False
                )
        
    elif progress >= 0.1 and progress <=1:
        fig.add_shape(
            type='line',
            x0=progress,
            x1=progress,
            y0=0-bar_width/2,
            y1=len(y)-bar_width/2,
            line=dict(color=body, dash='dot')
        )
        
        fig.add_annotation(
                    x=progress, y=len(y),
                    xanchor='right',
                    text='Today',
                    font_color = body,
                    showarrow=False
                )
    
    else:
        pass

    # Update y axis labels
    fig.update_yaxes(
        tickfont=dict(color=body),
        tickvals=np.arange(len(y)),
        ticktext=[f'<b>{label}</b>' if label in [
            'Total Income', 'Total Spending', 'Income', 'Guilt Free', 
            'Fixed Costs', 'Investments', 'Savings'] 
                    else label for label in y]
        )
    
    return fig

# def plot_report(budget_report, start_date, end_date):
#     green = '#78C2AD'
#     yellow = '#FFCE67'
#     red = '#F3969A'
#     body = '#888'
#     heading = '#5a5a5a'

#     x = abs(budget_report['Proportion'])
#     y = budget_report['Category']
#     text = budget_report['Spending'] / budget_report['Budget'] 
#     hover_text = budget_report['Spending']
    
#     bar_width=.8
    
#     fig = go.Figure(
        
#         data=[go.Bar(x=x, y=y,
#                     name='Budget',
#                     orientation='h',
#                     marker_color=(
#                         [red if a >= 1 
#                          else (yellow if a >=.8 and a < 1
#                                else green) for a in x]
#                     ),
#                     hovertext=hover_text,
#                     # hoverinfo='x', 
#                     hovertemplate='Actual: $%{hovertext:,.2f} <extra></extra>',
#                     hoverlabel=dict(bgcolor='#888', bordercolor='#888', 
#                                     font=dict(color='white')),
#                     text=text, 
#                     textposition='auto',
#                     texttemplate='%{text:.0%}',
#                     textfont=dict(size=10, color='white'),
#                     insidetextanchor='start',
#                     width=bar_width,
#                     showlegend=False,
#                     legendgroup='Fixed Costs'
#                     )],
        
#         layout=go.Layout(
#             title=go.layout.Title(text="Budgeted Spending", 
#                                   font=dict(color=heading)),
#             xaxis=dict(showgrid=False, 
#                     visible=False,
#                     range=[0,1.45]),
#             paper_bgcolor='white',
#             plot_bgcolor='white',
#             barmode='relative', # in case negative values
#             # Add 'Discretionary' tag above discretionary items
#             annotations=[
#                 go.layout.Annotation(
#                     x=1.31, y=len(y)+.05,
#                     xanchor='right',
#                     text='<b>Budget<b>',
#                     font_color=heading,
#                     showarrow=False
#                 ),
#                 go.layout.Annotation(
#                     x=1.36, y=len(y)+.05,
#                     xanchor='left',
#                     text='<b>Remaining<b>',
#                     font_color=heading,
#                     showarrow=False
#                 )
#             ],
#             height=185 + max(45, len(budget_report) * 30),
#             margin=dict(l=180, pad=10) # TODO allow annotations with margin
#         )
#     )
    
#     # Add budget annotation
#     for idx, budget in enumerate(budget_report['Budget']):
#         if budget > 0:
#             fig.add_annotation(
#                 x=1.31, y=idx,
#                 xanchor='right',
#                 text=f'$ {budget:,.0f}',
#                 font_color=body,
#                 showarrow=False
#             )
    
#     # Add remaining annotation
#     for idx, remain in enumerate(budget_report['Remaining']):
#         if remain >= 0:
#             fig.add_annotation(
#                 x=1.36, y=idx,
#                 xanchor='left',
#                 text=f'$ {remain:,.0f}',
#                 font_color=body,
#                 showarrow=False
#             )
#         elif remain < 0:
#             fig.add_annotation(
#                 x=1.36, y=idx,
#                 xanchor='left',
#                 text=f'<b>$ ({abs(remain):,.0f})</b>',
#                 font_color = red,
#                 showarrow=False
#             )
            
#     # Add line for each Group
#     for group in ['Income', 'Guilt Free', 'Fixed Costs', 'Investments', 'Savings']:
#         fig.add_shape(
#             type='line',
#             x0=0,
#             y0=y.tolist().index(group),
#             x1=1.45,
#             y1=y.tolist().index(group),
#             line=dict(
#                 width=.5,
#                 color='grey'
#             ),
#             layer='below',
#             opacity=.6
#         )
    
#     # # Add empty box for unbudgeted and color red
#     # fig.add_shape(
#     #     type="rect",
#     #     x0=0,
#     #     y0=(len(y)-2)-(bar_width/2),
#     #     x1=1,
#     #     y1=(len(y)-2)+(bar_width/2),
#     #     line=dict(
#     #         width=.5,
#     #         color=red
#     #     ),
#     #     fillcolor=red
#     # )
    
#     # Add line for today
#     start_to_today = (dt.today() - start_date).days
#     total_days = (end_date - start_date).days
#     progress = start_to_today/total_days
    
#     if progress > 0 and progress < 0.1:
#         fig.add_shape(
#             type='line',
#             x0=progress,
#             x1=progress,
#             y0=0-bar_width/2,
#             y1=len(y)-bar_width/2,
#             line=dict(color=body, dash='dot')
#         )
    
#         fig.add_annotation(
#                     x=progress, y=len(y),
#                     xanchor='left',
#                     text='Today',
#                     font_color = body,
#                     showarrow=False
#                 )
        
#     elif progress >= 0.1 and progress <=1:
#         fig.add_shape(
#             type='line',
#             x0=progress,
#             x1=progress,
#             y0=0-bar_width/2,
#             y1=len(y)-bar_width/2,
#             line=dict(color=body, dash='dot')
#         )
        
#         fig.add_annotation(
#                     x=progress, y=len(y),
#                     xanchor='right',
#                     text='Today',
#                     font_color = body,
#                     showarrow=False
#                 )
    
#     else:
#         pass
    
#     # Update y axis labels
#     fig.update_yaxes(
#         tickfont=dict(color=body),
#         tickvals=np.arange(len(y)),
#         ticktext=[f'<b>{label}</b>' if label in ['Income', 'Guilt Free', 'Fixed Costs', 'Investments', 'Savings'] 
#                     else label for label in y]
#         )
    
#     return fig


def format_table(transactions):
    '''prettifies transactions table for display'''
    transactions_pretty = transactions.copy()
    # format Amount
    transactions_pretty['amount'] = (
        transactions_pretty['amount'].map('${:,.2f}'.format)
    )
    
    # format Date
    transactions_pretty['date'] = (
        transactions_pretty['date'].dt.strftime('%Y-%m-%d')
    )
    
    # subset columns
    pretty_cols = [
        'date', 'plaidName','amount', 'category_name', 'account_name', 'notes'
    ]
    transactions_pretty = transactions_pretty.loc[:, pretty_cols]
    transactions_pretty.columns = [
        "Date", "Transaction", "Amount", "Category", "Account", "Notes"
    ]
    
    transactions_pretty.sort_values('Date', inplace=True, ascending=False)
    
    return transactions_pretty

def order_budget(budget, config, user):
    cat_order = pd.DataFrame(config["users"][user]['cat_order'])
    cat_order = cat_order.reset_index()
    cat_order.columns = ['order', 'category']

    # Merge with category orders
    budget = pd.merge(budget, cat_order, left_index=True, 
                            right_on='category', how='left')

    # Sort by category order
    budget.sort_values('order', inplace=True, ascending=True)

    budget = budget.set_index('category')
    budget.index.name = "category"

    # budget.loc["Total"] = budget.drop('income').sum(numeric_only=True)

    budget = budget.drop(columns=["order"])
    budget = budget.reset_index()

    return budget

def plot_csp_by_label(processed_transactions, as_percent):
    df = processed_transactions.groupby([processed_transactions['date'].dt.year, 'csp_label'])['amount'].sum().reset_index()
    df.columns = ['date', 'csp_label', 'value']
    df = df.loc[df['date'] >= 2020]
    df['value'] = df['value'].abs()

    # Define the desired order
    desired_order = ["fixed", "investments", "guilt-free", "savings"]

    # Pivot the DataFrame to reshape it for calculations
    pivot_df = df.pivot(index="date", columns="csp_label", values="value").fillna(0)

    # Ensure all desired categories are in the DataFrame
    for col in desired_order:
        if col not in pivot_df.columns:
            pivot_df[col] = 0

    # Normalize by income for each year
    if as_percent:
        pivot_df[desired_order] = pivot_df[desired_order].div(pivot_df["income"], axis=0)

    # Handle missing or zero income to avoid division errors
    pivot_df[desired_order] = pivot_df[desired_order].fillna(0)

    # Define custom Minty theme-inspired colors
    minty_colors = ['#c2b2b4', '#78c2ad', '#5bc0be', '#8447ff', '#d972ff', '#ffb2e6']

    # Create the stacked area chart using stackgroup
    fig = go.Figure()

    for i, col in enumerate(desired_order):
        fig.add_trace(go.Scatter(
            x=pivot_df.index,
            y=pivot_df[col],
            mode='lines',
            stackgroup='one',  # All traces share the same stackgroup
            name=col,
            line=dict(color=minty_colors[i % len(minty_colors)]),
            # hoverinfo='x', 
            hovertemplate='{x}: $%{y:,.0f} <extra></extra>',
            hoverlabel=dict(bgcolor='#888', bordercolor='#888', 
                            font=dict(color='white')),
        ))
    
    if not as_percent:
        fig.add_trace(go.Scatter(
            x=pivot_df.index,
            y=pivot_df['income'],
            mode='lines',
            name='income',
            line_color='#888',
            line_dash='dot',
            hovertemplate='Income: $%{y:,.0f} <extra></extra>',
            hoverlabel=dict(bgcolor='#888', bordercolor='#888', 
                            font=dict(color='white')),
        ))
        
    if as_percent:
        for trace in fig.data:
            trace.hovertemplate='Proportion: %{y:.0%} <extra></extra>'
        



    # Update layout
    fig.update_layout(
        xaxis_title="Year",
        yaxis_title="Total Spending",
        yaxis_tickformat="$,.0f",
        template="plotly_white",
        showlegend=True,
        yaxis_automargin=True,
        xaxis_automargin=True,
        legend=dict(
            font=dict(color="#888")
        ),
        font=dict(
            color="#888"
        )
        # colorway=plotly.colors.qualitative.Prism,
        # yaxis=dict(range=[0, 1])
    )

    if as_percent:
        fig.update_layout(
            yaxis_range=[0, 1.3],
            yaxis_title="Proportion of Income",
            yaxis_tickformat=".0%",
        )

    # Show the figure
    return fig


def calculate_social_security_benefit(earnings: pd.Series, claim_age: int) -> float:
    """
    Calculate the monthly Social Security benefit given a series of 35 years of earnings 
    and the age at which benefits are first taken.

    Parameters:
    earnings (pd.Series): A series of earnings values.
    claim_age (int): The age at which benefits are first taken.

    Returns:
    float: Estimated monthly Social Security benefit.
    """
    earnings = np.array(earnings)
    
    if len(earnings) < 35:
        print("⚠️ Warning: Earnings contains less than 35 years of data.")
        highest_earnings = np.sort(earnings)[::-1][:len(earnings)]  # Use what we have
    else:
        highest_earnings = np.sort(earnings)[::-1][:35]  # Take top 35 values


    # Ensure claim age is within valid range (62-70)
    if claim_age < 62 or claim_age > 70:
        raise ValueError("Claim age must be between 62 and 70.")
    
    # Social Security Bend Points for 2024
    bend_point_1 = 1174  # 90% applies below this
    bend_point_2 = 7078  # 32% applies between this range

    # Compute AIME (Average Indexed Monthly Earnings)
    aime = highest_earnings.sum() / (35 * 12)

    # Compute PIA (Primary Insurance Amount)
    if aime <= bend_point_1:
        pia = 0.9 * aime
    elif aime <= bend_point_2:
        pia = 0.9 * bend_point_1 + 0.32 * (aime - bend_point_1)
    else:
        pia = 0.9 * bend_point_1 + 0.32 * (bend_point_2 - bend_point_1) + 0.15 * (aime - bend_point_2)

    # Adjust for claiming age
    delayed_retirement_factors = {
        62: 0.7,  # 30% reduction
        63: 0.75,
        64: 0.80,
        65: 0.866,
        66: 0.933,
        67: 1.0,  # Full PIA at FRA
        68: 1.08,
        69: 1.16,
        70: 1.24  # 8% increase per year after FRA
    }

    # Apply the adjustment factor
    benefit = pia * delayed_retirement_factors[claim_age]

    return round(benefit, 2)

def calculate_married_joint_tax(income):
    """
    Calculate federal income tax for a married couple filing jointly in 2024.

    Parameters:
    income (float): The taxable income of the couple.

    Returns:
    float: The total federal income tax owed.
    """
    # 2024 Tax Brackets for Married Filing Jointly
    brackets = [
        (0, 23000, 0.10),
        (23000, 94300, 0.12),
        (94300, 201050, 0.22),
        (201050, 383900, 0.24),
        (383900, 487450, 0.32),
        (487450, 731200, 0.35),
        (731200, float('inf'), 0.37)
    ]

    tax_owed = 0
    for lower, upper, rate in brackets:
        if income > lower:
            taxable_amount = min(income, upper) - lower
            tax_owed += taxable_amount * rate
        else:
            break

    return round(tax_owed, 2)


def load_vanguard_cost_basis(csv_path: str) -> pd.DataFrame:
    """
    Load Vanguard cost basis CSV export and extract initial cost basis info.

    Parameters:
    - csv_path: str, path to Vanguard CSV export

    Returns:
    - DataFrame with columns: account, symbol, cost_basis
    """
    # Read CSV with appropriate options
    df = pd.read_csv(csv_path)

    # Clean up column names (remove extra whitespace)
    df.columns = df.columns.str.strip()

    # Convert cost values to numeric (strip $ and commas if needed)
    df['Total cost'] = pd.to_numeric(df['Total cost'], errors='coerce')

    # Standardize column names and output
    clean_df = df.rename(columns={
        'Account': 'account',
        'Symbol/CUSIP': 'symbol',
        'Total cost': 'cost_basis'
    })

    # Select and aggregate
    cost_basis_df = clean_df[['account', 'symbol', 'cost_basis']] \
        .groupby(['account', 'symbol'], as_index=False) \
        .sum()

    return cost_basis_df

# stored_transactions = upload_transactions(FILE_NAME)
# transactions = pd.DataFrame(store_subsetted_transactions('erik', '2024-01-01', '2024-12-31', stored_transactions))
# budget = read_budget(BUDGET_NAME)
# budget_report = build_budget_report(transactions, budget, dt.strptime('2024-01-01', '%Y-%m-%d'), dt.strptime('2024-12-31', '%Y-%m-%d'))
# budget_report = order_budget_report(budget_report)
# fig = plot_report(budget_report, dt.strptime('2024-01-01', '%Y-%m-%d'), dt.strptime('2024-12-31', '%Y-%m-%d'))