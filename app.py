import dash
from dash import dcc, html, Input, Output, dash_table, State
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import odoo_client # Assume o odoo_client.py modificado anteriormente
import io

# === Constantes de estilo ===
PRIMARY = '#004aad'
ACCENT = '#FFFF00'
DELAYED = '#d62828'
WARNING = '#f57c00'
DONE = 'green'
PLANNED = 'gray' # Cinza para Planejado
BG = '#f9f9f9'
FONT = 'Helvetica, Arial, sans-serif'
LIGHT_BLUE = '#add8e6'

# === Nova função de classificação de status da tarefa ===
def classify_task_status_revised(r, hoje_param):
    # Colunas esperadas em 'r' (linha do DataFrame):
    # 'is_final_state' (bool) - Nova: True se a tarefa está concluída ou cancelada.
    # 'is_actually_delayed' (bool) - Nova: True se não finalizada e prazo passou.
    # 'stage_id_name' (str) - Nome do estágio no Kanban.
    # 'is_open' (bool) - Original: Baseado no 'state' interno do Odoo.
    # 'date_deadline' (datetime) - Prazo da tarefa.

    if r['is_final_state']: # Prioridade 1: Tarefa em estado final
        return 'Concluída' # Trata concluídas e canceladas como "não ativas"

    if r['is_actually_delayed']: # Prioridade 2: Tarefa efetivamente atrasada
        return 'Atrasada'

    stage_name = str(r.get('stage_id_name', '')).lower() # Nome do estágio, normalizado

    # Palavras-chave para estágios (ajuste conforme os nomes reais no seu Odoo)
    # Estas listas ajudam a interpretar o significado do estágio Kanban.
    planned_stage_keywords = [
        'planejad', 'a fazer', 'to do', 'backlog', 'novo',
        'pendente', 'aguardando', 'programada', 'em espera', 'aprovad' # 'aprovad' pode significar pronto para iniciar = Planejada
    ]
    inprogress_stage_keywords = [
        'em andamento', 'em progresso', 'fazendo', 'in progress',
        'desenvolvimento', 'em execução', 'trabalhando'
    ]

    # Prioridade 3: Estágio Kanban indica "Planejada" explicitamente
    if any(keyword in stage_name for keyword in planned_stage_keywords):
        return 'Planejada'

    # Prioridade 4: Estágio Kanban indica "Em Andamento" explicitamente
    if any(keyword in stage_name for keyword in inprogress_stage_keywords):
        return 'Em Andamento'

    # Prioridade 5: Baseado no 'state' interno ('is_open') se o estágio não foi conclusivo
    # 'is_open' é True se state for '01_in_progress', '02_changes_requested', '03_approved'
    # Se '03_approved' NÃO estiver em planned_stage_keywords, pode ser interpretado como Em Andamento aqui.
    if r.get('is_open', False):
        return 'Em Andamento'

    # Prioridade 6: Fallback para "Planejada" (baseado em prazo futuro ou ausência de prazo)
    # Se a tarefa não foi classificada como 'is_open' (pelo state interno) e não se encaixou acima.
    # Se ainda ambíguo (ex: prazo passou mas não foi pega por 'is_actually_delayed')
    # Mais seguro retornar 'Planejada' para evitar falsos "Em Andamento".
    deadline = r.get('date_deadline') # Já deve ser datetime ou NaT
    if (pd.notna(deadline) and deadline >= hoje_param) or pd.isna(deadline):
        return 'Planejada'

    # Default final: Se ainda ambíguo (ex: prazo passou mas não foi pega por 'is_actually_delayed')
    # Isso é improvável se a lógica anterior estiver correta.
    # Mais seguro retornar 'Planejada' para evitar falsos "Em Andamento".
    return 'Planejada'

