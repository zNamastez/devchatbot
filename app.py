import json, requests, os, logging, base64, re
from enum import Enum
from pathlib import Path
from flask import Flask, request
from pydantic import BaseModel, field_validator
from clients.parana import ParanaClient
from services.proposal import create_proposal
from clients.redis_client import redis_get, redis_set

app = Flask(__name__)
contact_mapping = {}
url = os.getenv("URL")
service_id = os.getenv("SERVICE_ID")
token = os.getenv("DIGISAC_TOKEN")

headers = {
    "Authorization": token,
    "Content-Type": "application/json"
}


logging.getLogger("werkzeug").setLevel(logging.ERROR)

class State(Enum):
    INICIAL = "INICIAL"
    ANTECIPAR_FGTS = "ANTECIPAR_FGTS"
    ANTECIPAR_FGTS_OPTANTE_SAQUE_ANIVERSARIO = "ANTECIPAR_FGTS_OPTANTE_SAQUE_ANIVERSARIO"
    CREDITO_CONSIGNADO = "CREDITO_CONSIGNADO"
    YES_I_AM_ALREADY_ENROLLED_IN_THE_BIRTHDAY_WITHDRAWAL = "YES_I_AM_ALREADY_ENROLLED_IN_THE_BIRTHDAY_WITHDRAWAL"
    OK_AUTHORIZED = "OK_AUTHORIZED"
    NO_WANT_CLARIFY_DOUBTS = "NO_WANT_CLARIFY_DOUBTS"
    MAKE_ANTECIPATION = "MAKE_ANTECIPATION"
    CONFIRMAR_DADOS_BANCARIOS = "CONFIRMAR_DADOS_BANCARIOS"
    COLETAR_DADOS_BANCARIOS = "COLETAR_DADOS_BANCARIOS"
    CLEAR_DOUBTS = "CLEAR_DOUBTS"
    YES_SIMULATE_CLT = "YES_SIMULATE_CLT"

class Cpf(BaseModel):
    cpf: str

    @field_validator("cpf")
    def validate_cpf_field(cls, cpf):
        if not validate_cpf(cpf):
            raise ValueError("CPF inválido")
        
        return cpf

def state_credito_consignado(contactId, number):
    message = (
        '''O empréstimo consignado é uma solução com taxas reduzidas, destinada a trabalhadores com contrato CLT.

Deseja receber uma simulação personalizada?'''
    )

    send_message(message, contactId, number, type="interactive", name="state_credito_consignado", buttons=["SIM", "TIRAR DÚVIDAS"])    

def yes_simulate_clt(contactId, number):
    message = (
        '''Para que possamos realizar a sua simulação de crédito consignado CLT e te apresentar as melhores condições, preciso de algumas informações:

✅ Seu CPF
✅ Data de Admissão

Com esses dados, faremos a simulação rapidamente e te enviaremos todas as opções disponíveis. Aguardo seu retorno!'''
    )

    send_message(message, contactId, number)
    send_message("Um de nossos especialistas já vai te atender!", contactId, number)
    transfer_call(contactId)


def clear_doubts(contactId, number):
    message = (
        '''O que é o Empréstimo Consignado CLT?
O empréstimo consignado CLT é uma linha de crédito destinada a trabalhadores com carteira assinada (regime CLT), onde as parcelas são descontadas diretamente do salário.
Isso oferece vantagens como:
•	Taxas de juros mais baixas em comparação a outros tipos de crédito pessoal.
•	Facilidade na aprovação, já que o pagamento é garantido pelo desconto em folha.
•	Prazos mais longos para pagamento.

Deseja fazer uma simulação sem compromisso?'''
    )
    
    send_message(message, contactId, number)

def state_confirmar_dados_bancarios_coletar_dados(state, contactId, number):
    state = get_state(contactId)
    name = state.get("name")

    message = (
        f"{name}, para liberar o valor, preciso dos seus dados bancários para a transferência.\n"
        "Por gentileza, envie as informações abaixo:\n\n"
        "- Tipo da conta\n"
        "- Nome do banco\n"
        "- Número da agência\n"
        "- Número da conta\n"
    )

    send_message(message, contactId, number)

