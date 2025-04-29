import dash
from dash import dcc, html, dash_table, Input, Output
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import odoo_client  # nosso módulo de conexão com Odoo

# 1) Carregar dados
df_projects = odoo_client.get_projects()
df_tasks    = odoo_client.get_tasks()

today = datetime.now().date()

# 2) Converter datas brutas
df_tasks['date_end_dt']      = pd.to_datetime(df_tasks['date_end'],      errors='coerce').dt.date
df_tasks['date_deadline_dt'] = pd.to_datetime(df_tasks['date_deadline'], errors='coerce').dt.date

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

# 9) App layout
app = dash.Dash(__name__)
common_style = {'textAlign':'left','padding':'5px','minWidth':'80px','maxWidth':'150px','whiteSpace':'normal','overflow':'hidden','textOverflow':'ellipsis'}
app.layout = html.Div(style={'padding':'20px','fontFamily':'Arial, sans-serif','backgroundColor':'#f5f5f5'},children=[
    html.H1('Dashboard de Projetos',style={'textAlign':'center','color':'#333'}),
    html.Div([html.H2('Resumo dos Projetos'),dcc.Graph(id='projetos-grafico')],style={'marginTop':'30px'}),
    html.Div([html.H2('Projetos Ativos'),dash_table.DataTable(
        id='projects-table',columns=[
            {'name':'Departamento','id':'name'},{'name':'Gerente','id':'user_id'},{'name':'Total de Tarefas','id':'total_tasks'},{'name':'Em Aberto','id':'open_tasks'},{'name':'Atrasadas','id':'delayed_tasks'}
        ],data=df_summary.to_dict('records'),row_selectable='single',filter_action='native',sort_action='native',sort_mode='multi',style_table={'overflowX':'auto','backgroundColor':'white'},style_header={'backgroundColor':'#007BFF','color':'white','fontWeight':'bold'},style_cell=common_style
    )],style={'marginTop':'30px'}),
    html.Div([html.H2('Tarefas em Andamento'),dcc.Graph(id='gantt-chart'),dash_table.DataTable(
        id='tasks-table',columns=[
            {'name':'Nome','id':'name'},{'name':'Criada em','id':'create_date'},{'name':'Prazo','id':'date_deadline'},{'name':'Status','id':'status'}
        ],data=[],filter_action='native',sort_action='native',sort_mode='multi',style_table={'overflowX':'auto','backgroundColor':'white'},style_header={'backgroundColor':'#007BFF','color':'white','fontWeight':'bold'},style_cell=common_style,style_data_conditional=[
            {'if':{'filter_query':'{status}="Atrasada"'},'backgroundColor':'#FF0000','color':'white'}
        ]
    )],style={'marginTop':'30px','height':'600px','overflowY':'scroll'})
])

# 10) Callbacks
@app.callback(Output('projetos-grafico','figure'),Input('projects-table','data'))
def update_projects_graph(projects_data):
    df=pd.DataFrame(projects_data)
    if df.empty: return {}
    fig=px.bar(df,x='name',y=['total_tasks','open_tasks','delayed_tasks'],barmode='group',labels={'name':'Departamento','value':'Quantidade','variable':'Tipo'},title='Resumo de Tarefas por Departamento',color_discrete_map={'total_tasks':'#636EFA','open_tasks':'#00CC96','delayed_tasks':'#FF0000'})
    for t in fig.data: t.name={'total_tasks':'Total','open_tasks':'Em Aberto','delayed_tasks':'Atrasadas'}.get(t.name,t.name)
    return fig

@app.callback(Output('tasks-table','data'),Output('gantt-chart','figure'),Input('projects-table','selected_rows'))
def update_tasks(selected_rows):
    if not selected_rows: return [],{}
    pid=df_summary.iloc[selected_rows[0]]['id']
    df_sel=df_tasks[(df_tasks['project_id_id']==pid)&(df_tasks['is_open'])].copy()
    # preparar status e datas de exibição
    df_sel['status']=df_sel.apply(lambda r:'Atrasada' if r['is_delayed'] else 'No Prazo',axis=1)
    df_sel['create_date']=pd.to_datetime(df_sel['create_date'],errors='coerce').dt.strftime('%d/%m/%Y').fillna('—')
    df_sel['date_deadline']=pd.to_datetime(df_sel['date_deadline'],errors='coerce').dt.strftime('%d/%m/%Y').fillna('—')
    # Gantt: barras até hoje para atrasadas ou até deadline para não atrasadas
    df_sel['start_dt']=pd.to_datetime(df_sel['create_date'],dayfirst=True,errors='coerce')
    df_sel['finish_dt']=df_sel.apply(lambda r: pd.to_datetime(today) if r['is_delayed'] else pd.to_datetime(r['date_deadline'],dayfirst=True,errors='coerce'),axis=1)
    gantt=px.timeline(df_sel,x_start='start_dt',x_end='finish_dt',y='name',color='status',title='Gantt das Tarefas',color_discrete_map={'No Prazo':'#00CC96','Atrasada':'#FF0000'})
    gantt.update_yaxes(autorange='reversed')
    # marcador de deadline original
    gantt.add_trace(go.Scatter(x=pd.to_datetime(df_sel['date_deadline'],dayfirst=True,errors='coerce'),y=df_sel['name'],mode='markers',marker_symbol='line-ns-open',marker_line_width=2,marker_size=12,marker_color='black',showlegend=False))
    # dados tabela
    recs=df_sel[['name','create_date','date_deadline','status']].to_dict('records')
    return recs,gantt

# 11) Rodar servidor
if __name__=='__main__': app.run(host='0.0.0.0',port=8050,debug=True)
