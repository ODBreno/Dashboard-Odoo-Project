import dash
from dash import dcc, html, Input, Output, callback_context
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import odoo_client

# Constants de estilo
PRIMARY = '#004aad'
ACCENT  = '#ffc107'
BG      = '#f9f9f9'
FONT    = 'Helvetica, Arial, sans-serif'

# Carrega e prepara dados

def load_and_prepare_data():
    df_projects = odoo_client.get_projects()
    df_tasks = odoo_client.get_tasks()

    # Datas como Timestamps
    df_tasks['date_deadline'] = pd.to_datetime(df_tasks['date_deadline'], errors='coerce')
    df_tasks['create_date']   = pd.to_datetime(df_tasks['create_date'], errors='coerce')

    # IDs relacionais
    for col in ['project_id', 'parent_id']:
        df_tasks[f"{col}_id"]   = df_tasks[col].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else None)
        df_tasks[f"{col}_name"] = df_tasks[col].apply(lambda v: v[1] if isinstance(v, (list, tuple)) and len(v)>1 else None)

    # Dependências
    def extract_ids(v):
        if isinstance(v, (list, tuple)):
            ids = []
            for x in v:
                if isinstance(x, (list, tuple)) and x:
                    ids.append(x[0])
                elif isinstance(x, int):
                    ids.append(x)
            return ids
        return []

    df_tasks['depend_on_ids_list'] = df_tasks['depend_on_ids'].apply(extract_ids)

    # Estado e atraso
    now = pd.Timestamp.now().normalize()
    df_tasks['is_open'] = df_tasks['state'].isin(['01_in_progress','02_changes_requested','03_approved'])
    df_tasks['is_delayed'] = df_tasks.apply(
        lambda r: r['is_open'] and pd.notna(r['date_deadline']) and r['date_deadline'] < now,
        axis=1
    )

    # Cálculo de datas de início
    def recalc_starts(df):
        df = df.copy()
        task_map = {r['id']: r for _,r in df.iterrows()}
        def find_start(tid, seen=None):
            if seen is None: seen=set()
            if tid in seen or tid not in task_map:
                return pd.NaT
            seen.add(tid)
            task = task_map[tid]
            deps = task['depend_on_ids_list']
            if not deps:
                return task['create_date']
            latest=None
            for d in deps:
                dep=task_map.get(d)
                if dep is None: continue
                end=dep['date_deadline']
                if pd.isna(end):
                    st=find_start(d,seen.copy())
                    if pd.notna(st): end=st+timedelta(days=7)
                if pd.notna(end) and (latest is None or end>latest):
                    latest=end
            return (latest+timedelta(days=1)) if latest is not None else task['create_date']
        df['calculated_start'] = df['id'].apply(find_start)
        return df

    df_tasks = recalc_starts(df_tasks)

    # Resumo
    summary = df_projects.copy()
    oc = df_tasks[df_tasks['is_open']].groupby('project_id_id').size()
    dc = df_tasks[df_tasks['is_delayed']].groupby('project_id_id').size()
    summary['open_tasks']    = summary['id'].map(oc).fillna(0).astype(int)
    summary['delayed_tasks'] = summary['id'].map(dc).fillna(0).astype(int)
    summary['total_tasks']   = summary.get('task_count', 0)
    return df_projects, df_tasks, summary

# Globals
df_projects, df_tasks, df_summary = load_and_prepare_data()
now = pd.Timestamp.now().normalize()

# Gantt generator
def generate_gantt(df_sel):
    fig = go.Figure()
    if df_sel.empty:
        return fig.update_layout(title="Nenhuma tarefa selecionada", plot_bgcolor='white', paper_bgcolor=BG)

    df = df_sel.copy()
    df['start'] = pd.to_datetime(df['calculated_start'].fillna(df['create_date']))
    df['finish']= pd.to_datetime(df['date_deadline'])
    df=df.dropna(subset=['start','finish'])
    df['status']=df['is_delayed'].map({True:'Atrasada',False:'No Prazo'})

    fig = px.timeline(
        df, x_start='start', x_end='finish', y='name', color='status',
        color_discrete_map={'No Prazo':ACCENT,'Atrasada':'#d62828'}
    )
    fig.update_traces(marker_line_color=PRIMARY)
    fig.update_layout(
        title='Cronograma de Tarefas', yaxis={'autorange':'reversed'},
        plot_bgcolor='white', paper_bgcolor=BG,
        margin=dict(t=50,b=20,l=20,r=20), height=max(300,len(df)*40),
        legend_title_text='Status', xaxis_title='Data'
    )

    # Dependências
    id_map={r['id']:r for _,r in df.iterrows()}
    for _,row in df.iterrows():
        for d in row['depend_on_ids_list']:
            src = id_map.get(d)
            if src is None:
                continue
            x0, y0 = src['finish'], src['name']
            x1, y1 = row['start'], row['name']
            fig.add_shape(
                type='line', x0=x0, y0=y0, x1=x1, y1=y1,
                line=dict(color='#666666', width=2, dash='dot'), layer='below'
            )
            fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, showarrow=True, arrowhead=3, arrowsize=1)

    # Linha 'Hoje' como shape + annotation
    fig.add_shape(
        type='line', x0=now, x1=now,
        y0=0, y1=1, xref='x', yref='paper',
        line_dash='dash', line_color='green'
    )
    fig.add_annotation(
        x=now, y=1, xref='x', yref='paper',
        text='Hoje', showarrow=False, yanchor='bottom', align='right'
    )

    return fig

