import dash
from dash import dcc, html, dash_table, Input, Output
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import odoo_client

# 1) Carregar dados
df_projects = odoo_client.get_projects()
df_tasks    = odoo_client.get_tasks()

today = datetime.now().date()

# 2) Converter datas brutas
df_tasks['date_end_dt']      = pd.to_datetime(df_tasks['date_end'], errors='coerce').dt.date
_df_deadline = pd.to_datetime(df_tasks['date_deadline'], errors='coerce')
df_tasks['date_deadline_dt'] = _df_deadline.dt.date

# 3) IDs de project_id e parent_id
df_tasks['project_id_id'] = df_tasks['project_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
df_tasks['parent_id_id']  = df_tasks['parent_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else None)

# 4) Tarefas-pai somente
df_tasks = df_tasks[df_tasks['parent_id_id'].isna()].copy()

# 5) Estados
df_tasks['is_open']   = df_tasks['state'].isin(['01_in_progress','02_changes_requested','03_approved'])
df_tasks['concluida'] = df_tasks['state'].isin(['1_done','1_canceled']).map({True:'Sim',False:'Não'})

# 6) Atrasadas
df_tasks['is_delayed'] = df_tasks.apply(lambda r: r['is_open'] and pd.notna(r['date_deadline_dt']) and r['date_deadline_dt'] < today, axis=1)

# 7) Contagem por projeto
open_series    = df_tasks[df_tasks['is_open']].groupby('project_id_id').size()
delayed_series = df_tasks[df_tasks['is_delayed']].groupby('project_id_id').size()
df_projects['open_tasks']    = df_projects['id'].map(open_series).fillna(0).astype(int)
df_projects['delayed_tasks'] = df_projects['id'].map(delayed_series).fillna(0).astype(int)

# 8) Resumo
df_summary = df_projects.rename(columns={'task_count':'total_tasks'})[['id','name','user_id','total_tasks','open_tasks','delayed_tasks']]

# Brand colors
PRIMARY = '#004aad'
ACCENT  = '#ffc107'
BG      = '#f9f9f9'
FONT    = 'Helvetica, Arial, sans-serif'

# 9) App layout
app = dash.Dash(__name__)
app.layout = html.Div(
    style={'backgroundColor': BG, 'fontFamily': FONT, 'padding': '20px'},
    children=[
        # Header com logo
        html.Div(
            style={'display':'flex','alignItems':'center','marginBottom':'20px'},
            children=[
                html.Img(src='/assets/dac_logo.png', style={'height':'60px','marginRight':'15px'}),
                html.H1('Dashboard DAC Engenharia', style={'color': PRIMARY, 'margin': 0})
            ]
        ),
        # Tabs
        dcc.Tabs(
            id='tabs',
            value='tab-summary',
            children=[
                dcc.Tab(
                    label='Resumo',
                    value='tab-summary',
                    children=[
                        html.Div(
                            [
                                html.H2('Resumo dos Departamentos', style={'color': PRIMARY}),
                                dcc.Graph(id='projetos-grafico')
                            ],
                            style={'marginTop':'20px'}
                        )
                    ]
                ),
                dcc.Tab(
                    label='Departamentos',
                    value='tab-projects',
                    children=[
                        html.Div(
                            [
                                html.H3('Departamentos', style={'color': PRIMARY}),
                                dash_table.DataTable(
                                    id='projects-table',
                                    columns=[
                                        {'name':'Departamento','id':'name'},
                                        {'name':'Gerente','id':'user_id'},
                                        {'name':'Total','id':'total_tasks'},
                                        {'name':'Aberto','id':'open_tasks'},
                                        {'name':'Atrasadas','id':'delayed_tasks'}
                                    ],
                                    data=df_summary.to_dict('records'),
                                    row_selectable='single',
                                    filter_action='native',
                                    sort_action='native',
                                    style_table={'overflowX':'auto','backgroundColor':'white'},
                                    style_header={'backgroundColor': PRIMARY,'color':'white'},
                                    style_cell={'textAlign':'left','padding':'5px'}
                                ),
                                dcc.Graph(id='project-pie', style={'marginTop':'20px'})
                            ]
                        )
                    ]
                ),
                dcc.Tab(
                    label='Tarefas',
                    value='tab-tasks',
                    children=[
                        html.Div(
                            [
                                html.H3('Tarefas em Andamento', style={'color': PRIMARY}),
                                dcc.Dropdown(
                                    id='tasks-project-dropdown',
                                    options=[{'label': r['name'], 'value': r['id']} for r in df_summary.to_dict('records')],
                                    placeholder='Selecione um projeto',
                                    style={'marginBottom':'10px'}
                                ),
                                dcc.Graph(id='gantt-chart', style={'height':'1000px', 'overflowY':'scroll'}),
                                dash_table.DataTable(
                                    id='tasks-table',
                                    columns=[
                                        {'name':'Nome','id':'name'},
                                        {'name':'Criada','id':'create_date'},
                                        {'name':'Prazo','id':'date_deadline'},
                                        {'name':'Status','id':'status'}
                                    ],
                                    data=[],
                                    filter_action='native',
                                    sort_action='native',
                                    style_table={'overflowX':'auto','backgroundColor':'white'},
                                    style_header={'backgroundColor': PRIMARY,'color':'white'},
                                    style_cell={'textAlign':'left','padding':'5px'},
                                    style_data_conditional=[
                                        {'if':{'filter_query':'{status}="Atrasada"'},'backgroundColor':'#fdecea','color':'#a80000'}
                                    ]
                                )
                            ]
                        )
                    ]
                )
            ]
        )
    ]
)

# 10) Callbacks
@app.callback(
    Output('projetos-grafico','figure'),
    Output('project-pie','figure'),
    Input('projects-table','selected_rows'),
    Input('projects-table','data')
)
def update_projects_graph(selected_rows, projects_data):
    df = pd.DataFrame(projects_data)
    if df.empty:
        return {}, {}
    fig = px.bar(
        df, x='name', y=['total_tasks','open_tasks','delayed_tasks'], barmode='group',
        labels={'name':'Departamento','value':'Quantidade','variable':'Tipo'}, title='',
        color_discrete_map={'total_tasks':PRIMARY,'open_tasks':ACCENT,'delayed_tasks':'#d62828'}
    )
    fig.update_layout(plot_bgcolor='white', paper_bgcolor=BG, legend=dict(title='Legenda'), margin=dict(t=20))
    for t in fig.data:
        t.name = {'total_tasks':'Total','open_tasks':'Em Aberto','delayed_tasks':'Atrasadas'}.get(t.name)
    pie = {}
    if selected_rows:
        proj = df.iloc[selected_rows[0]]
        pie = px.pie(
            df.iloc[selected_rows], names=['Total','Em Aberto','Atrasadas'], values=[proj.total_tasks, proj.open_tasks, proj.delayed_tasks],
            color_discrete_map={'Total':PRIMARY,'Em Aberto':ACCENT,'Atrasadas':'#d62828'}
        )
        pie.update_traces(marker=dict(colors=[PRIMARY, ACCENT, '#d62828']))
        pie.update_layout(plot_bgcolor='white', paper_bgcolor=BG, margin=dict(t=30))
    return fig, pie

@app.callback(
    Output('tasks-table','data'),
    Output('gantt-chart','figure'),
    Input('tasks-project-dropdown','value')
)
def update_tasks(value):
    if not value:
        return [], {}
    df_sel = df_tasks[(df_tasks['project_id_id']==value) & (df_tasks['is_open'])].copy()
    df_sel['status'] = df_sel.apply(lambda r: 'Atrasada' if r['is_delayed'] else 'No Prazo', axis=1)
    df_sel['create_date'] = pd.to_datetime(df_sel['create_date'], errors='coerce').dt.strftime('%d/%m/%Y')
    df_sel['date_deadline'] = pd.to_datetime(df_sel['date_deadline'], errors='coerce').dt.strftime('%d/%m/%Y')
    df_sel['start_dt'] = pd.to_datetime(df_sel['create_date'], dayfirst=True)
    df_sel['finish_dt'] = df_sel.apply(lambda r: pd.to_datetime(today) if r['is_delayed'] else pd.to_datetime(r['date_deadline'], dayfirst=True), axis=1)
    gantt = px.timeline(
        df_sel, x_start='start_dt', x_end='finish_dt', y='name', color='status',
        color_discrete_map={'No Prazo':ACCENT,'Atrasada':'#d62828'}
    )
    gantt.update_traces(marker=dict(line_color=PRIMARY, line_width=0.5))
    gantt.update_layout(
        title='Tarefas em Andamento',
        xaxis_title='Prazo',
        yaxis_title='Tarefa',
        legend_title='Status',
        xaxis_tickformat='%d/%m/%Y',
        yaxis_tickformat='%d/%m/%Y'
    )
    
    gantt.update_layout(plot_bgcolor='white', paper_bgcolor=BG, margin=dict(t=30))
    gantt.update_yaxes(autorange='reversed')
    gantt.add_trace(
        go.Scatter(
            x=pd.to_datetime(df_sel['date_deadline'], dayfirst=True),
            y=df_sel['name'], mode='markers', marker_symbol='line-ns-open',
            marker_line_width=2, marker_size=12, marker_color='black', showlegend=False
        )
    )
    recs = df_sel[['name','create_date','date_deadline','status']].to_dict('records')
    return recs, gantt

# 11) Run
if __name__=='__main__':
    app.run(host='0.0.0.0', port=8050, debug=True)