# === Carrega e prepara dados (MODIFICADO) ===
def load_and_prepare_data():
    df_projects = odoo_client.get_projects()
    df_tasks = odoo_client.get_tasks()
    hoje = pd.Timestamp.now().normalize()

    if df_projects.empty and df_tasks.empty:
        print("ATENÇÃO: Não foi possível carregar dados de projetos nem de tarefas do Odoo.")
        cols_projects = ['id', 'name', 'date_start', 'date', 'user_id', 'task_count', 'open_task_count', 'tag_ids', 'department']
        cols_tasks = ['id', 'name', 'create_date', 'date_deadline', 'date_end', 'partner_id', 'project_id', 'stage_id',
                      'state', 'active', 'parent_id', 'depend_on_ids', 'project_id_id', 'project_id_name',
                      'stage_id_id', 'stage_id_name', 'depend_on_ids_list']
        df_projects = pd.DataFrame(columns=cols_projects)
        df_tasks = pd.DataFrame(columns=cols_tasks)
        for col in ['date_start', 'date']:
            if col in df_projects.columns: df_projects[col] = pd.to_datetime(df_projects[col], errors='coerce')
        for col in ['create_date', 'date_deadline', 'date_end']:
            if col in df_tasks.columns: df_tasks[col] = pd.to_datetime(df_tasks[col], errors='coerce')

    if not df_tasks.empty:
        # Conversão de datas
        for col_date in ['create_date', 'date_deadline', 'date_end']:
            if col_date in df_tasks.columns:
                df_tasks[col_date] = pd.to_datetime(df_tasks[col_date], errors='coerce')
            else:
                df_tasks[col_date] = pd.NaT

        def safe_id_local(v):
            if isinstance(v, (list, tuple)) and v: return v[0]
            if isinstance(v, int): return v
            return None

        if 'parent_id' in df_tasks.columns:
            df_tasks['parent_id_id'] = df_tasks['parent_id'].apply(safe_id_local)
        else:
            df_tasks['parent_id_id'] = None

        if 'depend_on_ids_list' not in df_tasks.columns:
            df_tasks['depend_on_ids_list'] = [[] for _ in range(len(df_tasks))]

        # Coluna 'is_open' (baseada no 'state' interno do Odoo)
        # Usada para ver se o Odoo considera a tarefa "ativa" internamente.
        # '03_approved' pode significar "aprovado para iniciar"; a lógica em classify_task_status_revised
        # dará preferência ao estágio "Planejada" se aplicável.
        open_task_states = ['01_in_progress', '02_changes_requested', '03_approved']
        if 'state' in df_tasks.columns:
            df_tasks['is_open'] = df_tasks['state'].isin(open_task_states)
        else:
            df_tasks['is_open'] = False
            df_tasks['state'] = None # Garantir que a coluna 'state' exista

        # Nova coluna: 'is_final_state' (Concluída ou Cancelada)
        concluida_keywords = ['concluíd', 'done', 'finalizad', 'entregue', 'resolvid', 'fechada']
        cancelada_keywords = ['cancelad', 'arquivada']

        if 'stage_id_name' not in df_tasks.columns: # Garantir que a coluna exista
            df_tasks['stage_id_name'] = ''

        df_tasks['is_final_state'] = df_tasks.apply(lambda r:
            r.get('state') in ['04_done', 'done', '1_done', 'cancel'] or \
            any(keyword in str(r.get('stage_id_name', '')).lower() for keyword in concluida_keywords) or \
            any(keyword in str(r.get('stage_id_name', '')).lower() for keyword in cancelada_keywords), axis=1)

        # Nova coluna: 'is_actually_delayed' (Realmente Atrasada)
        # Uma tarefa está atrasada se não está em estado final E seu prazo passou.
        df_tasks['is_actually_delayed'] = df_tasks.apply(lambda r:
            not r['is_final_state'] and \
            pd.notna(r.get('date_deadline')) and \
            r['date_deadline'] < hoje, axis=1)

        # Cálculo do 'status_cat' usando a nova função revisada
        df_tasks['status_cat'] = df_tasks.apply(lambda row: classify_task_status_revised(row, hoje), axis=1)

        # Recalcular 'is_delayed' para consistência com 'Atrasada' em status_cat, se necessário em outros lugares
        # Ou usar 'is_actually_delayed' diretamente onde for preciso.
        # A coluna 'is_delayed' original não será mais usada para determinar o status do projeto.
        # Vamos manter o nome da coluna 'is_actually_delayed' para clareza nas funções subsequentes.


        # Função recalc (cálculo de datas de início com base em dependências)
        def recalc(df):
            if 'id' not in df.columns or df.empty:
                df['calculated_start'] = pd.NaT
                return df
            df_copy = df.set_index('id').copy()
            def find_start(task_id, seen_tasks=None):
                if seen_tasks is None: seen_tasks = set()
                if task_id in seen_tasks or task_id not in df_copy.index: return pd.NaT
                seen_tasks.add(task_id)
                current_task_record = df_copy.loc[task_id]
                dependencies = current_task_record.get('depend_on_ids_list', [])
                if not dependencies: return current_task_record.get('create_date')
                latest_dependency_end_date = pd.NaT
                for dep_id in dependencies:
                    if dep_id not in df_copy.index: continue
                    dependency_record = df_copy.loc[dep_id]
                    dependency_deadline = dependency_record.get('date_deadline')
                    if pd.isna(dependency_deadline):
                        dependency_start_date = find_start(dep_id, seen_tasks.copy())
                        if pd.notna(dependency_start_date):
                            # Usar uma duração padrão se não houver 'duration_expected_days'
                            duration_days = current_task_record.get('duration_expected_days', 1) # Alterado para 1 dia mínimo
                            if not isinstance(duration_days, (int, float)) or duration_days <= 0:
                                duration_days = 1 # Garantir duração positiva
                            dependency_deadline = dependency_start_date + timedelta(days=duration_days)
                    if pd.notna(dependency_deadline) and \
                       (pd.isna(latest_dependency_end_date) or dependency_deadline > latest_dependency_end_date):
                        latest_dependency_end_date = dependency_deadline
                return (latest_dependency_end_date + timedelta(days=1)) if pd.notna(latest_dependency_end_date) else current_task_record.get('create_date')

            if not df_copy.empty:
                # Garantir que as colunas necessárias para find_start existam
                if 'create_date' not in df_copy.columns: df_copy['create_date'] = pd.NaT
                if 'date_deadline' not in df_copy.columns: df_copy['date_deadline'] = pd.NaT
                if 'depend_on_ids_list' not in df_copy.columns:
                    df_copy['depend_on_ids_list'] = [[] for _ in range(len(df_copy))]

                df_copy['calculated_start'] = [find_start(i) for i in df_copy.index]
            else:
                if 'calculated_start' not in df.columns: df['calculated_start'] = pd.NaT
                # return df # Não retornar aqui, pois o df_copy pode ter sido modificado.
            return df_copy.reset_index() if not df_copy.empty else df
        df_tasks = recalc(df_tasks)

    # Merge com informações do projeto e nomes de dependências (sem alterações aqui)
    if not df_projects.empty and not df_tasks.empty:
        if 'project_id_id' in df_tasks.columns and 'id' in df_projects.columns and \
           'department' in df_projects.columns and 'name' in df_projects.columns:
            df_project_info = df_projects[['id', 'department', 'name']].rename(columns={'name': 'name_project_temp'})
            df_tasks = pd.merge(df_tasks, df_project_info, left_on='project_id_id', right_on='id', how='left', suffixes=('', '_from_proj'))
            if 'department_from_proj' in df_tasks.columns:
                df_tasks['department'] = df_tasks['department_from_proj'].fillna('Sem Departamento')
                df_tasks.drop(columns=['department_from_proj'], inplace=True)
            elif 'department' not in df_tasks.columns: df_tasks['department'] = 'Sem Departamento'
            if 'name_project_temp' in df_tasks.columns:
                df_tasks['name_project'] = df_tasks['name_project_temp'].fillna('Projeto não especificado')
                df_tasks.drop(columns=['name_project_temp'], inplace=True)
            elif 'name_project' not in df_tasks.columns: df_tasks['name_project'] = 'Projeto não especificado'
            if 'id_from_proj' in df_tasks.columns: df_tasks.drop(columns=['id_from_proj'], inplace=True)
        else:
            if 'department' not in df_tasks.columns: df_tasks['department'] = 'Sem Departamento'
            if 'name_project' not in df_tasks.columns: df_tasks['name_project'] = 'Projeto não especificado'
    elif not df_tasks.empty:
        if 'department' not in df_tasks.columns: df_tasks['department'] = 'Sem Departamento'
        if 'name_project' not in df_tasks.columns: df_tasks['name_project'] = 'Projeto não especificado'

    task_names = {}
    if not df_tasks.empty and 'id' in df_tasks.columns and 'name' in df_tasks.columns:
        task_names = df_tasks.set_index('id')['name'].to_dict()

    if not df_tasks.empty and 'depend_on_ids_list' in df_tasks.columns:
        df_tasks['depend_on_names'] = df_tasks['depend_on_ids_list'].apply(
            lambda dep_ids_list: [task_names.get(d_id, f"ID:{d_id}") for d_id in dep_ids_list if isinstance(dep_ids_list, list)] if isinstance(dep_ids_list, list) else []
        )
    elif not df_tasks.empty: # Garantir que a coluna exista mesmo se vazia
        df_tasks['depend_on_names'] = [[] for _ in range(len(df_tasks))]

    # === Nova lógica para calcular "Implicações" ===
    if not df_tasks.empty and 'id' in df_tasks.columns:
        # Criar um dicionário para mapear as implicações
        implications_map = {task_id: [] for task_id in df_tasks['id'].unique()}
        for _, row in df_tasks.iterrows():
            task_id = row['id']
            # Certificar-se de que 'depend_on_ids_list' é uma lista para evitar erros
            if isinstance(row.get('depend_on_ids_list'), list):
                for dep_id in row['depend_on_ids_list']:
                    if dep_id in implications_map:
                        implications_map[dep_id].append(task_id)

        # Adicionar a coluna 'implications_ids'
        df_tasks['implications_ids'] = df_tasks['id'].map(implications_map)
        # Converter os IDs das implicações em nomes para exibição
        df_tasks['implications_names'] = df_tasks['implications_ids'].apply(
            lambda imp_ids_list: [task_names.get(i_id, f"ID:{i_id}") for i_id in imp_ids_list if isinstance(imp_ids_list, list)] if isinstance(imp_ids_list, list) else []
        )
    else:
        df_tasks['implications_ids'] = [[] for _ in range(len(df_tasks))]
        df_tasks['implications_names'] = [[] for _ in range(len(df_tasks))]
    # === Fim da nova lógica ===

    return df_projects.to_json(date_format='iso', orient='split'), \
           df_tasks.to_json(date_format='iso', orient='split')