def process_response(text, contactId, number, state):

    dados_bancarios = {
        "tipo_conta": None,
        "banco": None,
        "agencia": None,
        "conta": None
    }
    
    resposta = text.lower().strip()
    
    partes = [p.strip() for p in resposta.split(",")]
    
    if len(partes) == 4:
        dados_bancarios["tipo_conta"] = partes[0].capitalize()  
        dados_bancarios["banco"] = 260 if partes[1] == "nubank" else partes[1] 
        dados_bancarios["agencia"] = partes[2]  
        dados_bancarios["conta"] = partes[3]  
    
    if not re.match(r"\d{4}", dados_bancarios["agencia"]):  
        dados_bancarios["agencia"] = None  
    
    if not re.match(r"\d{9,12}", dados_bancarios["conta"]):  
        dados_bancarios["conta"] = None  

    message = (
        "Confirma as informações abaixo?\n\n"
        f"- Tipo da conta: {dados_bancarios["tipo_conta"]}\n"
        f"- Nome do banco: {dados_bancarios["banco"]}\n"
        f"- Número da agência: {dados_bancarios["agencia"]}\n"
        f"- Número da conta: {dados_bancarios["conta"]}\n"
    )
    
    state = get_state(contactId)
    state["tipo_conta"] = dados_bancarios["tipo_conta"]
    state["banco"] = dados_bancarios["banco"]
    state["agencia"] = dados_bancarios["agencia"]
    state["conta"] = dados_bancarios["conta"]
    state["state"] = State.CONFIRMAR_DADOS_BANCARIOS.value

    set_state(contactId, state)
    send_message(message, contactId, number, type="interactive", name="confirmar_dados_bancarios", buttons=["ESTÃO CORRETAS", "NÃO ESTÃO CORRETAS"])  

def validate_cpf(cpf):
    cpf = re.sub(r'\D', '', cpf)  

    if len(cpf) != 11 or cpf == cpf[0] * 11:  
        return False
    
    def calculate_digit(cpf, positions):
        soma = sum(int(cpf[i]) * positions[i] for i in range(len(positions)))
        return 0 if soma % 11 < 2 else 11 - (soma % 11)
    
    position1 = list(range(10, 1, -1))
    position2 = list(range(11, 1, -1))
    digit1 = calculate_digit(cpf, position1)
    digit2 = calculate_digit(cpf, position2)
    
    return cpf[-2:] == f"{digit1}{digit2}"

def handle_simulate_loan_state(contact_id, number, text, state):
    if text == "SIM":
        state["state"] = State.INICIAL.value
        yes_simulate_clt(contact_id, number)
        set_state(contact_id, state)
    elif text == "TIRAR DÚVIDAS":
        state["state"] = State.CLEAR_DOUBTS.value
        clear_doubts(contact_id, number)
        set_state(contact_id, state)

def handle_confirmar_dados_bancarios_state(contact_id, number, text, state):
    if text == "ESTÃO CORRETAS":
        state["state"] = "MAKE_ANTECIPATION"
        set_state(contact_id, state)

    message = create_proposal(contact_id)
    print(text)
    
    if text == "ESTÃO CORRETAS":
        send_message(message, contact_id, number)
    elif "pouco" in text.lower() or "muito pouco" in text.lower():
        name = state.get("name")

        message = (
            f"Eu entendo, {name}. Às vezes o valor pode parecer pequeno, mas essa antecipação pode ser útil para resolver algo urgente, sem complicação e de maneira bem simples.\n"
            "Se mudar de ideia, é só falar comigo! Estou à disposição para te ajudar sempre que precisar! 😊"
        )
        send_message(message, contact_id, number)
    elif text == "NÃO ESTÃO CORRETAS" or message == "Nenhuma conta encontrada!":
        state["state"] = State.COLETAR_DADOS_BANCARIOS.value
        state_confirmar_dados_bancarios_coletar_dados(state, contact_id, number)
        set_state(contact_id, state)
    else:
        send_message(message, contact_id, number, type="interactive", name="confirmar_dados_bancarios", buttons=["ESTÃO CORRETAS", "NÃO ESTÃO CORRETAS"])

def get_state(contactId):
    state = redis_get(contactId)
    print(f"[STATE]: {state} \n")

    if state:
        return json.loads(state)
    
    return {"interation": 0}

def set_state(contactId, state):
    redis_set(contactId, json.dumps(state))

