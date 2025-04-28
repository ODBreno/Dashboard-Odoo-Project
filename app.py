import dash
from dash import dcc, html, dash_table, Input, Output
import pandas as pd
import plotly.express as px
from datetime import datetime
import odoo_client  # nosso módulo de conexão com Odoo

# 1) Carregar dados
df_projects = odoo_client.get_projects()
df_tasks    = odoo_client.get_tasks()

today = datetime.now().date()

# 2) Converter datas
df_tasks['date_end_dt']      = pd.to_datetime(df_tasks['date_end'],      errors='coerce').dt.date
df_tasks['date_deadline_dt'] = pd.to_datetime(df_tasks['date_deadline'], errors='coerce').dt.date

# 3) Extrair IDs de project_id e parent_id
# Many2one vem como [id, nome] → pegamos o [0]
if 'project_id' in df_tasks.columns:
    df_tasks['project_id_id'] = df_tasks['project_id'].apply(
        lambda v: v[0] if isinstance(v, (list, tuple)) else v
    )
else:
    raise KeyError("Nenhuma coluna 'project_id' em df_tasks")

if 'parent_id' in df_tasks.columns:
    df_tasks['parent_id_id'] = df_tasks['parent_id'].apply(
        lambda v: v[0] if isinstance(v, (list, tuple)) else None
    )
else:
    # se não houver subtasks no seu read, define tudo como None
    df_tasks['parent_id_id'] = None

# 4) Filtrar apenas tarefas-pai (parent_id_id é None)
df_tasks = df_tasks[df_tasks['parent_id_id'].isna()].copy()

# 5) Definir estados abertos / fechados
open_states   = ['01_in_progress', '02_changes_requested', '03_approved']
closed_states = ['1_done', '1_canceled']

df_tasks['is_open']   = df_tasks['state'].isin(open_states)
df_tasks['concluida'] = df_tasks['state'].isin(closed_states).map({True: 'Sim', False: 'Não'})

# 6) Marcar atrasadas
df_tasks['is_delayed'] = df_tasks.apply(
    lambda r: r['is_open']
              and pd.notna(r['date_deadline_dt'])
              and r['date_deadline_dt'] < today,
    axis=1
)

# 7) Recontagem por projeto
open_series    = df_tasks[df_tasks['is_open']].groupby('project_id_id').size()
delayed_series = df_tasks[df_tasks['is_delayed']].groupby('project_id_id').size()

df_projects['open_tasks']    = df_projects['id'].map(open_series).fillna(0).astype(int)
df_projects['delayed_tasks'] = df_projects['id'].map(delayed_series).fillna(0).astype(int)

# 8) Preparar resumo
df_summary = df_projects.rename(columns={'task_count': 'total_tasks'})[[
    'id', 'name', 'user_id', 'total_tasks', 'open_tasks', 'delayed_tasks'
]]

# 9) Montar Dash
app = dash.Dash(__name__)
common_style = {
    'textAlign': 'left', 'padding': '5px', 'minWidth': '80px',
    'maxWidth': '150px', 'whiteSpace': 'normal', 'overflow': 'hidden', 'textOverflow': 'ellipsis'
}

app.layout = html.Div(style={'padding': '20px', 'fontFamily': 'Arial, sans-serif', 'backgroundColor': '#f5f5f5'}, children=[
    html.H1('Dashboard de Projetos', style={'textAlign': 'center', 'color': '#333'}),
    html.Div([html.H2('Resumo dos Projetos'), dcc.Graph(id='projetos-grafico')], style={'marginTop': '30px'}),
    html.Div([html.H2('Projetos Ativos'), dash_table.DataTable(
        id='projects-table',
        columns=[
            {'name': 'Departamento',     'id': 'name'},
            {'name': 'Gerente',          'id': 'user_id'},
            {'name': 'Total de Tarefas', 'id': 'total_tasks'},
            {'name': 'Em Aberto',        'id': 'open_tasks'},
            {'name': 'Atrasadas',        'id': 'delayed_tasks'}
        ],
        data=df_summary.to_dict('records'),
        row_selectable='single', filter_action='native',
        sort_action='native', sort_mode='multi',
        style_table={'overflowX': 'auto', 'backgroundColor': 'white'},
        style_header={'backgroundColor': '#007BFF', 'color': 'white', 'fontWeight': 'bold'},
        style_cell=common_style
    )], style={'marginTop': '30px'}),
    html.Div([html.H2('Tarefas do Projeto Selecionado'),
              dcc.Graph(id='tarefas-status-grafico'),
              dash_table.DataTable(
                  id='tasks-table',
                  columns=[
                      {'name': 'Nome',       'id': 'name'},
                      {'name': 'Criada em', 'id': 'create_date'},
                      {'name': 'Prazo',     'id': 'date_deadline'},
                      {'name': 'Concluída', 'id': 'concluida'},
                      {'name': 'Status',    'id': 'status'}
                  ],
                  data=[], filter_action='native', sort_action='native', sort_mode='multi',
                  style_table={'overflowX': 'auto', 'backgroundColor': 'white'},
                  style_header={'backgroundColor': '#007BFF', 'color': 'white', 'fontWeight': 'bold'},
                  style_cell=common_style,
                  style_data_conditional=[
                      {'if': {'filter_query': '{status} = "Atrasada"'}, 'backgroundColor': '#FFCDD2'},
                      {'if': {'filter_query': '{status} = "Concluída"'}, 'backgroundColor': '#C8E6C9'}
                  ]
              )], style={'marginTop': '30px'})
])

# 10) Callbacks
@app.callback(Output('projetos-grafico', 'figure'), Input('projects-table', 'data'))
def update_projects_graph(projects_data):
    df = pd.DataFrame(projects_data)
    if df.empty:
        return {}
    return px.bar(df, x='name', y=['total_tasks','open_tasks','delayed_tasks'],
                  barmode='group',
                  labels={'name':'Departamento','value':'Quantidade','variable':'Tipo'},
                  title='Resumo de Tarefas por Departamento')

@app.callback(
    Output('tasks-table','data'),
    Output('tarefas-status-grafico','figure'),
    Input('projects-table','selected_rows')
)
def update_tasks(selected_rows):
    if not selected_rows:
        return [], {}
    proj_id = df_summary.iloc[selected_rows[0]]['id']
    df_sel  = df_tasks[df_tasks['project_id_id']==proj_id].copy()
    df_sel['status'] = df_sel.apply(
        lambda r: 'Atrasada' if r['is_delayed']
                  else ('Concluída' if not r['is_open'] else 'No Prazo'),
        axis=1
    )
    fig  = px.pie(df_sel, names='status', title='Status das Tarefas')
    recs = df_sel[['name','create_date','date_deadline','concluida','status']].to_dict('records')
    return recs, fig

# 11) Rodar servidor
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8050, debug=True)