# === Status geral do projeto (MODIFICADO) ===
def get_project_overall_status(project_row_input, project_tasks_df_input, project_calculated_end_date=None):
    hoje = pd.Timestamp.now().normalize()
    project_date_start_odoo = pd.to_datetime(project_row_input.get('date_start'), errors='coerce')
    project_date_end_odoo = pd.to_datetime(project_row_input.get('date'), errors='coerce')
    effective_project_end_date = project_calculated_end_date
    if pd.isna(effective_project_end_date): effective_project_end_date = project_date_end_odoo

    has_tasks = not project_tasks_df_input.empty
    project_has_any_delayed_task = False
    project_has_any_active_task = False
    project_all_tasks_are_done = True
    project_only_has_planned_tasks = False

    if has_tasks:
        # Usar a coluna 'is_actually_delayed' que foi calculada com a nova lógica
        if 'is_actually_delayed' in project_tasks_df_input.columns:
            project_has_any_delayed_task = project_tasks_df_input['is_actually_delayed'].any()

        if 'status_cat' in project_tasks_df_input.columns:
            task_statuses = project_tasks_df_input['status_cat']
            # 'Em Risco' não é um status_cat individual, é um status de projeto derivado de tarefas atrasadas.
            active_task_statuses_for_project = ['Em Andamento', 'Atrasada']
            project_has_any_active_task = task_statuses.isin(active_task_statuses_for_project).any()

            project_all_tasks_are_done = (task_statuses == 'Concluída').all() if not task_statuses.empty else True

            # Verifica se SÓ tem tarefas 'Planejada' (e não há ativas ou concluídas)
            if not project_has_any_active_task and not project_all_tasks_are_done:
                    project_only_has_planned_tasks = (task_statuses == 'Planejada').all() if not task_statuses.empty else False
            elif task_statuses.empty : # Se não há tarefas, mas has_tasks é True (DataFrame vazio com colunas)
                    project_only_has_planned_tasks = False # Ou True, dependendo da interpretação. False é mais seguro.
                    project_all_tasks_are_done = True # Sem tarefas, pode ser considerado concluído ou planejado.
        else:
            project_all_tasks_are_done = False
            # Fallback se 'status_cat' não estiver disponível (improvável com a nova lógica)
            if 'is_open' in project_tasks_df_input.columns: # 'is_open' do state interno
                    project_has_any_active_task = project_tasks_df_input['is_open'].any()

    # Lógica de prioridade para status do projeto:
    has_pending_work = project_has_any_active_task or (project_only_has_planned_tasks and has_tasks and not project_all_tasks_are_done)

    # 1. Atrasada (Vermelho) - Se o projeto tem prazo final e este passou, e ainda há trabalho pendente.
    if pd.notna(effective_project_end_date) and effective_project_end_date < hoje and has_pending_work:
        return 'Atrasada'

    # 2. Em Risco (Laranja) - Se o projeto tem QUALQUER tarefa individual atrasada.
    if project_has_any_delayed_task: # Usa 'is_actually_delayed'
        return 'Em Risco'

    # 3. Concluída (Verde) - Se todas as tarefas estão concluídas, ou não há tarefas.
    if project_all_tasks_are_done:
        return 'Concluída'

    # 4. Planejada (Cinza)
    # Se não tem tarefas ativas (Em Andamento, Atrasada), e não está tudo concluído,
    # E (ou não tem tarefas, ou todas as que tem são 'Planejada')
    if (not has_tasks and pd.isna(project_date_start_odoo)) or \
       (not has_tasks and pd.notna(project_date_start_odoo) and project_date_start_odoo > hoje) or \
       (has_tasks and project_only_has_planned_tasks):
        return 'Planejada'

    # 5. Em Andamento (Amarelo)
    if project_has_any_active_task: # Se tem tarefas 'Em Andamento' ou 'Atrasada' (Atrasada já teria virado 'Em Risco' acima, mas mantém aqui para lógica de atividade)
        return 'Em Andamento'

    # 6. Casos de Borda para Planejada ou Em Andamento baseado na data de início do projeto
    if pd.notna(project_date_start_odoo):
        if project_date_start_odoo > hoje and not has_pending_work: # Início futuro e sem trabalho ativo/pendente
            return 'Planejada'
        elif project_date_start_odoo <= hoje and not has_pending_work and not project_all_tasks_are_done : # Já deveria ter começado, sem trabalho ativo mas não concluído (ex: só tarefas planejadas, mas o projeto em si deveria estar "em andamento" por ter iniciado)
              # Se chegou aqui e tem tarefas, e project_only_has_planned_tasks foi False, mas não há active_tasks,
              # é uma situação estranha. Mas se só tem planejadas, o item 4 já pegou.
              # Se já começou e não tem tarefas, o item 4 (sem tarefas com início futuro) ou 3 (sem tarefas = concluído) deveria tratar.
              # Este fallback é para garantir que se o projeto iniciou e não caiu nas outras categorias, ele é 'Em Andamento'.
              return 'Em Andamento'


    return 'Planejada'

