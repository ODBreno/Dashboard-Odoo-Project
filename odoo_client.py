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
    ["id", "name", "create_date", "date_deadline", "date_end", "partner_id", 
     "project_id", "stage_id", "state", "active", "parent_id"]  # Adicionado stage_id
)
df_tasks = pd.DataFrame(tasks)

# Ajustar partner_id e extrair projeto
if "partner_id" in df_tasks.columns:
    df_tasks["partner_id"] = df_tasks["partner_id"].apply(
        lambda x: x[1] if isinstance(x, list) else x
    )
if "project_id" in df_tasks.columns:
    df_tasks["project_id_id"] = df_tasks["project_id"].apply(
        lambda x: x[0] if isinstance(x, list) else x
    )
    df_tasks["project_id_name"] = df_tasks["project_id"].apply(
        lambda x: x[1] if isinstance(x, list) else x
    )

# Extrair informações do stage_id se disponível
if "stage_id" in df_tasks.columns:
    df_tasks["stage_id_id"] = df_tasks["stage_id"].apply(
        lambda x: x[0] if isinstance(x, list) else x
    )
    df_tasks["stage_id_name"] = df_tasks["stage_id"].apply(
        lambda x: x[1] if isinstance(x, list) else x
    )

def get_projects():
    return df_projects

def get_tasks():
    return df_tasks