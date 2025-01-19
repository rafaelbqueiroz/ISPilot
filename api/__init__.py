import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from openai import AssistantEventHandler
from typing_extensions import override
import requests
from flask import Flask, request, jsonify, render_template, send_from_directory, redirect
import threading
import datetime
import re

# Carrega variáveis de ambiente
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MIKWEB_API_TOKEN = os.getenv("MIKWEB_API_TOKEN")
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# Inicializa o cliente da OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Inicializa o Flask
app = Flask(__name__, static_folder='static')

# Simple in-memory cache for threads (for demonstration purposes)
thread_cache = {}
thread_lock = threading.Lock()

# Log storage (in memory for this example)
logs = []

def is_cpf_valid(cpf):
    cpf = "".join(filter(str.isdigit, cpf))
    if len(cpf) != 11:
        return False
    if cpf in [s * 11 for s in '0123456789']:
        return False
    for i in range(10, 12):
        value = sum([int(cpf[p]) * (i + 1 - p) for p in range(i)]) % 11
        if int(cpf[i]) != (value if value < 10 else 0):
            return False
    return True

@tool
def send_whatsapp_message(to: str, body: str, typing_time: int = 0, quoted: str = None, ephemeral: int = None, edit: str = None, no_link_preview: bool = False, mentions: list = None, view_once: bool = False) -> str:
    """
    Envia uma mensagem de texto para um número ou grupo do WhatsApp.

    Args:
        to: Número de telefone ou ID do chat do WhatsApp para o qual a mensagem será enviada (string).
        body: O corpo (texto) da mensagem a ser enviada (string).
        typing_time: Tempo em segundos para simular digitação (inteiro, opcional, padrão 0).
        quoted: ID da mensagem a ser citada (string, opcional).
        ephemeral: Tempo em segundos para a mensagem desaparecer (inteiro, opcional).
        edit: ID da mensagem a ser editada (string, opcional).
        no_link_preview: Se deve enviar links sem a preview (booleano, opcional, padrão False).
        mentions: Lista de números de telefone para mencionar na mensagem (lista de strings, opcional).
        view_once: Indica se a mensagem deve ser visualizada apenas uma vez (booleano, opcional, padrão False).

    Returns:
        Um texto com a resposta da API da Whapi ou uma mensagem de erro (string).
    """
    url = "https://gate.whapi.cloud/messages/text"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHAPI_TOKEN}"
    }
    payload = {
        "to": to,
        "body": body,
        "typing_time": typing_time,
        "no_link_preview": no_link_preview,
        "view_once": view_once
    }
    if quoted:
        payload["quoted"] = quoted
    if ephemeral:
        payload["ephemeral"] = ephemeral
    if edit:
        payload["edit"] = edit
    if mentions:
        payload["mentions"] = mentions
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        log_message(f"send_whatsapp_message: Mensagem enviada para {to} com sucesso, corpo: {body}", level="INFO", response=response.json())
        return json.dumps(response.json(), indent=4, ensure_ascii=False)

    except requests.exceptions.RequestException as e:
        log_message(f"send_whatsapp_message: Erro ao contatar a API da Whapi: {str(e)}, corpo: {body}", level="ERROR")
        return f"Erro ao contatar a API da Whapi: {str(e)}"
        
