import dash
from dash import dcc, html, Input, Output, dash_table
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import odoo_client
import io

# === Constantes de estilo ===
PRIMARY = '#004aad'
ACCENT = '#ffc107'
DELAYED = '#d62828'
DONE = 'green'
PLANNED = 'gray'
BG = '#f9f9f9'
FONT = 'Helvetica, Arial, sans-serif'
LIGHT_BLUE = '#add8e6'

# === Carrega e prepara dados ===
def load_and_prepare_data():
    df_projects = odoo_client.get_projects()
    df_tasks = odoo_client.get_tasks()

    df_tasks['date_deadline'] = pd.to_datetime(df_tasks['date_deadline'], errors='coerce')
    df_tasks['create_date'] = pd.to_datetime(df_tasks['create_date'], errors='coerce')

    def safe_id(v):
        if isinstance(v, (list, tuple)) and v:
            return v[0]
        if isinstance(v, int):
            return v
        return None

    def safe_name(v):
        if isinstance(v, (list, tuple)) and len(v) > 1:
            return v[1]
        return None

    for col in ['project_id', 'parent_id']:
        df_tasks[f"{col}_id"] = df_tasks[col].apply(safe_id)
        df_tasks[f"{col}_name"] = df_tasks[col].apply(safe_name)

    df_tasks['depend_on_ids_list'] = df_tasks['depend_on_ids'].apply(
        lambda v: [x[0] if isinstance(x, (list, tuple)) else x for x in v]
                     if isinstance(v, (list, tuple)) else []
    )

    hoje = pd.Timestamp.now().normalize()
    df_tasks['is_open'] = df_tasks['state'].isin([
        '01_in_progress','02_changes_requested','03_approved'
    ])
    df_tasks['is_delayed'] = df_tasks.apply(
        lambda r: r['is_open'] and pd.notna(r['date_deadline']) \
                     and r['date_deadline'] < hoje,
        axis=1
    )

    def classify(r):
        if r['state'] in ['04_done','done','1_done']:
            return 'Concluída'
        if r['is_delayed']:
            return 'Atrasada'
        if r['is_open']:
            return 'Em Andamento'
        return 'Planejada'

    df_tasks['status_cat'] = df_tasks.apply(classify, axis=1)

    def recalc(df):
        df2 = df.set_index('id').copy()
        def find_start(tid, seen=None):
            if seen is None:
                seen = set()
            if tid in seen or tid not in df2.index:
                return pd.NaT
            seen.add(tid)
            rec = df2.loc[tid]
            deps = rec['depend_on_ids_list']
            if not deps:
                return rec['create_date']
            latest = None
            for d in deps:
                if d not in df2.index:
                    continue
                dep = df2.loc[d]
                end = dep['date_deadline']
                if pd.isna(end):
                    start_dep = find_start(d, seen.copy())
                    if pd.notna(start_dep):
                        end = start_dep + timedelta(days=7)
                if pd.notna(end) and (latest is None or end > latest):
                    latest = end
            return (latest + timedelta(days=1)) \
                   if latest is not None else rec['create_date']
        df2['calculated_start'] = [find_start(i) for i in df2.index]
        return df2.reset_index()

    df_tasks = recalc(df_tasks)

    # Adiciona o nome do departamento e do projeto à tarefa
    df_tasks = pd.merge(df_tasks, df_projects[['id', 'department', 'name']],
                        left_on='project_id_id', right_on='id',
                        suffixes=('', '_proj_name'), how='left')
    df_tasks.rename(columns={'department_proj_name': 'department', 'name_proj_name': 'name_project'}, inplace=True)
    
    task_names = df_tasks.set_index('id')['name'].to_dict()
    df_tasks['depend_on_names'] = df_tasks['depend_on_ids_list'].apply(
        lambda dep_ids: [task_names.get(d, f"ID:{d}") for d in dep_ids]
    )

    return df_projects.to_json(date_format='iso', orient='split'), \
           df_tasks.to_json(date_format='iso', orient='split')

def compute_depths(df_indexed):
    depth = {}
    def get_depth(tid):
        pid = df_indexed.at[tid, 'parent_id_id']
        if pd.isna(pid) or pid not in df_indexed.index:
            return 0
        if tid in depth:
            return depth[tid]
        d = 1 + get_depth(pid)
        depth[tid] = d
        return d
    for tid in df_indexed.index:
        get_depth(tid)
    return pd.Series(depth)