def menu_initial(contactId, number, state):
    state["state"] = State.INICIAL.value
    name = state.get("name", "")

    message = (
        f"🖐️ Olá, {name}! Eu sou a Luísa, consultora financeira da Lucas CRED. 😊 \n"
        "Escolha abaixo o assunto que deseja tratar e vamos te ajudar rapidinho. 👇\n\n"
        "A qualquer momento durante a conversa, você pode digitar *0* para retornar a este menu."
    )

    send_message(message, contactId, number, type="interactive", name="menu_inicial", buttons=["CONSIGNADO CLT", "ANTECIPAR FGTS"])
    set_state(contactId, state)

def send_message(message, contactId, number, type="simple", name=None, buttons=None):
    try:
        payload = {"contactId": contactId, "number": number, "serviceId": service_id}
        
        if type == "simple":
            payload.update({
                "type": "chat",
                "origin": "bot",
                "text": message
            })
        else:
            payload.update({
                "type": "chat",
                "interactiveMessage": {
                    "name": name,
                    "interactive": {
                        "type": "button",
                        "action": {
                            "buttons": [{"type": "reply", "reply": {"title": title}} for title in buttons]
                        },
                        "body": {
                            "text": message
                        }
                    }
                }
            })

        response = requests.post(f"{url}/api/v1/messages", json=payload, headers=headers, timeout=60)  

        if response.status_code != 200:
            logging.error(f"Falha ao enviar mensagem. Status: {response.status_code}, Response: {response.text}")
    except requests.exceptions.Timeout as exception:
        logging.exception("A requisição excedeu o tempo de resposta (timeout): %s", exception)
    except requests.exceptions.RequestException as exception:
        logging.exception("Ocorreu um erro durante a requisição: %s", exception)

def handle_state_inicial(contact_id, number, text, state):
    if text == "ANTECIPAR FGTS":
        state["state"] = State.ANTECIPAR_FGTS.value

        if state.get("CPF"):
            state_antecipar_fgts_confirmar_cpf(state.get("CPF"), contact_id, number)
        else:
            state_antecipar_fgts_verificar_saque_aniversario(contact_id, number, state)

        set_state(contact_id, state)
    
    elif text == "CONSIGNADO CLT":
        state["state"] = State.CREDITO_CONSIGNADO.value

        state_credito_consignado(contact_id, number)
        set_state(contact_id, state)

def state_antecipar_fgts_confirmar_cpf(cpf, contactId, number):

    if len(cpf) == 11 and cpf.isdigit():
        cpf = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
    
    message = (
        f"Por gentileza, confirme se o seu CPF é {cpf}, para que eu possa dar continuidade com segurança."
    )

    send_message(message, contactId, number, type="interactive", name="state_antecipar_fgts_confirmar_cpf", buttons=["CPF ESTÁ CORRETO", "NÃO É MEU CPF"])    

def state_antecipar_fgts_verificar_saque_aniversario(contactId, number, state):
    state["state"] = State.ANTECIPAR_FGTS_OPTANTE_SAQUE_ANIVERSARIO.value

    message = (
        "Você já é optante pelo saque-aniversário?"
    )

    send_message(message, contactId, number, type="interactive", name="state_antecipar_fgts_verificar_saque_aniversario", buttons=["SIM", "NÃO (TIRAR DÚVIDA)"])    
    set_state(contactId, state)

def handle_state_antecipar_fgts_verificar_saque_aniversario_tirar_duvidas(text, contactId, number, state):
    if text == "NÃO (TIRAR DÚVIDA)":
        state_antecipar_fgts_duvidas(contactId, number)
    elif text == "TIRAR OUTRA DÚVIDA":
        send_message("Um de nossos especialistas já vai te atender!", contactId, number)
        transfer_call(contactId)
    elif text == "SIM":
        state_antecipar_fgts_coletar_cpf(contactId, number, state)

def state_antecipar_fgts_duvidas(contactId, number):
    message = (
        "💰 Não precise esperar até seu mês de aniversário para retirar uma parte do seu FGTS. Antecipe até 10 anos de saque e receba tudo de uma vez!\n\n"
        "🔹 Taxas mais baixas que as do crédito pessoal tradicional.\n"
        "🔹 O dinheiro pode cair na sua conta em até 1 hora.\n"
        "🔹 Processo rápido, simples e sem burocracia.\n\n"
        "Com base no seu saldo, conseguimos fazer uma simulação prévia, sem compromisso.\n"
        "Vamos fazer uma simulação?"
    )

    send_message(message, contactId, number, type="interactive", name="state_antecipar_fgts_duvidas", buttons=["SIM", "TIRAR OUTRA DÚVIDA"])    

