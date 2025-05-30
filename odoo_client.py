from dotenv import load_dotenv
import os
import odoorpc
import pandas as pd

load_dotenv()

HOST = os.getenv("ODOO_HOST")
PORT = os.getenv("ODOO_PORT", 8069) # Usa 8069 como porta padrão se não definida
DB = os.getenv("ODOO_DB")
USER = os.getenv("ODOO_USER")
PASS = os.getenv("ODOO_PASSWORD")

# Variável global para a instância ODOO, para reutilizar a conexão
_odoo_instance = None

def _connect_and_login():
    """
    Estabelece uma nova conexão com o Odoo e realiza o login.
    Retorna a instância Odoo conectada ou None em caso de falha.
    """
    global _odoo_instance
    try:
        print("INFO: Tentando conectar e logar no Odoo...")
        _odoo_instance = odoorpc.ODOO(host=HOST, protocol='jsonrpc', port=int(PORT), timeout=60)
        _odoo_instance.login(DB, USER, PASS)
        print("INFO: Conexão e login com Odoo bem-sucedidos.")
        return _odoo_instance
    except Exception as e:
        print(f"ATENÇÃO: Falha crítica ao conectar/logar no Odoo: {e}")
        _odoo_instance = None # Garante que não tentaremos usar uma instância falha
        return None

def get_odoo_env():
    """
    Retorna o ambiente 'env' da conexão Odoo.
    Tenta (re)conectar e (re)logar se a conexão não existir ou a sessão estiver inválida.
    """
    global _odoo_instance
    if _odoo_instance is None:
        if not _connect_and_login(): # Tenta conectar na primeira vez ou se _odoo_instance foi resetado
            return None

    try:
        # Tenta uma chamada leve para verificar se a sessão ainda é válida
        _odoo_instance.version() 
        return _odoo_instance.env
    except Exception as e: 
        # Qualquer exceção aqui (RPCError, ConnectionRefusedError, etc.) indica problema.
        print(f"INFO: Sessão Odoo possivelmente inválida ou conexão perdida ({type(e).__name__}: {e}). Tentando relogar...")
        if not _connect_and_login(): # Tenta reconectar e logar
            return None # Falha ao relogar
        # Se o relogin foi bem-sucedido, retorna o novo ambiente
        return _odoo_instance.env if _odoo_instance else None


def execute_odoo_read(model_name, domain, fields, context=None):
    """
    Executa um search_read no Odoo de forma segura, lidando com problemas de sessão.
    Retorna os dados ou uma lista vazia em caso de erro.
    """
    env = get_odoo_env()
    if not env:
        print(f"ATENÇÃO: Não foi possível obter o ambiente Odoo para o modelo {model_name}.")
        return [] 

    try:
        # print(f"INFO: Buscando dados para o modelo {model_name}...") # Descomente para debug detalhado
        data = env[model_name].search_read(domain, fields, context=context or {})
        return data if data else []
    except odoorpc.error.RPCError as e:
        print(f"ATENÇÃO: RPCError ao buscar dados de {model_name}: {getattr(e, 'message', str(e))} (Fault Code: {getattr(e, 'faultCode', 'N/A')})")
        fault_code_str = str(getattr(e, 'faultCode', '')).lower()
        error_message_str = str(getattr(e, 'message', str(e))).lower()
        
        # Condições comuns para erros de sessão/login
        session_errors = ["session", "login", "authent", "zugriff verweigert", "access denied", "login required"]
        
        if any(err_key in fault_code_str for err_key in session_errors) or \
           any(err_key in error_message_str for err_key in session_errors):
            print(f"INFO: Erro de sessão detectado para {model_name}. Invalidando instância para forçar novo login na próxima tentativa.")
            global _odoo_instance
            _odoo_instance = None # Força _connect_and_login() na próxima chamada a get_odoo_env()
        return [] 
    except Exception as e:
        print(f"ATENÇÃO: Erro genérico ao buscar dados de {model_name}: {type(e).__name__} - {e}")
        return []


def _extract_relational_field(value, part='name'):
    """
    Extrai ID ou Nome de um campo relacional do Odoo.
    Odoo retorna [ID, "Nome"] para campos Many2one, ou False se vazio.
    """
    if isinstance(value, list) and len(value) == 2:
        return value[0] if part == 'id' else value[1]
    # Se o campo for False (vazio no Odoo) ou formato inesperado
    return None