def generate_full_gantt(df_sel_tasks, pid, all_projects_df):
    hoje = pd.Timestamp.now().normalize()
    if pid not in all_projects_df['id'].values:
        fig = go.Figure().update_layout(title=f"Projeto com ID {pid} não encontrado.", plot_bgcolor='white', paper_bgcolor=BG)
        return fig
    project_details_row = all_projects_df.loc[all_projects_df['id'] == pid].iloc[0]
    df_tasks_for_gantt = df_sel_tasks.copy()

    for col in ['calculated_start', 'date_deadline', 'status_cat', 'depend_on_ids_list', 'id', 'name', 'parent_id_id', 'project_id_id']:
        if col not in df_tasks_for_gantt.columns:
            if col.endswith('_id') or col == 'id': df_tasks_for_gantt[col] = None
            elif col == 'depend_on_ids_list': df_tasks_for_gantt[col] = [[] for _ in range(len(df_tasks_for_gantt))]
            elif col.startswith('date') or col == 'calculated_start': df_tasks_for_gantt[col] = pd.NaT
            else: df_tasks_for_gantt[col] = 'N/A'

    df_tasks_for_gantt['start'] = pd.to_datetime(df_tasks_for_gantt['calculated_start'], errors='coerce')
    df_tasks_for_gantt['deadline'] = pd.to_datetime(df_tasks_for_gantt['date_deadline'], errors='coerce')
    df_tasks_for_gantt['end'] = df_tasks_for_gantt.apply(
        lambda r: max(r['deadline'], hoje) if (r.get('status_cat')=='Em Andamento' and pd.notna(r.get('deadline')))
        else (r.get('deadline') if pd.notna(r.get('deadline'))
        else (r.get('start') + timedelta(days=1) if pd.notna(r.get('start')) else hoje + timedelta(days=1))),
        axis=1
    ).fillna(df_tasks_for_gantt['start'] + timedelta(days=1) if 'start' in df_tasks_for_gantt.columns and not df_tasks_for_gantt.empty and pd.notna(df_tasks_for_gantt['start'].iloc[0] if not df_tasks_for_gantt['start'].empty else pd.NaT) else hoje + timedelta(days=1) )

    p_start_odoo = pd.to_datetime(project_details_row.get('date_start', None), errors='coerce')
    p_start_from_tasks = pd.NaT
    if not df_tasks_for_gantt.empty and 'start' in df_tasks_for_gantt.columns and df_tasks_for_gantt['start'].notna().any():
        p_start_from_tasks = df_tasks_for_gantt['start'].min()
    if pd.notna(p_start_odoo): p_start = p_start_odoo
    elif pd.notna(p_start_from_tasks): p_start = p_start_from_tasks
    else: p_start = hoje

    p_end_odoo = pd.to_datetime(project_details_row.get('date', None), errors='coerce')
    p_end_from_tasks = pd.NaT
    if not df_tasks_for_gantt.empty and 'deadline' in df_tasks_for_gantt.columns and df_tasks_for_gantt['deadline'].notna().any():
        p_end_from_tasks = df_tasks_for_gantt['deadline'].max()
    if pd.notna(p_end_odoo): p_end = p_end_odoo
    elif pd.notna(p_end_from_tasks): p_end = p_end_from_tasks
    else: p_end = p_start + timedelta(days=1)
    if pd.notna(p_start) and pd.notna(p_end) and p_end < p_start: p_end = p_start + timedelta(days=1)

    project_bar = pd.DataFrame([{
        'id': pid,
        'display_name': project_details_row.get('name', f"Projeto ID: {pid}"),
        'start': p_start, 'end': p_end,
        'status_cat': 'Projeto',
        'depend_on_ids_list': [], 'project_id_id': pid
    }])
    full_df_for_gantt = project_bar.assign(__order=-1)

    if not df_tasks_for_gantt.empty:
        mask_no_deps = df_tasks_for_gantt['depend_on_ids_list'].apply(lambda l: isinstance(l, list) and len(l) == 0)
        if pd.notna(p_start): df_tasks_for_gantt.loc[mask_no_deps, 'start'] = p_start
        df_idx_gantt = df_tasks_for_gantt.set_index('id')
        if not df_idx_gantt.empty:
            df_tasks_for_gantt['depth'] = df_tasks_for_gantt['id'].map(compute_depths(df_idx_gantt)).fillna(0).astype(int)
            df_tasks_for_gantt['display_name'] = df_tasks_for_gantt['depth'].apply(lambda d: '   '*d) + df_tasks_for_gantt['name']
        else:
            df_tasks_for_gantt['depth'] = 0
            df_tasks_for_gantt['display_name'] = df_tasks_for_gantt['name'] if 'name' in df_tasks_for_gantt else "Tarefa sem nome"
        tree_gantt = {}
        if 'id' in df_tasks_for_gantt.columns:
            tree_gantt = {tid: [] for tid in df_tasks_for_gantt['id']}
            if not df_idx_gantt.empty and 'parent_id_id' in df_idx_gantt.columns:
                for task_id, task_row in df_idx_gantt.iterrows():
                    parent_id = task_row.get('parent_id_id')
                    if pd.notna(parent_id) and parent_id in tree_gantt:
                        tree_gantt[parent_id].append(task_id)
        order_gantt = []
        def trav_gantt(tid):
            order_gantt.append(tid)
            children_to_sort = tree_gantt.get(tid, [])
            if not df_idx_gantt.empty and 'start' in df_idx_gantt.columns:
                children = sorted(children_to_sort, key=lambda i: (df_idx_gantt.at[i, 'start'] if i in df_idx_gantt.index and pd.notna(df_idx_gantt.at[i, 'start']) else pd.Timestamp.min))
            else: children = children_to_sort
            for ch in children: trav_gantt(ch)
        all_children = {child for children_list in tree_gantt.values() for child in children_list}
        roots = []
        if not df_idx_gantt.empty and 'project_id_id' in df_idx_gantt.columns:
            roots = [i for i in tree_gantt if i not in all_children and (i in df_idx_gantt.index and df_idx_gantt.at[i, 'project_id_id'] == pid)]
        elif tree_gantt: roots = [i for i in tree_gantt if i not in all_children]
        if not df_idx_gantt.empty and 'start' in df_idx_gantt.columns:
            roots = sorted(roots, key=lambda i: (df_idx_gantt.at[i, 'start'] if i in df_idx_gantt.index and pd.notna(df_idx_gantt.at[i, 'start']) else pd.Timestamp.min))
        for r_root in roots: trav_gantt(r_root)
        if order_gantt and 'id' in df_tasks_for_gantt.columns:
            df_tasks_for_gantt['__order'] = df_tasks_for_gantt['id'].apply(lambda i: order_gantt.index(i) if i in order_gantt else float('inf'))
            df_tasks_for_gantt = df_tasks_for_gantt[df_tasks_for_gantt['__order'] != float('inf')]
        elif not df_tasks_for_gantt.empty:
            df_tasks_for_gantt['__order'] = range(len(df_tasks_for_gantt))
        full_df_for_gantt = pd.concat([project_bar.assign(__order=-1), df_tasks_for_gantt], ignore_index=True).sort_values('__order')

    fig = px.timeline(
        full_df_for_gantt, x_start='start', x_end='end', y='display_name', color='status_cat',
        color_discrete_map={'Concluída': DONE, 'Em Andamento': ACCENT, 'Atrasada': DELAYED, 'Planejada': PLANNED, 'Em Risco': WARNING, 'Projeto': PRIMARY},
        labels={'status_cat': 'Legenda'}
    )
    fig.update_layout(
        yaxis={'autorange': 'reversed'},
        yaxis_title="Nome dos Projetos/Tarefas",
        plot_bgcolor='white',
        paper_bgcolor=BG,
        margin=dict(t=50),
        xaxis=dict(tickformat="%d/%m/%Y", dtick="M1", ticklabelmode="period")
    )
    if 'display_name' in full_df_for_gantt.columns and not full_df_for_gantt['display_name'].empty:
        fig.update_yaxes(categoryorder='array', categoryarray=full_df_for_gantt['display_name'].tolist())

    if not df_tasks_for_gantt.empty:
        coord_map = {r['id']: (r['end'], r['display_name']) for _, r in full_df_for_gantt.iterrows() if pd.notna(r.get('id')) and pd.notna(r.get('end')) and pd.notna(r.get('display_name')) and r.get('id') != pid}
        for _, r_task in full_df_for_gantt.iterrows():
            if r_task.get('id') == pid: continue
            if pd.notna(r_task.get('start')) and pd.notna(r_task.get('display_name')) and 'depend_on_ids_list' in r_task:
                for dep_id in r_task.get('depend_on_ids_list', []):
                    if dep_id in coord_map:
                        x0, y0 = coord_map[dep_id]
                        fig.add_annotation(x=r_task['start'], y=r_task['display_name'], ax=x0, ay=y0, xref='x', yref='y', axref='x', ayref='y', showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=1.5, arrowcolor='#666')

        if 'tree_gantt' in locals() and tree_gantt:
            for parent_id, children_ids in tree_gantt.items():
                if children_ids and parent_id in full_df_for_gantt['id'].values:
                    parent_row_df = full_df_for_gantt[full_df_for_gantt['id'] == parent_id]
                    if not parent_row_df.empty:
                        parent_row = parent_row_df.iloc[0]
                        if pd.notna(parent_row.get('start')) and pd.notna(parent_row.get('end')) and pd.notna(parent_row.get('display_name')):
                            fig.add_shape(type='line', x0=parent_row['start'], x1=parent_row['end'], y0=parent_row['display_name'], y1=parent_row['display_name'], xref='x', yref='y', line=dict(color='black', width=3))

    # ***** INÍCIO DA MODIFICAÇÃO *****
    # Adiciona um trace invisível para a legenda da "Tarefa Pai (linha preta)"
    fig.add_trace(go.Scatter(
        x=[None],  # Sem pontos de dados reais
        y=[None],
        mode='lines',
        line=dict(color='black', width=3),
        name='Tarefa Pai (linha preta)', # Texto da legenda
        showlegend=True
    ))
    # ***** FIM DA MODIFICAÇÃO *****

    fig.add_shape(type='line', x0=hoje, x1=hoje, y0=0, y1=1, xref='x', yref='paper', line_dash='dash', line_color='green')
    fig.add_annotation(x=hoje, y=1, xref='x', yref='paper', text='Hoje', showarrow=False, yanchor='bottom', align='right')

    return fig