# --- Gantt por projeto ---
def generate_full_gantt(df_sel, pid, all_projects):
    if df_sel.empty:
        fig = go.Figure()
        fig.update_layout(
            title='Nenhuma tarefa',
            plot_bgcolor='white',
            paper_bgcolor=BG
        )
        return fig

    df = df_sel.copy()
    hoje = pd.Timestamp.now().normalize()
    df['start'] = pd.to_datetime(df['calculated_start'])
    df['deadline'] = pd.to_datetime(df['date_deadline'])
    df['end'] = df.apply(
        lambda r: max(r['deadline'], hoje) if (
            r['status_cat']=='Em Andamento' and pd.notna(r['deadline'])
        ) else (
            r['deadline'] if pd.notna(r['deadline']) else hoje
        ),
        axis=1
    ).fillna(df['start'] + timedelta(days=1))

    proj = all_projects.loc[all_projects['id']==pid].iloc[0]
    ds = proj.get('date_start', None)
    de = proj.get('date_end', None)
    p_start = pd.to_datetime(ds) if pd.notna(ds) and not isinstance(ds, bool) \
              else df['start'].min() if not df.empty else hoje
    p_end = pd.to_datetime(de) if pd.notna(de) and not isinstance(de, bool) \
              else df['end'].max() if not df.empty else hoje + timedelta(days=1)

    project_bar = pd.DataFrame([{
        'id': pid,
        'display_name': proj['name'],
        'start': p_start,
        'end': p_end,
        'status_cat': 'Projeto',
        'depend_on_ids_list': []
    }])

    mask_no_deps = df['depend_on_ids_list'].apply(
        lambda l: isinstance(l, list) and len(l) == 0
    )
    df.loc[mask_no_deps, 'start'] = p_start


    df_idx = df.set_index('id')
    df['depth'] = df['id'].map(compute_depths(df_idx)).fillna(0).astype(int)
    df['display_name'] = df['depth'].apply(
        lambda d: '   '*d
    ) + df['name']

    tree = {tid: [] for tid in df['id']}
    for _, r in df.iterrows():
        pid_p = r['parent_id_id']
        if pd.notna(pid_p) and pid_p in tree:
            tree[pid_p].append(r['id'])

    order = []
    def trav(tid):
        order.append(tid)
        for ch in sorted(
            tree.get(tid, []),
            key=lambda i: df_idx.at[i, 'start']
        ):
            trav(ch)

    all_children = set()
    for children_list in tree.values():
        all_children.update(children_list)

    roots = [
        i for i in tree.keys()
        if i not in all_children and df_idx.at[i, 'project_id_id'] == pid
    ]
    roots = sorted(roots, key=lambda i: df_idx.at[i, 'start'])
    for rt in roots:
        trav(rt)

    df['__order'] = df['id'].apply(
        lambda i: order.index(i) if i in order else float('inf')
    )
    df = df[df['__order'] != float('inf')]


    full = pd.concat([
        project_bar.assign(__order=-1), df
    ], ignore_index=True).sort_values('__order')

    fig = px.timeline(
        full,
        x_start='start', x_end='end',
        y='display_name',
        color='status_cat',
        color_discrete_map={
            'Concluída': DONE,
            'Em Andamento': ACCENT,
            'Atrasada': DELAYED,
            'Planejada': PLANNED,
            'Projeto': PRIMARY
        },
        labels={'status_cat': 'Legenda'}
    )
    fig.update_layout(
        yaxis={'autorange': 'reversed'},
        plot_bgcolor='white', paper_bgcolor=BG,
        margin=dict(t=50),
        xaxis=dict(
            tickformat="%d/%m/%Y",
            dtick="M1",
            ticklabelmode="period"
        )
    )
    fig.update_yaxes(
        categoryorder='array',
        categoryarray=full['display_name'].tolist()
    )

    coord = {
        r['id']: (r['end'], r['display_name'])
        for _, r in full.iterrows()
    }
    for _, r in full.iterrows():
        for d in r['depend_on_ids_list'] or []:
            if d in coord:
                x0, y0 = coord[d]
                fig.add_annotation(
                    x=r['start'], y=r['display_name'],
                    ax=x0, ay=y0,
                    xref='x', yref='y', axref='x', ayref='y',
                    showarrow=True, arrowhead=3,
                    arrowsize=1.2, arrowwidth=1.5,
                    arrowcolor='#666'
                )

    for tid, children in tree.items():
        if children and tid in full['id'].values:
            row = full[full['id']==tid].iloc[0]
            fig.add_shape(
                type='line',
                x0=row['start'], x1=row['end'],
                y0=row['display_name'], y1=row['display_name'],
                xref='x', yref='y',
                line=dict(color='black', width=3)
            )

    fig.add_shape(
        type='line', x0=hoje, x1=hoje,
        y0=0, y1=1, xref='x', yref='paper',
        line_dash='dash', line_color='green'
    )
    fig.add_annotation(
        x=hoje, y=1, xref='x', yref='paper',
        text='Hoje', showarrow=False,
        yanchor='bottom', align='right'
    )

    return fig