def get_projects():
    """Busca e processa os dados de projetos do Odoo."""
    project_data = execute_odoo_read(
        model_name="project.project",
        domain=[("active", "=", True)],
        fields=["id", "name", "date_start", "date", "user_id", "task_count", "open_task_count", "tag_ids"]
    )
    df_projects = pd.DataFrame(project_data)

    if not df_projects.empty:
        if "user_id" in df_projects.columns:
            df_projects["user_id"] = df_projects["user_id"].apply(lambda x: _extract_relational_field(x, 'name'))
        
        tag_data = execute_odoo_read(model_name='project.tags', domain=[], fields=['id', 'name'])
        df_tags = pd.DataFrame(tag_data)
        tag_map = dict(zip(df_tags['id'], df_tags['name'])) if not df_tags.empty else {}

        def map_department(tag_ids_list): # tag_ids_list é uma lista de IDs de tags
            if isinstance(tag_ids_list, (list, tuple)) and tag_ids_list:
                first_tag_id = tag_ids_list[0] 
                return tag_map.get(first_tag_id, 'Sem Departamento')
            return 'Sem Departamento'
        
        if "tag_ids" in df_projects.columns:
            df_projects['department'] = df_projects['tag_ids'].apply(map_department)
        else:
            df_projects['department'] = 'Sem Departamento'
    else: # Garante colunas mínimas se o DataFrame estiver vazio
        expected_cols = ['id', 'name', 'date_start', 'date', 'user_id', 'task_count', 'open_task_count', 'tag_ids', 'department']
        for col in expected_cols:
            if col not in df_projects.columns:
                df_projects[col] = None if col != 'tag_ids' else pd.Series([[] for _ in range(len(df_projects))], dtype='object')
    
    # Assegurar tipos de dados corretos para colunas de data
    for col_date in ['date_start', 'date']:
        if col_date in df_projects.columns:
            df_projects[col_date] = pd.to_datetime(df_projects[col_date], errors='coerce')

    return df_projects

def get_tasks():
    """Busca e processa os dados de tarefas do Odoo."""
    tasks_data = execute_odoo_read(
        model_name="project.task",
        domain=[("project_id.active", "=", True)], # Busca tarefas de projetos ativos
        fields=[
            "id", "name", "create_date", "date_deadline", "date_end", "partner_id",  
            "project_id", "stage_id", "state", "active", "parent_id", "depend_on_ids"
        ]
    )
    df_tasks = pd.DataFrame(tasks_data)

    if not df_tasks.empty:
        if "partner_id" in df_tasks.columns:
            df_tasks["partner_id"] = df_tasks["partner_id"].apply(lambda x: _extract_relational_field(x, 'name'))
        
        if "project_id" in df_tasks.columns:
            df_tasks["project_id_id"] = df_tasks["project_id"].apply(lambda x: _extract_relational_field(x, 'id'))
            df_tasks["project_id_name"] = df_tasks["project_id"].apply(lambda x: _extract_relational_field(x, 'name'))
        else: # Garante as colunas mesmo se project_id não vier
            df_tasks["project_id_id"] = None
            df_tasks["project_id_name"] = None

        if "stage_id" in df_tasks.columns:
            df_tasks["stage_id_id"] = df_tasks["stage_id"].apply(lambda x: _extract_relational_field(x, 'id'))
            df_tasks["stage_id_name"] = df_tasks["stage_id"].apply(lambda x: _extract_relational_field(x, 'name'))
        else:
            df_tasks["stage_id_id"] = None
            df_tasks["stage_id_name"] = None
            
        # parent_id também é [id, name] ou False. Será processado em app.py para 'parent_id_id'
        # Apenas garantimos que a coluna existe se vier do Odoo
        if "parent_id" not in df_tasks.columns:
            df_tasks["parent_id"] = None
            
        if "depend_on_ids" in df_tasks.columns:
            # depend_on_ids é uma lista de IDs de tarefas das quais esta tarefa depende
            df_tasks["depend_on_ids_list"] = df_tasks["depend_on_ids"].apply(
                lambda id_list: id_list if isinstance(id_list, list) else []
            )
        else:
            df_tasks["depend_on_ids_list"] = [[] for _ in range(len(df_tasks))]
    else: # Garante colunas mínimas se o DataFrame estiver vazio
        expected_cols = ['id', 'name', 'create_date', 'date_deadline', 'date_end', 'partner_id', 
                         'project_id', 'stage_id', 'state', 'active', 'parent_id', 'depend_on_ids', 
                         'project_id_id', 'project_id_name', 'stage_id_id', 'stage_id_name', 
                         'depend_on_ids_list']
        for col in expected_cols:
            if col not in df_tasks.columns:
                 df_tasks[col] = None if col != 'depend_on_ids_list' else pd.Series([[] for _ in range(len(df_tasks))], dtype='object')

    # Assegurar tipos de dados corretos para colunas de data
    for col_date in ['create_date', 'date_deadline', 'date_end']:
        if col_date in df_tasks.columns:
            df_tasks[col_date] = pd.to_datetime(df_tasks[col_date], errors='coerce')
            
    return df_tasks