def compute_depths(df_indexed_tasks):
    depth_dict = {}
    if df_indexed_tasks.empty or 'parent_id_id' not in df_indexed_tasks.columns or not df_indexed_tasks.index.name == 'id':
        return pd.Series({idx: 0 for idx in df_indexed_tasks.index} if not df_indexed_tasks.empty and df_indexed_tasks.index.name == 'id' else {})
    def get_depth_recursive(task_id):
        if task_id in depth_dict: return depth_dict[task_id]
        parent_id = df_indexed_tasks.loc[task_id, 'parent_id_id']
        if pd.isna(parent_id) or parent_id not in df_indexed_tasks.index:
            depth_dict[task_id] = 0
            return 0
        depth = 1 + get_depth_recursive(parent_id)
        depth_dict[task_id] = depth
        return depth
    for tid in df_indexed_tasks.index:
        if tid not in depth_dict: get_depth_recursive(tid)
    return pd.Series({idx: depth_dict.get(idx, 0) for idx in df_indexed_tasks.index})

def generate_dept_gantt(all_tasks_df, selected_projects_df, show_tasks=False):
    if selected_projects_df.empty:
        fig = go.Figure().update_layout(title='Nenhum projeto para o departamento selecionado', plot_bgcolor='white', paper_bgcolor=BG)
        return fig
    hoje = pd.Timestamp.now().normalize()
    gantt_data_list = []
    overall_order_counter = 0

    if 'date_deadline' in all_tasks_df.columns: all_tasks_df['date_deadline'] = pd.to_datetime(all_tasks_df['date_deadline'], errors='coerce')
    else: all_tasks_df['date_deadline'] = pd.NaT
    if 'calculated_start' in all_tasks_df.columns: all_tasks_df['start_task'] = pd.to_datetime(all_tasks_df['calculated_start'], errors='coerce')
    else: all_tasks_df['start_task'] = pd.NaT

    for _, project_row in selected_projects_df.iterrows():
        project_id = project_row['id']
        project_name = project_row.get('name', f"Projeto ID {project_id}")
        current_project_tasks = pd.DataFrame()
        if 'project_id_id' in all_tasks_df.columns and not all_tasks_df.empty:
            current_project_tasks = all_tasks_df[all_tasks_df['project_id_id'] == project_id].copy()

        p_start_odoo_proj = pd.to_datetime(project_row.get('date_start', None), errors='coerce')
        p_start_from_tasks_proj = pd.NaT
        if not current_project_tasks.empty and 'start_task' in current_project_tasks.columns and current_project_tasks['start_task'].notna().any():
            p_start_from_tasks_proj = current_project_tasks['start_task'].min()
        if pd.notna(p_start_odoo_proj): p_start_proj = p_start_odoo_proj
        elif pd.notna(p_start_from_tasks_proj): p_start_proj = p_start_from_tasks_proj
        else: p_start_proj = hoje

        p_end_odoo_proj = pd.to_datetime(project_row.get('date', None), errors='coerce')
        p_end_from_tasks_proj = pd.NaT
        if not current_project_tasks.empty and 'date_deadline' in current_project_tasks.columns and current_project_tasks['date_deadline'].notna().any():
            p_end_from_tasks_proj = current_project_tasks['date_deadline'].max()

        if pd.notna(p_end_odoo_proj): p_end_proj = p_end_odoo_proj
        elif pd.notna(p_end_from_tasks_proj): p_end_proj = p_end_from_tasks_proj
        else: p_end_proj = p_start_proj + timedelta(days=1)
        if pd.notna(p_start_proj) and pd.notna(p_end_proj) and p_end_proj < p_start_proj: p_end_proj = p_start_proj + timedelta(days=1)

        project_status_val = get_project_overall_status(project_row, current_project_tasks, p_end_proj)
        project_bar_data = {'id': f'proj_{project_id}', 'display_name': project_name, 'start': p_start_proj, 'end': p_end_proj, 'status_cat': project_status_val, 'depend_on_ids_list': [], 'project_id_id': project_id, '__overall_order': overall_order_counter}
        gantt_data_list.append(pd.DataFrame([project_bar_data]))
        overall_order_counter += 1

        if show_tasks and not current_project_tasks.empty:
            tasks_to_display = current_project_tasks.copy()
            tasks_to_display.rename(columns={'start_task': 'start', 'date_deadline': 'deadline'}, inplace=True)
            for col in ['depend_on_ids_list', 'id', 'name', 'parent_id_id', 'project_id_id', 'status_cat', 'start', 'deadline']:
                if col not in tasks_to_display.columns:
                    if col.endswith('_id') or col == 'id': tasks_to_display[col] = None
                    elif col == 'depend_on_ids_list': tasks_to_display[col] = [[] for _ in range(len(tasks_to_display))]
                    elif col.startswith('date') or col == 'start' or col == 'deadline': tasks_to_display[col] = pd.NaT
                    else: tasks_to_display[col] = 'N/A'
            tasks_to_display['end'] = tasks_to_display.apply(lambda r: max(r['deadline'], hoje) if (r.get('status_cat')=='Em Andamento' and pd.notna(r.get('deadline'))) else (r.get('deadline') if pd.notna(r.get('deadline')) else (r.get('start') + timedelta(days=1) if pd.notna(r.get('start')) else hoje + timedelta(days=1))), axis=1).fillna(tasks_to_display['start'] + timedelta(days=1) if 'start' in tasks_to_display.columns and not tasks_to_display.empty and pd.notna(tasks_to_display['start'].iloc[0] if not tasks_to_display['start'].empty else pd.NaT) else hoje + timedelta(days=1) )
            df_idx_dept = tasks_to_display.set_index('id') if 'id' in tasks_to_display.columns and not tasks_to_display.empty else pd.DataFrame()
            if not df_idx_dept.empty:
                tasks_to_display['depth'] = tasks_to_display['id'].map(compute_depths(df_idx_dept)).fillna(0).astype(int)
                tasks_to_display['display_name'] = tasks_to_display['depth'].apply(lambda d: '   '*d) + tasks_to_display['name']
            else:
                tasks_to_display['depth'] = 0
                tasks_to_display['display_name'] = tasks_to_display['name'] if 'name' in tasks_to_display else "Tarefa"
            tasks_to_display['__overall_order'] = tasks_to_display.reset_index().index + overall_order_counter
            gantt_data_list.append(tasks_to_display)
            overall_order_counter += len(tasks_to_display)

    if not gantt_data_list:
        fig = go.Figure().update_layout(title='Nenhum dado para exibir no Gantt do departamento.', plot_bgcolor='white', paper_bgcolor=BG)
        return fig
    full_gantt_data_dept = pd.concat(gantt_data_list, ignore_index=True)
    full_gantt_data_dept = full_gantt_data_dept.sort_values('__overall_order').reset_index(drop=True)
    fig = px.timeline(full_gantt_data_dept, x_start='start', x_end='end', y='display_name', color='status_cat', color_discrete_map={'Concluída': DONE, 'Em Andamento': ACCENT, 'Atrasada': DELAYED, 'Planejada': PLANNED, 'Em Risco': WARNING, 'Tarefa-Pai': "-"}, labels={'status_cat': 'Legenda'}) # Note: 'Tarefa-Pai': "-" might not render a black line directly in legend.
    fig.update_layout(
        yaxis={'autorange': 'reversed'},
        yaxis_title="Nome dos Projetos/Tarefas",
        plot_bgcolor='white',
        paper_bgcolor=BG,
        margin=dict(t=50),
        xaxis=dict(tickformat="%d/%m/%Y", dtick="M1", ticklabelmode="period")
    )
    if 'display_name' in full_gantt_data_dept.columns and not full_gantt_data_dept['display_name'].empty:
        fig.update_yaxes(categoryorder='array', categoryarray=full_gantt_data_dept['display_name'].tolist())
    fig.add_shape(type='line', x0=hoje, x1=hoje, y0=0, y1=1, xref='x', yref='paper', line_dash='dash', line_color='green')
    fig.add_annotation(x=hoje, y=1, xref='x', yref='paper', text='Hoje', showarrow=False, yanchor='bottom', align='right')
    return fig