# --- Gantt por departamento ---
def generate_dept_gantt(df_tasks_sel, df_proj_sel):
    if df_tasks_sel.empty:
        fig = go.Figure()
        fig.update_layout(
            title='Nenhuma tarefa para o departamento selecionado',
            plot_bgcolor='white',
            paper_bgcolor=BG
        )
        return fig

    hoje = pd.Timestamp.now().normalize()
    full_gantt_data = pd.DataFrame()
    overall_order_counter = 0

    for _, proj in df_proj_sel.iterrows():
        pid = proj['id']
        project_name = proj['name']

        df_proj_tasks = df_tasks_sel[df_tasks_sel['project_id_id'] == pid].copy()

        ds = proj.get('date_start', None)
        de = proj.get('date_end', None)
        p_start = pd.to_datetime(ds) if pd.notna(ds) and not isinstance(ds, bool) \
                  else df_proj_tasks['calculated_start'].min() if not df_proj_tasks.empty else hoje
        p_end = pd.to_datetime(de) if pd.notna(de) and not isinstance(de, bool) \
                  else df_proj_tasks['date_deadline'].max() if not df_proj_tasks.empty else hoje + timedelta(days=1)

        project_bar = pd.DataFrame([{
            'id': f'proj_{pid}',
            'display_name': project_name,
            'start': p_start,
            'end': p_end,
            'status_cat': 'Projeto',
            'depend_on_ids_list': [],
            'project_id_id': pid
        }])

        if not df_proj_tasks.empty:
            df_proj_tasks['start'] = pd.to_datetime(df_proj_tasks['calculated_start'])
            df_proj_tasks['deadline'] = pd.to_datetime(df_proj_tasks['date_deadline'])
            df_proj_tasks['end'] = df_proj_tasks.apply(
                lambda r: max(r['deadline'], hoje) if (
                    r['status_cat']=='Em Andamento' and pd.notna(r['deadline'])
                ) else (
                    r['deadline'] if pd.notna(r['deadline']) else hoje
                ),
                axis=1
            ).fillna(df_proj_tasks['start'] + timedelta(days=1))

            mask_no_deps_proj = df_proj_tasks['depend_on_ids_list'].apply(
                lambda l: isinstance(l, list) and len(l) == 0
            )
            df_proj_tasks.loc[mask_no_deps_proj, 'start'] = p_start

            df_idx = df_proj_tasks.set_index('id')
            df_proj_tasks['depth'] = df_proj_tasks['id'].map(compute_depths(df_idx)).fillna(0).astype(int)
            df_proj_tasks['display_name'] = df_proj_tasks['depth'].apply(
                lambda d: '   '*d
            ) + df_proj_tasks['name']

            tree = {tid: [] for tid in df_proj_tasks['id']}
            for _, r in df_proj_tasks.iterrows():
                pid_p = r['parent_id_id']
                if pd.notna(pid_p) and pid_p in tree:
                    tree[pid_p].append(r['id'])

            order = []
            def trav(tid):
                order.append(tid)
                for ch in sorted(
                    tree.get(tid, []),
                    key=lambda i: df_idx.at[i, 'start']
                ):
                    trav(ch)

            all_children_in_project = set()
            for children_list in tree.values():
                all_children_in_project.update(children_list)

            project_roots = [
                i for i in df_proj_tasks['id'].unique()
                if i not in all_children_in_project and df_idx.at[i, 'project_id_id'] == pid
            ]
            project_roots = sorted(project_roots, key=lambda i: df_idx.at[i, 'start'])

            for rt in project_roots:
                trav(rt)

            df_proj_tasks['__project_order'] = df_proj_tasks['id'].apply(
                lambda i: order.index(i) if i in order else float('inf')
            )
            df_proj_tasks = df_proj_tasks[df_proj_tasks['__project_order'] != float('inf')]
            df_proj_tasks = df_proj_tasks.sort_values('__project_order').reset_index(drop=True)
            df_proj_tasks['__overall_order'] = df_proj_tasks.index + overall_order_counter + 1
        else:
            df_proj_tasks = pd.DataFrame()

        project_bar['__overall_order'] = overall_order_counter
        overall_order_counter += len(df_proj_tasks) + 1

        if not df_proj_tasks.empty:
            combined_proj_data = pd.concat([project_bar, df_proj_tasks])
        else:
            combined_proj_data = project_bar

        full_gantt_data = pd.concat([full_gantt_data, combined_proj_data], ignore_index=True)

    full_gantt_data = full_gantt_data.sort_values('__overall_order').reset_index(drop=True)

    fig = px.timeline(
        full_gantt_data,
        x_start='start', x_end='end',
        y='display_name',
        color='status_cat',
        color_discrete_map={
            'Concluída': DONE,
            'Em Andamento': ACCENT,
            'Atrasada': DELAYED,
            'Planejada': PLANNED,
            'Projeto': PRIMARY
        },
        labels={'status_cat': 'Legenda'}
    )
    fig.update_layout(
        yaxis={'autorange': 'reversed'},
        plot_bgcolor='white', paper_bgcolor=BG,
        margin=dict(t=50),
        xaxis=dict(
            tickformat="%d/%m/%Y",
            dtick="M1",
            ticklabelmode="period"
        )
    )
    fig.update_yaxes(
        categoryorder='array',
        categoryarray=full_gantt_data['display_name'].tolist()
    )

    for _, proj in df_proj_sel.iterrows():
        pid = proj['id']
        project_specific_data = full_gantt_data[
            (full_gantt_data['project_id_id'] == pid) | (full_gantt_data['id'] == f'proj_{pid}')
        ].copy()

        current_project_tasks_df = df_tasks_sel[df_tasks_sel['project_id_id'] == pid].copy()
        current_project_tree = {tid: [] for tid in current_project_tasks_df['id']}
        for _, r in current_project_tasks_df.iterrows():
            pid_p = r['parent_id_id']
            if pd.notna(pid_p) and pid_p in current_project_tree:
                current_project_tree[pid_p].append(r['id'])

        coord = {
            r['id']: (r['end'], r['display_name'])
            for _, r in project_specific_data.iterrows() if r['id'] != f'proj_{pid}'
        }
        for _, r in project_specific_data.iterrows():
            if r['id'] == f'proj_{pid}':
                continue
            for d in r['depend_on_ids_list'] or []:
                if d in coord:
                    x0, y0 = coord[d]
                    fig.add_annotation(
                        x=r['start'], y=r['display_name'],
                        ax=x0, ay=y0,
                        xref='x', yref='y', axref='x', ayref='y',
                        showarrow=True, arrowhead=3,
                        arrowsize=1.2, arrowwidth=1.5,
                        arrowcolor='#666'
                    )

        for tid, children in current_project_tree.items():
            if children and tid in project_specific_data['id'].values:
                row = project_specific_data[project_specific_data['id'] == tid].iloc[0]
                fig.add_shape(
                    type='line',
                    x0=row['start'], x1=row['end'],
                    y0=row['display_name'], y1=row['display_name'],
                    xref='x', yref='y',
                    line=dict(color='black', width=3)
                )

    fig.add_shape(
        type='line', x0=hoje, x1=hoje,
        y0=0, y1=1, xref='x', yref='paper',
        line_dash='dash', line_color='green'
    )
    fig.add_annotation(
        x=hoje, y=1, xref='x', yref='paper',
        text='Hoje', showarrow=False,
        yanchor='bottom', align='right'
    )
    return fig

