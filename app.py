import dash
from dash import dcc, html, dash_table, Output, Input
import pandas as pd
import datetime

# Mock dos dados - depois vamos puxar do odoo_client
projects = [
    {"id": 1, "name": "Projeto A"},
    {"id": 2, "name": "Projeto B"},
]

tasks = [
    {"id": 101, "name": "Tarefa 1", "date_deadline": "2025-05-10", "project_id": 1},
    {"id": 102, "name": "Tarefa 2", "date_deadline": "2025-05-15", "project_id": 1},
    {"id": 201, "name": "Tarefa 3", "date_deadline": "2025-05-20", "project_id": 2},
]

# Transformar em DataFrame
tasks_df = pd.DataFrame(tasks)

# Iniciar Dash
app = dash.Dash(__name__)

app.layout = html.Div([
    html.H1("Dashboard de Projetos"),
    
    # Dropdown para selecionar projeto
    dcc.Dropdown(
        id="project-dropdown",
        options=[{"label": p["name"], "value": p["id"]} for p in projects],
        value=projects[0]["id"],
        clearable=False,
    ),
    
    html.Br(),
    
    # Tabela de tarefas
    dash_table.DataTable(
        id="task-table",
        columns=[
            {"name": "Nome da Tarefa", "id": "name"},
            {"name": "Prazo", "id": "date_deadline"},
        ],
        style_cell={'textAlign': 'left'},
    )
])

# Callback para atualizar a tabela
@app.callback(
    Output("task-table", "data"),
    Input("project-dropdown", "value")
)
def update_table(selected_project_id):
    filtered = tasks_df[tasks_df["project_id"] == selected_project_id]
    return filtered[["name", "date_deadline"]].to_dict("records")

# Rodar
if __name__ == "__main__":
    app.run(debug=True)