def compute_depths(df_indexed_tasks):
    depth_dict = {}
    if df_indexed_tasks.empty or 'parent_id_id' not in df_indexed_tasks.columns or not df_indexed_tasks.index.name == 'id':
        return pd.Series({idx: 0 for idx in df_indexed_tasks.index} if not df_indexed_tasks.empty and df_indexed_tasks.index.name == 'id' else {})
    def get_depth_recursive(task_id):
        if task_id in depth_dict: return depth_dict[task_id]
        parent_id = df_indexed_tasks.loc[task_id, 'parent_id_id']
        if pd.isna(parent_id) or parent_id not in df_indexed_tasks.index:
            depth_dict[task_id] = 0
            return 0
        depth = 1 + get_depth_recursive(parent_id)
        depth_dict[task_id] = depth
        return depth
    for tid in df_indexed_tasks.index:
        if tid not in depth_dict: get_depth_recursive(tid)
    return pd.Series({idx: depth_dict.get(idx, 0) for idx in df_indexed_tasks.index})

app = dash.Dash(__name__, suppress_callback_exceptions=True)
layout_style = {'fontFamily': FONT, 'backgroundColor': BG, 'padding': '20px'}
app.layout = html.Div(style=layout_style, children=[
    dcc.Interval(id='interval-component', interval=120*1000, n_intervals=0),
    dcc.Store(id='stored-projects'), dcc.Store(id='stored-tasks'),
    html.H1('Dashboard DAC Engenharia', style={'color':PRIMARY,'textAlign':'center', 'marginBottom':'20px'}),
    dcc.Tabs(id='tabs', value='tab-summary', children=[
        dcc.Tab(label='Resumo', value='tab-summary', children=[dcc.Graph(id='summary-graph')], style={'padding':'15px'}, selected_style={'padding':'15px'}),
        dcc.Tab(label='Cronograma', value='tab-gantt', children=[
            html.Div(style={'display':'flex','gap':'15px','marginBottom':'20px', 'alignItems':'flex-end'}, children=[
                html.Div(style={'flex':1}, children=[html.Label('Departamento:'), dcc.Dropdown(id='dept-dropdown', placeholder='Selecione departamento', style={'width':'100%'})]),
                html.Div(style={'flex':2}, children=[html.Label('Projeto:'), dcc.Dropdown(id='project-dropdown', placeholder='Selecione projeto', style={'width':'100%'})])
            ]),
            dcc.Loading(type="default", children=dcc.Graph(id='full-gantt', style={'height':'700px'})),
            html.Hr(style={'marginTop': '30px', 'marginBottom': '20px'}),
            html.H3('Detalhes das Tarefas do Projeto Selecionado', style={'color': PRIMARY, 'textAlign': 'center', 'marginBottom':'15px'}),
            dash_table.DataTable(
                id='tasks-table',
                columns=[
                    {"name": "Tarefa", "id": "name"}, {"name": "Status", "id": "status_cat"},
                    {"name": "Projeto", "id": "name_project"}, {"name": "Início Calc.", "id": "calculated_start"},
                    {"name": "Prazo", "id": "date_deadline"}, {"name": "Departamento", "id": "department"},
                    {"name": "Dependências", "id": "depend_on_names"}, # Coluna existente
                    {"name": "Implicações", "id": "implications_names"} # Nova coluna
                ],
                filter_action="native", sort_action="native", page_action="native", page_size=10,
                style_table={'overflowX': 'auto', 'minWidth': '100%'},
                style_header={'backgroundColor': PRIMARY, 'color': 'white', 'fontWeight': 'bold', 'textAlign': 'left'},
                style_data={'whiteSpace': 'normal', 'height': 'auto', 'fontSize': '0.9em'},
                style_cell={'textAlign': 'left', 'padding': '8px', 'minWidth': '100px', 'width': '150px', 'maxWidth': '200px'},
                style_data_conditional=[
                    {'if': {'column_id': 'name'}, 'minWidth': '200px', 'width': '250px', 'maxWidth': '300px'},
                    {'if': {'filter_query': '{status_cat} = "Atrasada"'}, 'backgroundColor': '#ffebeb', 'color': DELAYED},
                    {'if': {'filter_query': '{status_cat} = "Em Risco"'}, 'backgroundColor': '#fff3e0', 'color': WARNING},
                ]
            )
        ], style={'padding':'15px'}, selected_style={'padding':'15px'})
    ])
])