@tool
def web_total_workflow(cpf: str, resumo: str, objetivo: str, acaoAPI: str) -> str:
    """
    Envia dados do cliente para o workflow do n8n e recebe informações para diagnóstico e ações.

    Essa ferramenta recebe o CPF do cliente, um resumo da interação com o cliente,
    o objetivo da chamada e a ação da API solicitada. Em seguida, envia esses dados
    para o workflow do n8n, que realiza uma série de verificações e ações,
    retornando ao final a resposta do workflow.

    Args:
        cpf: CPF do cliente (string)
        resumo: Resumo da interação com o cliente (string)
        objetivo: Objetivo da chamada API (string)
        acaoAPI: Ação da API solicitada (string, ex: "desbloqueio", "pagamento", "tecnico")

    Returns:
        Um texto com a resposta do workflow n8n (string).
    """
    url = "https://primary-production-ea8a.up.railway.app/webhook/recebe-dados-da-zaia"
    headers = {'Content-type': 'application/json'}
    payload = {
       "CPF": cpf,
       "Resumo": resumo,
       "Objetivo": objetivo,
       "AcaoAPI": acaoAPI
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)
        log_message(f"web_total_workflow: Envio bem-sucedido para o workflow do n8n, payload: {payload}", level="INFO", response=response.json())
        data = response.json()
        
        # Check if 'faturas' key is present and not None
        if data and 'faturas' in data and data['faturas']:
            faturas_data = data['faturas']

            # If it's an error
            if 'erro' in faturas_data:
                log_message(f"web_total_workflow: Erro ao processar o workflow: {faturas_data['erro']}", level="ERROR")
                return f"Ocorreu um erro no workflow: {faturas_data['erro']}"

            # If it's a success message with customer details
            if 'mensagemCliente' in faturas_data:
                mensagem_cliente = faturas_data['mensagemCliente']
                faturas_detalhes = faturas_data.get('faturasDetalhes', 'Nenhum detalhe de fatura encontrado.')
                return f"{mensagem_cliente} {faturas_detalhes}"
            
            # If there are no faturas found
            log_message(f"web_total_workflow: Nenhuma fatura encontrada no workflow.", level="INFO")
            return "Nenhuma fatura encontrada."
        else:
            log_message(f"web_total_workflow: Não foi possível processar os dados do workflow.", level="ERROR")
            return "Não foi possível processar os dados recebidos do workflow."
            
    except requests.exceptions.RequestException as e:
        log_message(f"web_total_workflow: Erro ao contatar o workflow: {str(e)}", level="ERROR")
        return f"Erro ao contatar o workflow: {str(e)}"