def state_antecipar_fgts_coletar_cpf(contactId, number, state):
    state["state"] = State.ANTECIPAR_FGTS.value

    message = (
        "Para seguir e consultar o valor disponível para saque do seu FGTS, por gentileza, digite seu CPF."
    )

    send_message(message, contactId, number)
    set_state(contactId, state)

def hanlde_state_antecipar_fgts(contact_id, number, text, state):

    if text == "QUERO TIRAR DÚVIDAS":
        state_antecipar_fgts_tirar_duvidas(contact_id, number)
    elif text == "TIRAR OUTRA DÚVIDA" or text == "ESTOU COM DIFIC..":
        send_message("Um de nossos especialistas já vai te atender!", contact_id, number)
        transfer_call(contact_id)
    else:
        simulate_fgts(text, contact_id, number, state)

def simulate_fgts(text, contactId, number, state):
    state = get_state(contactId)
    name = state.get("name", "")

    if text == "CPF ESTÁ CORRETO" or text == "OK, AUTORIZADO" or text == "AGORA AUTORIZEI" or "autorizado" in text.lower():
        cpf = state.get("CPF")   
    elif text == "NÃO É MEU CPF":
        message = (
            f"Entendido, {name}! Por favor, envie o seu CPF corretamente para que possamos continuar com segurança."
        )

        send_message(message, contactId, number)

        return
    else:
        text = text.replace(" ", "")
        cpf = re.search(r"(\d{3}\.??\d{3}\.??\d{3}-?\d{2})", text)
        cpf = cpf.group(1) if cpf else None

        if not cpf:
            return

        try:
            valid_cpf = Cpf(cpf=cpf)
        except ValueError as exception:
            send_message("Ops! 😕 O CPF que você digitou parece estar inválido. Por favor, confira os números e digite novamente para que eu possa continuar com sua simulação.", contactId, number)

            return
        
        state["CPF"] = cpf
        set_state(contactId, state)

    parana = ParanaClient()
    valor_liberado_parana = 0

    try:
        token_parana_response = parana.auth_token()
        token_parana = token_parana_response.get("access_token")
        saldo_response = parana.fgts_saque_aniversario_saldo_disponivel(token_parana, cpf)

        if saldo_response.get("codigo") == "9":
            send_message(saldo_response.get("mensagem"), contactId, number)

            return
        
        if saldo_response.get("saldoTotal"):
            saldos_por_periodos = saldo_response.get("saldosPorPeriodos")
            simulacao_response = parana.fgts_saque_aniversario_simulacao(token_parana, cpf, saldos_por_periodos)
            valor_liberado_parana = simulacao_response.get("valorLiberado")
    except requests.RequestException as exception:
        logging.exception("Erro ao interagir com a API Parana: %s", exception)

    from clients.api_facta import FactaClient

    facta = FactaClient()
    token_facta = facta.gera_token()
    saldo_facta = facta.fgts_saldo(cpf, token_facta)
    print(f"[SALDO FACTA]: {saldo_facta}")

    if saldo_facta.get("erro"):
        
        if saldo_facta.get("mensagem") == "Existe uma Operação Fiduciária em andamento. Tente mais tarde. (5)":
            send_message("Não conseguimos simular a antecipação neste momento devido à data de seu aniversário. Mas fique tranquilo, nossa equipe está à disposição para te ajudar a encontrar a melhor solução assim que possível.", contactId, number)
        elif saldo_facta.get("mensagem") == "Cliente não possui saldo FGTS (101)":
            send_message("Infelizmente não encontramos valor liberado. Atualmente você trabalha de carteira assinada? Se sim dia 20 seu saldo será atualizado", contactId, number)
        elif "Operação não permitida antes de" in saldo_facta.get("mensagem"):
            send_message("Não conseguimos simular a antecipação neste momento devido à data de seu aniversário. Mas fique tranquilo, nossa equipe está à disposição para te ajudar a encontrar a melhor solução assim que possível.", contactId, number)
        else:
            state["interation"] += 1

            set_state(contactId, state)
            state_antecipar_fgts_autorizar_bancos(contactId, number, state.get("interation"))

        return

    retorno = saldo_facta.get("retorno")
    retorno_normalizado = { key: ("0" if key.startswith("valor_") and float(value) < 5 else value) for key, value in retorno.items() }

    payload = {
        "cpf": cpf, 
        "taxa": "1.8", 
        "tabela": "60151", 
        "parcelas": retorno_normalizado
    }

    pyld = {
        "cpf": payload["cpf"], 
        "taxa": payload["taxa"], 
        "tabela": payload["tabela"], 
        "parcelas": []
    }   

    for i in range(1, 11):
        data = f"dataRepasse_{i}"
        valor = f"valor_{i}"
        data_val = payload["parcelas"].get(data)
        valor_val = payload["parcelas"].get(valor)

        if data_val is not None and valor_val is not None:
            pyld["parcelas"].append({data: data_val, valor: valor_val})

    response_calculo = facta.fgts_calculo(token_facta, pyld)
    print(f"[RESPONSE_CALCULO]: {response_calculo}\n")

    if response_calculo.get("permitido") == "NAO":
        send_message("Infelizmente não encontramos valor liberado. Atualmente você trabalha de carteira assinada? Se sim dia 20 seu saldo será atualizado", contactId, number)
        
        return
    
    valor_liberado_facta = response_calculo.get("valor_liquido")
    prazo = sum(1 for key, value in retorno_normalizado.items() if key.startswith("valor_") and float(value) > 5)

    if float(valor_liberado_parana or 0) > float(valor_liberado_facta or 0):
        message = (
            f"{name}, ótima notícia! Você tem *R${valor_liberado_parana}* disponíveis para antecipação do seu saque-aniversário do FGTS. Esse valor já é seu e pode ser transferido rapidamente para sua conta assim que confirmarmos os dados. 😊\n"
            "Gostaria de continuar com a antecipação e receber esse valor agora?"
        )
        
        state["valorLiberado"] = valor_liberado_parana
        state["bancoId"] = 254
    elif valor_liberado_facta == None:
        send_message("Infelizmente não encontramos valor liberado. Atualmente você trabalha de carteira assinada? Se sim dia 20 seu saldo será atualizado", contactId, number)
        transfer_call(contactId)

        return
    else:
        message = (
            f"{name}, ótima notícia! Você tem *R${valor_liberado_facta}* disponíveis para antecipação do seu saque-aniversário do FGTS. Esse valor já é seu e pode ser transferido rapidamente para sua conta assim que confirmarmos os dados. 😊\n"
            "Gostaria de continuar com a antecipação e receber esse valor agora?"
        )
        
        state["valorLiberado"] = valor_liberado_facta
        state["bancoId"] = 935
        state["prazo"] = prazo
        state["taxa"] = "1.8"
        state["tabela"] = "60151" if valor_liberado_facta < 100 else ("60119" if valor_liberado_facta < 900 else "53694")
        state["simulacao_fgts"] = response_calculo.get("simulacao_fgts")

    state["state"] = "CONFIRMAR_DADOS_BANCARIOS"
    
    set_state(contactId, state)
    send_message(message, contactId, number, type="interactive", name="simulate_fgts", buttons=["REALIZAR ANTECIPAÇÃO"])

