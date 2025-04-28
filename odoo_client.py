from dotenv import load_dotenv
import os
import odoorpc

# Carregar variáveis do .env
load_dotenv()

HOST = os.getenv("ODOO_HOST")
PORT = int(os.getenv("ODOO_PORT"))
DB = os.getenv("ODOO_DB")
USER = os.getenv("ODOO_USER")
PASS = os.getenv("ODOO_PASSWORD")

# Conexão
odoo = odoorpc.ODOO(host=HOST, port=PORT)
odoo.login(DB, USER, PASS)

# Buscar projetos ativos
projects = odoo.env["project.project"].search_read(
    [("active", "=", True)],  # só projetos ativos
    ["id", "name", "date_start", "date", "user_id", "task_count", "open_task_count"]
)

tasks = odoo.env["project.task"].search_read(
    [("project_id.active", "=", True)],  # só tarefas de projetos ativos
    ["id", "name", "create_date", "date_deadline", "date_end", "partner_id", "project_id"]
)

# Exibir
for project in projects:
    print(project)

for task in tasks:
    if task["date_deadline"]:
        print(task)


