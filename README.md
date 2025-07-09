# Dashboard Odoo Project 📊

Dashboard integrada ao Odoo, desenvolvida para uso interno na DAC Engenharia. Esta aplicação fornece visualizações gerenciais de projetos e tarefas a partir dos dados do ERP Odoo.

## 🌐 Visão Geral

Esta dashboard foi construída com foco na análise e acompanhamento dos projetos cadastrados no Odoo da empresa. Ela está presente em ambos os servidores TrueNAS — ambiente de **homologação** e **produção** — com imagens Docker gerenciadas separadamente por tags.

O código-fonte está disponível em:

🔗 [https://github.com/ODBreno/Dashboard-Odoo-Project](https://github.com/ODBreno/Dashboard-Odoo-Project)

A imagem Docker está publicada no GitHub Container Registry:

📦 `ghcr.io/odbreno/dashboard-odoo`

---

## 🚀 Instalação

### Usando Docker

Execute o container com as variáveis de ambiente do Odoo:

```bash
docker run -d \
  --name dashboard-odoo \
  -e ODOO_HOST=ip_do_odoo \
  -e ODOO_PORT=porta_do_odoo \
  -e ODOO_DB=banco_do_odoo \
  -e ODOO_USER=usuario_do_odoo \
  -e ODOO_PASSWORD=senha_do_usuario \
  -p 8050:8050 \
  ghcr.io/odbreno/dashboard-odoo:latest
```

> 📌 Substitua as informaçöes para as corretas.

---

## ⚙️ Variáveis de Ambiente

A dashboard depende da conexão com o Odoo e espera que as seguintes variáveis estejam configuradas:

| Variável        | Descrição                       |
| --------------- | ------------------------------- |
| `ODOO_HOST`     | IP ou hostname do servidor Odoo |
| `ODOO_PORT`     | Porta de acesso da API do Odoo  |
| `ODOO_DB`       | Nome do banco de dados do Odoo  |
| `ODOO_USER`     | Usuário com permissão de acesso |
| `ODOO_PASSWORD` | Senha do usuário                |

Você também pode criar um arquivo `.env` local com essas variáveis para desenvolvimento:

```env
ODOO_HOST=ip_do_odoo
ODOO_PORT=porta_do_odoo
ODOO_DB=banco_do_odoo
ODOO_USER=usuario_do_odoo
ODOO_PASSWORD=senha_do_usuario
```

---

## 👨‍💼 Desenvolvimento

Para desenvolver localmente, clone o repositório e instale as dependências:

```bash
git clone https://github.com/ODBreno/Dashboard-Odoo-Project.git
cd Dashboard-Odoo-Project

# Crie o arquivo .env conforme as variáveis acima
# Depois, rode a aplicação
python app.py
```

---

## 🔄 Atualizações

Para atualizar a dashboard no TrueNAS:

1. Faça as modificações no repositório.
2. Faça o commit e o push (caso seja colaborador).
3. No TrueNAS, atualize o app e certifique-se de estar usando a tag `latest` para refletir as mudanças.

> ✅ Se não for colaborador, é possível fazer um fork do projeto. No entanto, isso irá alterar o endereço da imagem Docker usada no TrueNAS.

---

## 🛄 Observações

- Produção e homologação usam a **mesma imagem**, diferenciando-se apenas pelas variáveis de ambiente.
- O TrueNAS exige configuração manual das variáveis no app para que a dashboard funcione corretamente.
- Caso deseje sincronizar ambas as versões (homologação e produção), basta editar e salvar a de produção usando as mesmas configurações.