def state_antecipar_fgts_autorizar_bancos(contactId, number, interation):

    if interation == 1:    

        message = (
            "Por gentileza, libere a autorização para esses bancos no app do FGTS antes de prosseguirmos. \n\n"
            "FACTA FINANCEIRA S/A \n\n"
            "*Nós vamos compara-los e trazer a simulação mais vantajosa para você.*\n"
        )

        send_message(message, contactId, number, type="interactive", name="antecipar_fgts_autorizar_bancos", buttons=["OK, AUTORIZADO", "QUERO TIRAR DÚVIDAS"])

        image = Path(__file__).resolve().parent / "a.jpeg"

        if not image:
            logging.error("Imagem não encontrada.")

            return

        try:
            with open(image, "rb") as file:
                b64 = base64.b64encode(file.read()).decode("utf-8")
        except Exception as exception:
            logging.error(f"Erro ao ler a imagem {image.name}: {exception}")

        payload = {
            "type": "media",
            "origin": "bot",
            "file": {
                "base64": b64,
                "mimetype": "image/jpeg",
                "name": image.name
            },
            "serviceId": service_id,
            "contactId": contactId,
            "number": number
        }

        try:
            response = requests.post(f"{url}/api/v1/messages", json=payload, headers=headers, timeout=60)

            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Falha ao enviar imagem. Status: {response.status_code}, Response: {response.text}")
        except requests.exceptions.Timeout as exception:
            logging.exception("A requisição para enviar imagem excedeu o tempo de resposta (timeout): %s", exception)
        except requests.exceptions.RequestException as e:
            logging.exception("Ocorreu um erro durante a requisição para enviar imagem: %s", exception)
    if interation > 1:
        message = (
            "Vi aqui que nenhum banco está autorizado ainda!"
        )  

        send_message(message, contactId, number, type="interactive", name="state_antecipar_fgts_autorizar_bancos", buttons=["AGORA AUTORIZEI", "ESTOU COM DIFIC.."])