@app.callback(
    [Output('stored-projects', 'data'), Output('stored-tasks', 'data')],
    [Input('interval-component', 'n_intervals'),
     Input('tabs', 'value')]
)
def get_data_from_odoo_callback(n_intervals, tab_value):
    return load_and_prepare_data()

@app.callback(Output('dept-dropdown', 'options'), Input('stored-projects', 'data'))
def update_dept_dropdown_options_callback(stored_projects_json):
    if stored_projects_json:
        df_projects_cb = pd.read_json(io.StringIO(stored_projects_json), orient='split')
        if 'department' in df_projects_cb.columns and not df_projects_cb.empty:
            departments = sorted([d for d in df_projects_cb['department'].dropna().unique() if d != 'Sem Departamento'])
            if 'Sem Departamento' in df_projects_cb['department'].unique(): departments.append('Sem Departamento')
            return [{'label': d_opt, 'value': d_opt} for d_opt in departments]
    return []

@app.callback(
    [Output('project-dropdown','options'), Output('project-dropdown','value')],
    [Input('dept-dropdown','value'), Input('stored-projects', 'data')],
    State('project-dropdown','value'))
def update_project_list_callback(dept_val, stored_projects_json, current_project_val):
    if not stored_projects_json: return [], None
    df_projects_cb2 = pd.read_json(io.StringIO(stored_projects_json), orient='split')
    options, new_project_value = [], None
    if 'department' in df_projects_cb2.columns and 'id' in df_projects_cb2.columns and 'name' in df_projects_cb2.columns:
        if dept_val:
            df_filtered_proj = df_projects_cb2[df_projects_cb2['department'] == dept_val]
            options = sorted([{'label': name_opt, 'value': id_opt} for id_opt, name_opt in zip(df_filtered_proj['id'], df_filtered_proj['name'])], key=lambda x: x['label'])
            if current_project_val and any(opt['value'] == current_project_val for opt in options): new_project_value = current_project_val
            else: new_project_value = None
        else:
            options = []
            new_project_value = None
    return options, new_project_value

@app.callback(
    [Output('full-gantt', 'figure'), Output('tasks-table', 'data')],
    [Input('dept-dropdown', 'value'), Input('project-dropdown', 'value'),
     Input('stored-projects', 'data'), Input('stored-tasks', 'data')])
def update_gantt_and_table_callback(dept_val_gantt, pid_val_gantt, stored_projects_json, stored_tasks_json):
    fig_default = go.Figure().update_layout(title='Selecione um departamento ou projeto para visualizar o cronograma.', plot_bgcolor='white', paper_bgcolor=BG, yaxis_visible=False, xaxis_visible=False)
    if not stored_projects_json or not stored_tasks_json: return fig_default, []
    all_projects_cb = pd.DataFrame(); all_tasks_cb = pd.DataFrame()
    try:
        all_projects_cb = pd.read_json(io.StringIO(stored_projects_json), orient='split')
        all_tasks_cb = pd.read_json(io.StringIO(stored_tasks_json), orient='split')
    except ValueError as e:
        print(f"ATENÇÃO: Erro ao ler JSON dos dados armazenados: {e}")
        return fig_default, []
    if 'calculated_start' in all_tasks_cb.columns: all_tasks_cb['calculated_start'] = pd.to_datetime(all_tasks_cb['calculated_start'], errors='coerce')
    if 'date_deadline' in all_tasks_cb.columns: all_tasks_cb['date_deadline'] = pd.to_datetime(all_tasks_cb['date_deadline'], errors='coerce')
    if all_projects_cb.empty: return fig_default.update_layout(title='Dados de projetos não disponíveis ou vazios.'), []
    df_sel_table_cb = pd.DataFrame(); current_fig = fig_default
    if pid_val_gantt:
        df_sel_gantt_tasks_cb = pd.DataFrame(columns=all_tasks_cb.columns)
        if 'project_id_id' in all_tasks_cb.columns and not all_tasks_cb.empty:
            df_sel_gantt_tasks_cb = all_tasks_cb[all_tasks_cb['project_id_id'] == pid_val_gantt].copy()
        df_sel_table_cb = df_sel_gantt_tasks_cb.copy()
        if 'id' in all_projects_cb.columns and pid_val_gantt in all_projects_cb['id'].values: current_fig = generate_full_gantt(df_sel_gantt_tasks_cb, pid_val_gantt, all_projects_cb)
        else: current_fig = fig_default.update_layout(title=f"Projeto ID {pid_val_gantt} não encontrado nos dados carregados.")
    elif dept_val_gantt:
        df_proj_in_dept_cb = pd.DataFrame()
        if 'department' in all_projects_cb.columns:
              df_proj_in_dept_cb = all_projects_cb[all_projects_cb['department'] == dept_val_gantt]

        if df_proj_in_dept_cb.empty: current_fig.update_layout(title=f"Nenhum projeto encontrado para o departamento '{dept_val_gantt}'.", yaxis_visible=False, xaxis_visible=False)
        else:
            if 'project_id_id' in all_tasks_cb.columns and not all_tasks_cb.empty and 'id' in df_proj_in_dept_cb.columns:
                df_sel_table_cb = all_tasks_cb[all_tasks_cb['project_id_id'].isin(df_proj_in_dept_cb['id'])].copy()
            current_fig = generate_dept_gantt(all_tasks_cb, df_proj_in_dept_cb, show_tasks=False)
    table_data_cb = []
    if not df_sel_table_cb.empty:
        # Adicione 'implications_names' aqui para que seja incluída na tabela
        table_cols_display = ["name", "status_cat", "name_project", "calculated_start", "date_deadline", "department", "depend_on_names", "implications_names"]
        df_table_final = df_sel_table_cb.copy()
        for col_tbl in table_cols_display:
            if col_tbl not in df_table_final.columns:
                if col_tbl.endswith('_date') or col_tbl == 'calculated_start': df_table_final[col_tbl] = pd.NaT
                elif col_tbl == 'depend_on_names' or col_tbl == 'implications_names': df_table_final[col_tbl] = [[] for _ in range(len(df_table_final))]
                else: df_table_final[col_tbl] = ''
        df_table_final['calculated_start'] = pd.to_datetime(df_table_final['calculated_start'], errors='coerce').dt.strftime('%d/%m/%Y').fillna('N/D')
        df_table_final['date_deadline'] = pd.to_datetime(df_table_final['date_deadline'], errors='coerce').dt.strftime('%d/%m/%Y').fillna('N/D')
        df_table_final['depend_on_names'] = df_table_final['depend_on_names'].apply(lambda x: ', '.join(x) if isinstance(x, list) and x else ('N/A' if not x or not isinstance(x, list) else str(x)))
        # Formatando a nova coluna 'implications_names'
        df_table_final['implications_names'] = df_table_final['implications_names'].apply(lambda x: ', '.join(x) if isinstance(x, list) and x else ('N/A' if not x or not isinstance(x, list) else str(x)))
        table_data_cb = df_table_final[table_cols_display].to_dict('records')
    return current_fig, table_data_cb

