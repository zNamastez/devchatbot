import requests, os, json, logging
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from clients.api_facta import register_proposal_facta
from clients.redis_client import redis_get, redis_set

# Configurações de requisição e retry
session = requests.Session()
retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"])
adapter = HTTPAdapter(max_retries=retry)

# Adiciona adaptador para https e http
session.mount("https://", adapter)
session.mount("http://", adapter)

# Variáveis de autenticação
host = os.getenv("REDIS_HOST", "localhost")
port = os.getenv("REDIS_PORT", 6379)
db = os.getenv("REDIS_DB", 0)
token = os.getenv("NEWCORBAN_TOKEN")
timeout = 60
username = os.getenv("NEWCORBAN_USERNAME")
password = os.getenv("NEWCORBAN_PASSWORD")
# Configuração de logs
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Função para criar proposta
def create_proposal(contactId: str):
    try:
        # Pega os dados do Redis
        state_json = redis_get(contactId)
        state = json.loads(state_json)
        cpf = state.get("CPF")
        bancoId = state.get("bancoId")
        valorLiberado = state.get("valorLiberado")
        prazo = state.get("prazo")
        taxa = state.get("taxa")
        tabela = state.get("tabela")

        # Cabeçalhos da requisição
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://freitas.newcorban.com.br",
            "Referer": "https://freitas.newcorban.com.br/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0"
            )
        }

        # Faz requisição para buscar dados do cliente
        response = session.get(f"https://server.newcorban.com.br/system/cliente.php?action=buscar&cpf={cpf}", headers=headers, timeout=timeout)
        response_json = response.json()
        logger.debug(f"[CREATE_PROPOSAL]: {response_json}")

        # Se erro na resposta, tenta fazer login e renovar o token
        if response_json.get("error"):
            headersLogin = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "*/*",
                "Origin": "https://freitas.newcorban.com.br",
                "Referer": "https://freitas.newcorban.com.br/",
                "User-Agent": headers["User-Agent"]
            }

            data = {
                "usuario": username,
                "empresa": "freitas",
                "senha": password,
                "ip": "192.141.239.5",
                "cf-turnstile-response": "0" 
            }
            
            # Requisição de login
            responseLogin = session.post("https://server.newcorban.com.br/api/v2/login", headers=headersLogin, data=data)
            responseLogin.raise_for_status()

            responseLogin_json = responseLogin.json()

            if not responseLogin_json.get("token"):
                raise RuntimeError("Falha ao obter token de login")
            
            # Atualiza o token
            os.environ["NEWCORBAN_TOKEN"] = responseLogin_json.get("token")
            headers["Authorization"] = f"Bearer {responseLogin_json.get('token')}"
            response = session.get(f"https://server.newcorban.com.br/system/cliente.php?action=buscar&cpf={cpf}", headers=headers, timeout=timeout)
            response.raise_for_status()

            response_json = response.json()
        
        if state.get("state") != "COLETAR_DADOS_BANCARIOS":
            # Busca o histórico da conta bancária
            responseGetBankAccountHistory = session.get(f"https://server.newcorban.com.br/system/cliente.php?action=getBankAccountHistory&cpf={cpf}", headers=headers, timeout=timeout)
            responseGetBankAccountHistory.raise_for_status()

            responseGetBankAccountHistory_json = responseGetBankAccountHistory.json()
            try:
                responseGetBankAccountHistory_json = responseGetBankAccountHistory_json[0]
            except:
                return "Nenhuma conta encontrada!"

            # Combina conta bancária com dígito
            conta_com_digito = (
                f"{responseGetBankAccountHistory_json.get('conta')}"
                f"{responseGetBankAccountHistory_json.get('conta_digito')}"
            )
        
        if state.get("state") == "COLETAR_DADOS_BANCARIOS":
            responseGetBankAccountHistory_json = {}
            responseGetBankAccountHistory_json.setdefault("tipo_liberacao", state.get("tipo_conta"))
            responseGetBankAccountHistory_json.setdefault("banco_averbacao", state.get("banco"))
            responseGetBankAccountHistory_json.setdefault("agencia", state.get("agencia"))
            responseGetBankAccountHistory_json.setdefault("conta", state.get("conta")[:-1])
            responseGetBankAccountHistory_json.setdefault("conta_digito", state.get("conta")[-1])

            conta_com_digito = state.get("conta")

            print(responseGetBankAccountHistory_json)

        # Extraí dados do cliente
        documentos = response_json.get("cliente", {}).get("documentos", {})
        documento_id, documento_data = next(iter(documentos.items()), (None, None)) if documentos else (None, None)
        telefones = response_json.get("cliente", {}).get("telefones", {})
        telefone_id, telefones_data = next(iter(telefones.items()), (None, None)) if telefones else (None, None)
        ddd_numero = f"({telefones_data['ddd']}){telefones_data['numero']}"
        enderecos = response_json.get("cliente", {}).get("enderecos", {})
        endereco_id, endereco_data = next(iter(enderecos.items()), (None, None)) if enderecos else (None, None)

        if state.get("state") == "CONFIRMAR_DADOS_BANCARIOS":
            responseBanks = requests.get(f"https://brasilapi.com.br/api/banks/v1/{responseGetBankAccountHistory_json.get("banco_averbacao")}")
            responseBanks_json = responseBanks.json()

            message = (
                "Verifiquei que os seus dados bancários já estão registrados em nosso sistema. Para que possamos dar sequência à antecipação, poderia confirmar as informações abaixo?\n\n"
                f"- Tipo da conta: {responseGetBankAccountHistory_json.get("tipo_liberacao").replace("_", " ")}\n"
                f"- Banco: {responseBanks_json.get("name").split(" - ")[0]}\n"
                f"- Número da agência: {responseGetBankAccountHistory_json.get("agencia")}\n"
                f"- Número da conta: {conta_com_digito}"
            )
        
        else:

            # Chama a função de registro de proposta
            proposta_id_banco, link_formalizacao = register_proposal_facta(contactId=contactId, cpf=cpf, dataNascimento=response_json.get("cliente").get("pessoais").get("nascimento"), renda=response_json.get("cliente").get("pessoais").get("renda"), nome=response_json.get("cliente").get("pessoais").get("nome"), sexo=response_json.get("cliente").get("pessoais").get("sexo"), estadoCivil=response_json.get("cliente").get("pessoais").get("estado_civil"), rg=documento_data["numero"], estadoRg=documento_data["uf"], dataExpedicao=datetime.strptime(documento_data["data_emissao"], "%Y-%m-%d").strftime("%d/%m/%Y"), celular=ddd_numero, cep=endereco_data["cep"], endereco=endereco_data["logradouro"], numero=endereco_data["numero"], bairro=endereco_data["bairro"], estado=endereco_data["uf"], nomeMae=response_json.get("cliente").get("pessoais").get("mae"), nomePai=response_json.get("cliente").get("pessoais").get("pai"), clienteIletradoImpossibilitado=response_json.get("cliente").get("pessoais").get("analfabeto"), banco=responseGetBankAccountHistory_json.get("banco_averbacao"), agencia=responseGetBankAccountHistory_json.get("agencia"), conta=conta_com_digito, tipoConta=responseGetBankAccountHistory_json.get("tipo_liberacao"), cidade=endereco_data["cidade"])
            
            # Prepara o payload para criação da proposta
            payload = {
                "auth": {
                    "username": "robo.01",  
                    "password": "Luisa1234@",  
                    "empresa": "freitas"
                },
                "requestType": "createProposta",
                "content": {
                    "cliente": {
                        "pessoais": response_json.get("cliente").get("pessoais"),
                        "documentos": {documento_id: documento_data},
                        "enderecos": {endereco_id: endereco_data},
                        "telefones": {telefone_id: telefones_data}
                    },
                    "proposta": {
                        "documento_id": documento_id,
                        "endereco_id": endereco_id,
                        "telefone_id": telefone_id,
                        "banco_id": bancoId,
                        "convenio_id": "100000",
                        "proposta_id_banco": proposta_id_banco,
                        "produto_id": "7",
                        "status": 0,
                        "tipo_cadastro": "API",
                        "tipo_liberacao": responseGetBankAccountHistory_json.get("tipo_liberacao"),
                        "banco_averbacao": responseGetBankAccountHistory_json.get("banco_averbacao"),
                        "conta": responseGetBankAccountHistory_json.get("conta"),
                        "conta_digito": responseGetBankAccountHistory_json.get("conta_digito"),
                        "agencia": responseGetBankAccountHistory_json.get("agencia"),
                        "promotora_id": "2",
                        "link_formalizacao": link_formalizacao,
                        "vendedor": 8656,
                        "origem_id": 6622,
                        "proposta_id": 8464220,
                        "login_digitacao": "alcif-ltf",
                        "valor_parcela": 0,
                        "valor_financiado": float(valorLiberado),
                        "valor_liberado": float(valorLiberado),
                        "prazo": prazo,
                        "taxa": taxa,
                        "tabela_id": tabela
                    }
                }    
            }

            # Envia proposta para a API
            headersPropostas = {"Content-Type": "application/json"}
            responsePropostas = session.post("https://api.newcorban.com.br/api/propostas/", json=payload, headers=headersPropostas, timeout=timeout)
            responsePropostas.raise_for_status()

            # Mensagem de sucesso
            message = (
                "Sua proposta foi cadastrada com sucesso! Para formalizar o processo, por favor, acesse o link abaixo:\n\n"
                f"{link_formalizacao}\n\n"
                "Ficamos à disposição para qualquer dúvida!"
            )

        return message
    except requests.RequestException as e:
        logger.exception(f"RequestException ao processar create_proposal para contactId={contactId}: {e}")

        raise

    except Exception as e:
        logger.exception(f"Erro inesperado ao processar create_proposal para contactId={contactId}: {e}")
        
        raise