def state_antecipar_fgts_tirar_duvidas(contactId, number):
    message = (
        '''Se você não está conseguindo autorizar, aqui estão algumas soluções comuns:

👉Se o banco a ser autorizado não está aparecendo, tente pesquisar pelo começo do nome. Se o erro persistir, tente fechar e atualizar a versão do aplicativo na Google Play Store/Appstore

👉Se você não consegue acessar com a sua senha, tente recuperá-la tocando em "esqueci minha senha"

👉Se o aplicativo está dando algum erro ao acessar, isso pode ocorrer em momentos de alto fluxo de pessoas acessando. Tente aguardar uns minutos e tentar novamente.'''
    )

    send_message(message, contactId, number, type="interactive", name="state_antecipar_fgts_duvidas", buttons=["OK, AUTORIZADO", "TIRAR OUTRA DÚVIDA"])    
    
def transfer_call(contactId):
    payload = {
        "departmentId": "b17ee5c5-3ae8-4add-b0b7-c887cec43bbd"   
    }

    requests.post(f"{url}/api/v1/contacts/{contactId}/ticket/transfer", headers=headers, data=payload)

@app.route("/webhook", methods=["POST"])
def webhook():
    print('123')
    payload = request.get_json()
    event = payload.get("event")
    data = payload.get("data")
    contact_id = data.get("contactId")
    text = data.get("text")

    print(payload)

    if event == "message.updated" or data.get("isFromMe") or not contact_id or "ticket" in event:
        return "", 200

    if contact_id:
        query = {
            "where": {"isOpen": True},
            "include": [
                {
                    "model": "contact",
                    "required": True,
                    "where": {
                        "visible": True,
                        "id": contact_id
                    }
                }
            ]
        }

        query_string = json.dumps(query)
        final_url = f"{url}/api/v1/tickets?query={query_string}"
        responseTickets = requests.get(final_url, headers=headers)
        responseTickets_json = responseTickets.json()
        dataTickets = responseTickets_json["data"][0]

        if dataTickets.get("userId"):
            print('Cliente já está em um chamado')
            return "", 200
            
        
        state = get_state(contact_id)
        number = data.get("data").get("number")

        if "name" not in state:
            response = requests.get(f"{url}/api/v1/contacts/{contact_id or number}", headers=headers)
            response_json = response.json()

            if response_json.get("isGroup"):
                return "", 200

            state["name"] = response_json.get("name")
            set_state(contact_id, state)

        if "state" not in state or text == "0" or state == None:
            menu_initial(contact_id, number, state)

            return "", 200
        
        if state.get("state") == State.INICIAL.value:
            handle_state_inicial(contact_id, number, text, state)
        elif state.get("state") == State.ANTECIPAR_FGTS.value:
            hanlde_state_antecipar_fgts(contact_id, number, text, state)
        elif state.get("state") == State.ANTECIPAR_FGTS_OPTANTE_SAQUE_ANIVERSARIO.value:
            handle_state_antecipar_fgts_verificar_saque_aniversario_tirar_duvidas(text, contact_id, number, state)
        elif state.get("state") == State.CONFIRMAR_DADOS_BANCARIOS.value or state.get("state") == State.MAKE_ANTECIPATION.value:
            handle_confirmar_dados_bancarios_state(contact_id, number, text, state)
        elif state.get("state") == State.CREDITO_CONSIGNADO.value:
            handle_simulate_loan_state(contact_id, number, text, state)
        elif state.get("state") == State.COLETAR_DADOS_BANCARIOS.value:
            process_response(text, contact_id, number, state)
        else:
            pass

    return "", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="localhost", port=port, debug=True)