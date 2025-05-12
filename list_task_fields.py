import xmlrpc.client
import os

# --- 1) Carrega configurações do ambiente ---
ODOO_HOST     = os.getenv('ODOO_HOST', '192.168.254.14')
ODOO_PORT     = os.getenv('ODOO_PORT', '30062')
ODOO_DB       = os.getenv('ODOO_DB', 'HomologDAC')
ODOO_USER     = os.getenv('ODOO_USER', 'breno.dacengenharia@gmail.com')
ODOO_PASSWORD = os.getenv('ODOO_PASSWORD', 'DAC123@')

# --- 2) Conecta aos endpoints XML-RPC ---
url_base = f'http://{ODOO_HOST}:{ODOO_PORT}'
common   = xmlrpc.client.ServerProxy(f'{url_base}/xmlrpc/2/common')
models   = xmlrpc.client.ServerProxy(f'{url_base}/xmlrpc/2/object')

# --- 3) Autentica e obtém uid ---
uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})

if not uid:
    raise Exception("Falha na autenticação. Verifique usuário/senha/DB.")

# --- 4) Pede todos os campos do modelo project.task ---
fields = models.execute_kw(
    ODOO_DB, uid, ODOO_PASSWORD,
    'project.task', 'fields_get',
    [],  # sem filtros
    {'attributes': ['string', 'type']}  # para ver nome e tipo de cada campo
)

# --- 5) Exibe cada campo ---
print(f"Campos disponíveis em project.task ({len(fields)}):\n")
for name, meta in sorted(fields.items()):
    print(f"- {name:30} ({meta.get('type')}) — {meta.get('string')}")

# Exemplo de saída:
# - name                          (char) — Task Name
# - date_deadline                 (date) — Deadline
# - blocking_ids                  (one2many) — Blocks
# - blocked_ids                   (one2many) — Is Blocked By
# ...