# === Layout e callbacks ===

app = dash.Dash(__name__, suppress_callback_exceptions=True)
layout_style = {'fontFamily': FONT, 'backgroundColor': BG, 'padding': 20}
app.layout = html.Div(style=layout_style, children=[
    dcc.Interval(
        id='interval-component',
        interval=60*1000, # em milissegundos, 60 segundos
        n_intervals=0
    ),
    dcc.Store(id='stored-projects'),
    dcc.Store(id='stored-tasks'),

    html.H1('Dashboard DAC Engenharia',
             style={'color':PRIMARY,'textAlign':'center'}),
    dcc.Tabs(id='tabs', value='tab-summary', children=[
        dcc.Tab(label='Resumo', value='tab-summary', children=[
            dcc.Graph(id='summary-graph')
        ], style={'padding':20}),
        dcc.Tab(label='Cronograma', value='tab-gantt', children=[
            html.Div(style={'display':'flex','gap':'10px','marginBottom':'20px'}, children=[
                html.Div(style={'flex':1}, children=[
                    html.Label('Departamento'),
                    dcc.Dropdown(
                        id='dept-dropdown',
                        placeholder='Selecione departamento',
                        style={'width':'100%','height':'40px'}
                    )
                ]),
                html.Div(style={'flex':2}, children=[
                    html.Label('Projeto'),
                    dcc.Dropdown(
                        id='project-dropdown',
                        placeholder='Selecione projeto',
                        style={'width':'100%','height':'40px'}
                    )
                ])
            ]),
            dcc.Graph(id='full-gantt', style={'height':'700px'}),
            html.Hr(style={'margin-top': '30px', 'margin-bottom': '20px'}),
            html.H3('Detalhes das Tarefas', style={'color': PRIMARY, 'textAlign': 'center'}),
            dash_table.DataTable(
                id='tasks-table',
                columns=[
                    {"name": "Tarefa", "id": "name"},
                    {"name": "Status", "id": "status_cat"},
                    {"name": "Projeto", "id": "name_project"}, # Nova coluna de projeto
                    {"name": "Início Calculado", "id": "calculated_start"},
                    {"name": "Prazo", "id": "date_deadline"},
                    {"name": "Departamento", "id": "department"},
                    {"name": "Dependências", "id": "depend_on_names"}
                ],
                filter_action="native",
                sort_action="native",
                page_action="native",
                page_size=15, # Aumentado o número de tarefas por página
                style_table={'overflowX': 'auto'},
                style_header={
                    'backgroundColor': PRIMARY,
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                style_data={
                    'whiteSpace': 'normal',
                    'height': 'auto',
                    'fontSize': '0.85em', # Aumentado o tamanho da fonte da tabela
                    'textAlign': 'center' # Centraliza o texto
                },
                style_cell={ # Garante que todas as células estejam centralizadas
                    'textAlign': 'center'
                },
                style_data_conditional=[
                    {
                        'if': {'filter_query': '{is_delayed} = true'},
                        'backgroundColor': '#ffebeb',
                        'color': DELAYED
                    }
                ]
            )
        ], style={'padding':20})
    ])
])

@app.callback(
    Output('stored-projects', 'data'),
    Output('stored-tasks', 'data'),
    Input('interval-component', 'n_intervals')
)
def get_data_from_odoo(n):
    return load_and_prepare_data()

@app.callback(
    Output('dept-dropdown', 'options'),
    Input('stored-projects', 'data')
)
def update_dept_dropdown_options(stored_projects_json):
    if stored_projects_json:
        df_projects = pd.read_json(io.StringIO(stored_projects_json), orient='split')
        departments = sorted(df_projects['department'].dropna().unique())
        return [{'label': d, 'value': d} for d in departments]
    return []

@app.callback(
    Output('project-dropdown','options'),
    Output('project-dropdown','value'),
    Input('dept-dropdown','value'),
    Input('stored-projects', 'data')
)
def update_project_list(dept, stored_projects_json):
    if not dept or not stored_projects_json:
        return [], None
    df_projects = pd.read_json(io.StringIO(stored_projects_json), orient='split')
    df = df_projects[df_projects['department'] == dept]
    opts = [{'label': n, 'value': i} for i, n in zip(df['id'], df['name'])]
    return opts, None

@app.callback(
    Output('full-gantt', 'figure'),
    Output('tasks-table', 'data'),
    Input('dept-dropdown', 'value'),
    Input('project-dropdown', 'value'),
    Input('stored-projects', 'data'),
    Input('stored-tasks', 'data')
)
def update_gantt_and_table(dept, pid, stored_projects_json, stored_tasks_json):
    if not stored_projects_json or not stored_tasks_json:
        fig = go.Figure()
        fig.update_layout(title='Carregando dados...', plot_bgcolor='white', paper_bgcolor=BG)
        return fig, []

    all_projects = pd.read_json(io.StringIO(stored_projects_json), orient='split')
    all_tasks = pd.read_json(io.StringIO(stored_tasks_json), orient='split')
    
    all_tasks['calculated_start'] = pd.to_datetime(all_tasks['calculated_start'], errors='coerce')
    all_tasks['date_deadline'] = pd.to_datetime(all_tasks['date_deadline'], errors='coerce')

    if pid:
        df_sel_gantt = all_tasks[all_tasks['project_id_id'] == pid]
        df_sel_table = df_sel_gantt.copy()
        
        df_sel_table['calculated_start'] = df_sel_table['calculated_start'].dt.strftime('%d/%m/%Y').fillna('')
        df_sel_table['date_deadline'] = df_sel_table['date_deadline'].dt.strftime('%d/%m/%Y').fillna('')
        df_sel_table['depend_on_names'] = df_sel_table['depend_on_names'].apply(
            lambda x: ', '.join(x) if isinstance(x, list) else ''
        )

        fig = generate_full_gantt(df_sel_gantt, pid, all_projects)
        return fig, df_sel_table[[
            'name', 'status_cat', 'name_project', 'calculated_start', 'date_deadline', 'department', 'depend_on_names', 'is_delayed'
        ]].to_dict('records')
    
    if dept:
        df_proj = all_projects[all_projects['department'] == dept]
        df_sel_gantt = all_tasks[all_tasks['project_id_id'].isin(df_proj['id'])]
        df_sel_table = df_sel_gantt.copy()

        df_sel_table['calculated_start'] = df_sel_table['calculated_start'].dt.strftime('%d/%m/%Y').fillna('')
        df_sel_table['date_deadline'] = df_sel_table['date_deadline'].dt.strftime('%d/%m/%Y').fillna('')
        df_sel_table['depend_on_names'] = df_sel_table['depend_on_names'].apply(
            lambda x: ', '.join(x) if isinstance(x, list) else ''
        )

        fig = generate_dept_gantt(df_sel_gantt, df_proj)
        return fig, df_sel_table[[
            'name', 'status_cat', 'name_project', 'calculated_start', 'date_deadline', 'department', 'depend_on_names', 'is_delayed'
        ]].to_dict('records')
    
    fig = go.Figure()
    fig.update_layout(
        title='Selecione projeto ou departamento para visualizar o cronograma',
        plot_bgcolor='white', paper_bgcolor=BG
    )
    return fig, []

@app.callback(
    Output('summary-graph','figure'),
    Input('tabs','value'),
    Input('stored-projects', 'data'),
    Input('stored-tasks', 'data')
)
def update_summary(tab, stored_projects_json, stored_tasks_json):
    if tab != 'tab-summary' or not stored_projects_json or not stored_tasks_json:
        return dash.no_update

    df_projects = pd.read_json(io.StringIO(stored_projects_json), orient='split')
    df_tasks = pd.read_json(io.StringIO(stored_tasks_json), orient='split')

    df_tc = df_tasks.groupby(['project_id_id','status_cat']).size().unstack(fill_value=0).reset_index()
    df_tc = df_tc.rename(columns={
        'Concluída':'done_tasks', 'Em Andamento':'open_tasks',
        'Atrasada':'delayed_tasks','Planejada':'planned_tasks'
    })
    df_tc['total_tasks'] = df_tc[['done_tasks','open_tasks','delayed_tasks','planned_tasks']].sum(axis=1)
    df_tc = pd.merge(df_tc, df_projects[['id','department']],
                     left_on='project_id_id', right_on='id', how='left')
    df_summary = df_tc.groupby('department')[[
        'done_tasks','open_tasks','delayed_tasks','planned_tasks','total_tasks'
    ]].sum().reset_index()
    df_proj = df_projects.groupby('department').size().reset_index(name='num_projects')
    df_summary = pd.merge(df_proj, df_summary, on='department')
    fig = px.bar(
        df_summary,
        x='department',
        y=['num_projects','total_tasks','open_tasks','delayed_tasks','planned_tasks','done_tasks'],
        barmode='group',
        labels={'department':'Departamento','value':'Quantidade','variable':'Métrica'},
        color_discrete_map={
            'num_projects':PRIMARY,
            'total_tasks':LIGHT_BLUE,
            'open_tasks':ACCENT,
            'delayed_tasks':DELAYED,
            'planned_tasks':PLANNED,
            'done_tasks':DONE
        }
    )
    mapping = {
        'num_projects':'Projetos','total_tasks':'Total de Tarefas',
        'open_tasks':'Em Andamento','delayed_tasks':'Atrasadas',
        'planned_tasks':'Planejadas','done_tasks':'Concluídas'
    }
    for key,name in mapping.items():
        fig.update_traces(selector=lambda t:t.name==key, name=name)
    fig.update_layout(
        plot_bgcolor='white', paper_bgcolor=BG,
        legend_title_text='Métrica',
        xaxis_title='Departamento', yaxis_title='Quantidade'
    )
    return fig

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8050)