@tool
def mikweb_chamados(
    action: str,
    subject: str = None,
    message: str = None,
    customer_id: int = None,
    technical_id: int = None,
    called_type_id: int = None,
    priority: str = None,
    status: str = None,
    called_id: int = None,
    search: str = None,
    type_date: str = None,
    start_date: str = None,
    end_date: str = None,
    ) -> str:
    """
    Cria, altera, consulta, lista ou finaliza chamados na API da MikWeb.
    Esta ferramenta interage com a API de chamados da MikWeb para realizar diversas ações,
    incluindo a criação, atualização, consulta e listagem de chamados, bem como a adição de
    respostas a chamados e a manipulação de tipos de chamados e técnicos associados.

    Args:
      action: A ação a ser realizada, "create", "update", "get", "list", "delete", "finalize", "restore", "create_answer", "update_answer", "delete_answer", "list_answers", "create_type", "update_type", "get_type", "delete_type", "list_types", "create_technical", "update_technical", "get_technical", "delete_technical", "list_technicals".
      subject: Título ou assunto do chamado.
      message: Mensagem detalhada do chamado.
      customer_id: ID do cliente associado ao chamado.
      technical_id: ID do técnico associado ao chamado.
      called_type_id: ID do tipo do chamado.
      priority: Prioridade do chamado ("B" para baixa, "M" para média, "A" para alta).
      status: Status do chamado (0 para Novo, 1 para Aguardando Cliente, 2 para Aguardando Resposta, 4 para Finalizado).
      called_id: ID do chamado a ser atualizado, consultado ou deletado.
      search: Termo para pesquisar chamados por login ou nome completo do cliente.
      type_date: Tipo de data para filtrar chamados ("created_at", "updated_at", "finalized_in").
      start_date: Data inicial para o filtro de data.
      end_date: Data final para o filtro de data.
    Returns:
        Um texto com a resposta da API da MikWeb em formato JSON formatado ou uma mensagem de erro.
    """
    base_url = "https://api.mikweb.com.br/v1/admin"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MIKWEB_API_TOKEN}"
    }

    try:
        if action == "create":
            url = f"{base_url}/calledies"
            payload = {
                 "subject": subject,
                 "message": message,
                 "customer_id": customer_id,
                 "technical_id": technical_id,
                 "called_type_id": called_type_id,
                 "priority": priority,
             }
            response = requests.post(url, headers=headers, json=payload)

        elif action == "update" and called_id:
            url = f"{base_url}/calledies/{called_id}"
            payload = {}
            if technical_id:
                payload["technical_id"] = technical_id
            if priority:
                payload["priority"] = priority
            if status:
                payload["status"] = status

            response = requests.put(url, headers=headers, json=payload)
        elif action == "get" and called_id:
            url = f"{base_url}/calledies/{called_id}"
            response = requests.get(url, headers=headers)
        elif action == "list":
            url = f"{base_url}/calledies"
            params = {}
            if customer_id:
                params["customer_id"] = customer_id
            if technical_id:
                params["technical_id"] = technical_id
            if called_type_id:
                params["called_type_id"] = called_type_id
            if status:
                params["status"] = status
            if search:
                params["search"] = search
            if type_date and start_date and end_date:
                 params["type_date"] = type_date
                 params["start_date"] = start_date
                 params["end_date"] = end_date

            response = requests.get(url, headers=headers, params=params)
        elif action == "delete" and called_id:
            url = f"{base_url}/calledies/{called_id}"
            response = requests.delete(url, headers=headers)
        elif action == "finalize" and called_id:
           url = f"{base_url}/calledies/{called_id}/finalize"
           response = requests.put(url, headers=headers)
        elif action == "restore" and called_id:
            url = f"{base_url}/calledies/{called_id}/restore"
            response = requests.put(url, headers=headers)

            #Answer methods
        elif action == "create_answer" and called_id and message:
            url = f"{base_url}/calledies/{called_id}/answer_create"
            payload = {"message": message}
            response = requests.post(url, headers=headers, json=payload)
        elif action == "update_answer" and called_id and message:
            url = f"{base_url}/calledies/{called_id}/answer_update"
            payload = {"message": message}
            response = requests.put(url, headers=headers, json=payload)
        elif action == "delete_answer" and called_id:
            url = f"{base_url}/calledies/{called_id}/answer_destroy"
            response = requests.delete(url, headers=headers)
        elif action == "list_answers" :
            url = f"{base_url}/calledies/answers"
            params = {}
            if called_id:
              params["called_id"] = called_id
            response = requests.get(url, headers=headers, params=params)

         # Called Types methods
        elif action == "create_type" and description:
            url = f"{base_url}/called_types"
            payload = {"description": description}
            response = requests.post(url, headers=headers, json=payload)
        elif action == "update_type" and called_id and description:
             url = f"{base_url}/called_types/{called_id}"
             payload = {"description": description}
             response = requests.put(url, headers=headers, json=payload)
        elif action == "get_type" and called_id:
             url = f"{base_url}/called_types/{called_id}"
             response = requests.get(url, headers=headers)
        elif action == "list_types":
             url = f"{base_url}/called_types"
             response = requests.get(url, headers=headers)
        elif action == "delete_type" and called_id:
             url = f"{base_url}/called_types/{called_id}"
             response = requests.delete(url, headers=headers)

            #Technicals methods
        elif action == "create_technical" and name:
            url = f"{base_url}/technicals"
            payload = {"name": name}
            response = requests.post(url, headers=headers, json=payload)
        elif action == "update_technical" and called_id and name:
             url = f"{base_url}/technicals/{called_id}"
             payload = {"name": name}
             response = requests.put(url, headers=headers, json=payload)
        elif action == "get_technical" and called_id:
             url = f"{base_url}/technicals/{called_id}"
             response = requests.get(url, headers=headers)
        elif action == "list_technicals":
             url = f"{base_url}/technicals"
             response = requests.get(url, headers=headers)
        elif action == "delete_technical" and called_id:
             url = f"{base_url}/technicals/{called_id}"
             response = requests.delete(url, headers=headers)
        else:
          return "Ação inválida ou parâmetros faltando."
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        try:
             return json.dumps(response.json(), indent=4, ensure_ascii=False)
        except json.JSONDecodeError:
             return f"Ação realizada com sucesso. Status code: {response.status_code}"
    except requests.exceptions.RequestException as e:
        log_message(f"mikweb_chamados: Erro ao contatar a API da MikWeb: {str(e)}", level="ERROR")
        return f"Erro ao contatar a API da MikWeb: {str(e)}"

tools = [mikweb_chamados, send_whatsapp_message, web_total_workflow]

class EventHandler(AssistantEventHandler):
    @override
    def on_text_created(self, text) -> None:
      print(f"\nassistant > ", end="", flush=True)
        
    @override
    def on_text_delta(self, delta, snapshot):
      print(delta.value, end="", flush=True)
        
    def on_tool_call_created(self, tool_call):
      print(f"\nassistant > {tool_call.type}\n", flush=True)

    def on_tool_call_delta(self, delta, snapshot):
      if delta.type == 'code_interpreter':
        if delta.code_interpreter.input:
          print(delta.code_interpreter.input, end="", flush=True)
        if delta.code_interpreter.outputs:
          print(f"\n\noutput >", flush=True)
          for output in delta.code_interpreter.outputs:
            if output.type == "logs":
              print(f"\n{output.logs}", flush=True)