@app.callback(
    Output('summary-graph','figure'),
    [Input('tabs','value'), Input('stored-projects', 'data'), Input('stored-tasks', 'data')])
def update_summary_callback(tab_val, stored_projects_json, stored_tasks_json):
    fig_empty_summary_cb = go.Figure().update_layout(title='Resumo não disponível.', plot_bgcolor='white', paper_bgcolor=BG, yaxis_visible=False, xaxis_visible=False)
    if tab_val != 'tab-summary': return dash.no_update
    if not stored_projects_json : return fig_empty_summary_cb
    df_projects_sum = pd.DataFrame(); df_tasks_sum = pd.DataFrame()
    try:
        df_projects_sum = pd.read_json(io.StringIO(stored_projects_json), orient='split')
        if stored_tasks_json: df_tasks_sum = pd.read_json(io.StringIO(stored_tasks_json), orient='split')
    except ValueError as e:
        print(f"ATENÇÃO: Erro ao ler JSON dos dados armazenados para resumo: {e}")
        return fig_empty_summary_cb
    if df_projects_sum.empty: return fig_empty_summary_cb.update_layout(title='Nenhum projeto para resumir.')
    df_task_counts_per_project = pd.DataFrame()
    if not df_tasks_sum.empty and 'project_id_id' in df_tasks_sum.columns and 'status_cat' in df_tasks_sum.columns:
        df_task_counts_per_project = df_tasks_sum.groupby(['project_id_id','status_cat']).size().unstack(fill_value=0)
        status_map_for_summary = {'Concluída':'done_tasks', 'Em Andamento':'inprogress_tasks', 'Atrasada':'delayed_tasks_individual', 'Planejada':'planned_tasks', 'Em Risco': 'at_risk_tasks'}
        df_task_counts_per_project = df_task_counts_per_project.rename(columns=status_map_for_summary)
        for col_name in status_map_for_summary.values():
            if col_name not in df_task_counts_per_project: df_task_counts_per_project[col_name] = 0
        task_sum_cols = [col for col in status_map_for_summary.values() if col in df_task_counts_per_project.columns]
        if task_sum_cols : df_task_counts_per_project['total_tasks'] = df_task_counts_per_project[task_sum_cols].sum(axis=1)
        else: df_task_counts_per_project['total_tasks'] = 0 # Handle if no status columns exist
        df_task_counts_per_project = df_task_counts_per_project.reset_index()

    df_summary_merged = pd.DataFrame()
    if 'id' in df_projects_sum.columns and 'department' in df_projects_sum.columns:
        if not df_task_counts_per_project.empty:
              df_summary_merged = pd.merge(df_projects_sum[['id', 'department']], df_task_counts_per_project, left_on='id', right_on='project_id_id', how='left')
        else: # No tasks, just use projects data for department counts
              df_summary_merged = df_projects_sum[['id', 'department']].copy()
              if 'project_id_id' not in df_summary_merged.columns: # Ensure column for consistency if no tasks
                  df_summary_merged['project_id_id'] = df_summary_merged['id']


        task_count_cols_to_fill = list(status_map_for_summary.values()) + ['total_tasks']
        for col in task_count_cols_to_fill:
            if col in df_summary_merged.columns: df_summary_merged[col] = df_summary_merged[col].fillna(0).astype(int)
            else: df_summary_merged[col] = 0
    else:
        print("ATENÇÃO: 'id' ou 'department' faltando em df_projects_sum para resumo.")
        return fig_empty_summary_cb.update_layout(title='Dados de projetos incompletos para resumo.')

    df_summary_by_dept = pd.DataFrame()
    if 'department' in df_summary_merged.columns and not df_summary_merged.empty:
        df_proj_counts_by_dept = df_projects_sum.groupby('department').size().reset_index(name='num_projects')
        sum_cols_for_dept_group = [col for col in task_count_cols_to_fill if col in df_summary_merged.columns]

        if sum_cols_for_dept_group:
            df_grouped_tasks_by_dept = df_summary_merged.groupby('department')[sum_cols_for_dept_group].sum().reset_index()
        else: # No task columns to sum, create empty sums
            df_grouped_tasks_by_dept = pd.DataFrame({'department': df_summary_merged['department'].unique()})
            for col_s in sum_cols_for_dept_group: df_grouped_tasks_by_dept[col_s] = 0 # Will be empty if sum_cols_for_dept_group is empty

        if not df_proj_counts_by_dept.empty:
            df_summary_by_dept = pd.merge(df_proj_counts_by_dept, df_grouped_tasks_by_dept, on='department', how='left').fillna(0)
            # Ensure all numeric columns are int if they were float due to merge/fillna
            for col in df_summary_by_dept.columns:
                if df_summary_by_dept[col].dtype == 'float64':
                    df_summary_by_dept[col] = df_summary_by_dept[col].astype(int)
        elif not df_grouped_tasks_by_dept.empty : # Only task data available, no project counts per se
            df_summary_by_dept = df_grouped_tasks_by_dept
            if 'num_projects' not in df_summary_by_dept.columns: df_summary_by_dept['num_projects'] = 0 # Add num_projects if missing

    if df_summary_by_dept.empty or 'department' not in df_summary_by_dept.columns: return fig_empty_summary_cb.update_layout(title='Não foi possível construir o resumo por departamento.')

    plot_metrics_map = {'num_projects':'Projetos', 'total_tasks':'Total Tarefas', 'inprogress_tasks':'Tarefas em Andamento', 'delayed_tasks_individual':'Tarefas Atrasadas', 'planned_tasks':'Tarefas Planejadas', 'done_tasks':'Tarefas Concluídas'}
    plot_cols = [col for col in plot_metrics_map.keys() if col in df_summary_by_dept.columns]
    if not plot_cols: return fig_empty_summary_cb.update_layout(title='Métricas de resumo não encontradas para plotagem.')

    fig_summary = px.bar(df_summary_by_dept, x='department', y=plot_cols, barmode='group', labels={'department':'Departamento','value':'Quantidade','variable':'Métrica'}, color_discrete_map={'num_projects':PRIMARY, 'total_tasks':LIGHT_BLUE, 'inprogress_tasks':ACCENT, 'delayed_tasks_individual':DELAYED, 'planned_tasks':PLANNED, 'done_tasks':DONE})
    fig_summary.for_each_trace(lambda t: t.update(name=plot_metrics_map.get(t.name, t.name)))
    fig_summary.update_layout(plot_bgcolor='white', paper_bgcolor=BG, legend_title_text='Métricas de Tarefas', xaxis_title='Departamento', yaxis_title='Quantidade')
    return fig_summary

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8050)