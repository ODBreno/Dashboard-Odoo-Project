from dotenv import load_dotenv
import os
import odoorpc
import pandas as pd

# Carregar variáveis de ambiente (.env)
load_dotenv()

HOST = os.getenv("ODOO_HOST")
PORT = int(os.getenv("ODOO_PORT"))
DB = os.getenv("ODOO_DB")
USER = os.getenv("ODOO_USER")
PASS = os.getenv("ODOO_PASSWORD")

# Conectar ao Odoo
odoo = odoorpc.ODOO(host=HOST, port=PORT)
odoo.login(DB, USER, PASS)

# Buscar projetos ativos
projects = odoo.env["project.project"].search_read(
    [("active", "=", True)],
    ["id", "name", "date_start", "date", "user_id", "task_count", "open_task_count"]
)
df_projects = pd.DataFrame(projects)

# Ajustar user_id para exibir apenas o nome
if "user_id" in df_projects.columns:
    df_projects["user_id"] = df_projects["user_id"].apply(
        lambda x: x[1] if isinstance(x, list) else x
    )

# Buscar tarefas dos projetos ativos com informações adicionais
tasks = odoo.env["project.task"].search_read(
    [("project_id.active", "=", True)],
    [
        "id", "name", "create_date", "date_deadline", "date_end", "partner_id",  
        "project_id", "stage_id", "state", "active", "parent_id", "depend_on_ids"
    ]
)
df_tasks = pd.DataFrame(tasks)

# Ajustar partner_id para exibir apenas o nome
if "partner_id" in df_tasks.columns:
    df_tasks["partner_id"] = df_tasks["partner_id"].apply(
        lambda x: x[1] if isinstance(x, list) else x
    )

# Extrair projeto
def _extract_id_name(field_value):
    if isinstance(field_value, list) and len(field_value) >= 2:
        return field_value[0], field_value[1]
    return field_value, None

if "project_id" in df_tasks.columns:
    ids_names = df_tasks["project_id"].apply(_extract_id_name)
    df_tasks[["project_id_id", "project_id_name"]] = pd.DataFrame(ids_names.tolist(), index=df_tasks.index)

# Extrair informações do stage_id se disponível
if "stage_id" in df_tasks.columns:
    ids_names = df_tasks["stage_id"].apply(_extract_id_name)
    df_tasks[["stage_id_id", "stage_id_name"]] = pd.DataFrame(ids_names.tolist(), index=df_tasks.index)

# Extrair lista de dependências (depend_on_ids)
if "depend_on_ids" in df_tasks.columns:
    df_tasks["depend_on_ids_list"] = df_tasks["depend_on_ids"].apply(
        lambda v: [x[0] if isinstance(x, (list, tuple)) else x for x in v]
                  if isinstance(v, (list, tuple)) else []
    )
else:
    df_tasks["depend_on_ids_list"] = [[] for _ in range(len(df_tasks))]


def get_projects():
    return df_projects

def get_tasks():
    return df_tasks