# Função para executar o agente
def run_agent(input_text, chat_history=[], user_id=None):
    log_message(f"run_agent: Iniciando execução do agente para o usuário {user_id}", level="INFO")
    with thread_lock:
      if user_id in thread_cache:
          thread_id = thread_cache[user_id]
          log_message(f"run_agent: Usando thread existente: {thread_id}", level="INFO")
      else:
          thread = client.beta.threads.create()
          thread_id = thread.id
          thread_cache[user_id] = thread_id
          log_message(f"run_agent: Iniciando uma nova thread para o usuário: {user_id}, thread id: {thread_id}", level="INFO")

    message = client.beta.threads.messages.create(
          thread_id=thread_id,
          role="user",
          content=input_text
    )
    log_message(f"run_agent: Mensagem enviada para o thread {thread_id} com o conteúdo: {input_text}", level="INFO", thread_id=thread_id)
    with client.beta.threads.runs.stream(
          thread_id=thread_id,
          assistant_id=ASSISTANT_ID,
          event_handler=EventHandler()
    ) as stream:
          stream.until_done()
        
    messages = client.beta.threads.messages.list(thread_id=thread_id)
    
    # Extract the last assistant response
    assistant_messages = [
        msg for msg in messages.data if msg.role == "assistant"
    ]
    if assistant_messages:
      last_message = assistant_messages[0]
      if last_message.content:
          if hasattr(last_message.content[0], 'text'):
               log_message(f"run_agent: Resposta do assistente recebida com sucesso: {last_message.content[0].text.value}", level="INFO", response=last_message.content[0].text.value, thread_id=thread_id)
               return last_message.content[0].text.value
          else:
              log_message(f"run_agent: Erro na resposta do assistente, não há texto no conteúdo.", level="WARNING", thread_id=thread_id)
              return "No text content in assistant's message."
      else:
        log_message(f"run_agent: Erro na resposta do assistente, mensagem sem conteúdo.", level="WARNING", thread_id=thread_id)
        return "Assistant's message has no content."
  else:
      log_message(f"run_agent: Erro na resposta do assistente, nenhuma mensagem encontrada.", level="WARNING", thread_id=thread_id)
      return "No assistant response found."

def log_message(message, level="INFO", response = None, thread_id = None):
    timestamp = datetime.datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message,
      "response": response,
       "thread_id": thread_id
    }
    logs.append(log_entry)
    print(log_entry)

@app.route('/webhook-whapi', methods=['POST'])
def webhook_whapi():
    try:
      log_message(f"webhook_whapi: Requisição POST recebida.", level="INFO")
      data = request.json
      log_message(f"webhook_whapi: Dados recebidos do webhook: {data}", level="DEBUG")

      if data:
            # Extract message details
            if 'messages' in data and data['messages']:
               for message in data['messages']:
                  if message['type'] == 'text':
                      phone_number = message['from']
                      user_message = message['body']
                      log_message(f"webhook_whapi: Mensagem recebida de: {phone_number}, mensagem: {user_message}", level="INFO")
                      # Run agent and get response
                      if is_cpf_valid(user_message):
                         log_message(f"webhook_whapi: CPF {user_message} encontrado, enviando para web_total_workflow", level="INFO")
                         response = web_total_workflow(cpf=user_message, resumo=f"mensagem do cliente: {user_message}", objetivo="Verificar status", acaoAPI="consulta")
                      else:
                        log_message(f"webhook_whapi: CPF não encontrado, enviando mensagem para o assistente.", level="INFO")
                        response = run_agent(user_message, user_id=phone_number)
                      # Send response using send_whatsapp_message
                      send_whatsapp_message(to=phone_number, body=response)
               return jsonify({"status": "success"}), 200
            else:
              log_message(f"webhook_whapi: Requisição inválida, não há mensagens.", level="ERROR")
              return jsonify({"status": "error", "message": "Invalid request: No messages found"}), 400
         
      else:
         log_message(f"webhook_whapi: Requisição inválida.", level="ERROR")
         return jsonify({"status": "error", "message": "Invalid request: no data"}), 400
        
    except Exception as e:
      log_message(f"webhook_whapi: Erro ao processar o webhook: {e}", level="ERROR")
      return jsonify({
                   'statusCode': 500,
                   'body': f'Erro ao processar o webhook: {e}'
                }), 500
        
    return {
        'statusCode': 405,
        'body': json.dumps({'error': 'Method not allowed'})
    }
   
@app.route('/logs', methods=['GET'])
def get_logs():
    return render_template('logs.html', logs=logs)

@app.route('/painel', methods=['GET'])
def painel():
    return render_template('painel.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)


@app.route('/', methods=['GET'])
def index():
    return redirect('/painel')

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple("0.0.0.0", 5000, app)