# App layout
app = dash.Dash(__name__, suppress_callback_exceptions=True)
proj_opts=[{'label':n,'value':i} for i,n in zip(df_projects['id'],df_projects['name'])]
app.layout=html.Div(style={'fontFamily':FONT,'bg':BG,'padding':20},children=[
    html.H1('Dashboard DAC Engenharia',style={'color':PRIMARY,'textAlign':'center'}),
    dcc.Tabs(id='tabs',value='tab-summary',children=[
        dcc.Tab(label='Resumo',value='tab-summary',children=html.Div(
            dcc.Graph(figure=px.bar(
                df_summary,x='name',y=['total_tasks','open_tasks','delayed_tasks'],barmode='group',
                labels={'name':'Projeto','value':'Número de Tarefas','variable':'Tipo'},
                color_discrete_map={'total_tasks':PRIMARY,'open_tasks':ACCENT,'delayed_tasks':'#d62828'}
            ).update_layout(plot_bgcolor='white',paper_bgcolor=BG,margin=dict(t=30),
                            legend_title_text='Tipo de Tarefa',xaxis_title='Projeto',yaxis_title='Número de Tarefas')
            )
        ,style={'padding':20})),
        dcc.Tab(label='Cronograma',value='tab-gantt',children=html.Div([
            html.Div(style={'display':'flex','marginBottom':'20px'},children=[
                html.Div([html.Label('Projeto:',style={'fontWeight':'bold'}),dcc.Dropdown(id='project-dropdown',options=proj_opts,placeholder='Selecione um projeto')],style={'flex':1,'paddingRight':'10px'}),
                html.Div([html.Label('Tarefa Principal:',style={'fontWeight':'bold'}),dcc.Dropdown(id='parent-task-dropdown',placeholder='Selecione projeto primeiro')],style={'flex':1,'paddingRight':'10px'}),
                html.Div([html.Label('Subtarefa:',style={'fontWeight':'bold'}),dcc.Dropdown(id='child-task-dropdown',placeholder='Selecione tarefa principal primeiro')],style={'flex':1})
            ]),
            html.H3('Tarefas do Projeto',style={'color':PRIMARY}),dcc.Graph(id='project-gantt'),
            html.H3('Subtarefas',style={'color':PRIMARY}),dcc.Graph(id='subtasks-gantt')
        ],style={'padding':20}))
    ])
])

# Callbacks
@app.callback(Output('parent-task-dropdown','options'),Input('project-dropdown','value'))
def set_parents(pid):
    if not pid: return []
    dfp=df_tasks[(df_tasks['project_id_id']==pid)&(df_tasks['parent_id_id'].isna())]
    return [{'label':r['name'],'value':r['id']}for _,r in dfp.iterrows()]

@app.callback(Output('child-task-dropdown','options'),Input('parent-task-dropdown','value'))
def set_children(p_id):
    if not p_id: return []
    dfc=df_tasks[df_tasks['parent_id_id']==p_id]
    return [{'label':r['name'],'value':r['id']}for _,r in dfc.iterrows()]

@app.callback(Output('project-gantt','figure'),[Input('project-dropdown','value'),Input('parent-task-dropdown','value')])
def update_proj(pid,pid_p):
    trg=callback_context.triggered[0]['prop_id']
    if 'project-dropdown' in trg and pid:
        sel=df_tasks[(df_tasks['project_id_id']==pid)&(df_tasks['parent_id_id'].isna())]
        return generate_gantt(sel)
    if 'parent-task-dropdown' in trg and pid_p:
        m=df_tasks[df_tasks['id']==pid_p]
        dps=df_tasks[df_tasks['id'].isin(m.iloc[0]['depend_on_ids_list'])]
        dnds=df_tasks[df_tasks['depend_on_ids_list'].apply(lambda lst:pid_p in lst)]
        return generate_gantt(pd.concat([m,dps,dnds]))
    return go.Figure().update_layout(title='Selecione um projeto')

@app.callback(Output('subtasks-gantt','figure'),[Input('parent-task-dropdown','value'),Input('child-task-dropdown','value')])
def update_sub(p_id,c_id):
    trg=callback_context.triggered[0]['prop_id']
    if 'parent-task-dropdown' in trg and p_id:
        sel = df_tasks[df_tasks['parent_id_id']==p_id]
        return generate_gantt(sel)
    if 'child-task-dropdown' in trg and c_id:
        s = df_tasks[df_tasks['id']==c_id]
        dp = df_tasks[df_tasks['id'].isin(s.iloc[0]['depend_on_ids_list'])]
        dn = df_tasks[df_tasks['depend_on_ids_list'].apply(lambda lst: c_id in lst)]
        return generate_gantt(pd.concat([s, dp, dn]))
    return go.Figure().update_layout(title='Selecione uma subtarefa')

if __name__=='__main__':
    app.run(debug=True)
