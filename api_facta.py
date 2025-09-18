import requests, base64, os, logging, json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .redis_client import redis_get

# URL base da API da Facta
base_url = "https://webservice.facta.com.br"
timeout = 60

# Configuração básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FactaClient:
    def __init__(self):
        self.session = requests.Session()
        self.credentials = os.getenv("CREDENCIAIS_FACTA") # credenciais no .env

        # tenta de novo até 3x se der erro de rede ou 5xx
        retry = Retry(total=3, backoff_factor=0.05, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)

        self.session.mount("https://", adapter)
        
        # gera header de auth básica em base64
        credentials_base64 = base64.b64encode(self.credentials.encode()).decode()
        auth_header = f"Basic {credentials_base64}"
        
        self.headers = {"Authorization": auth_header}
        
    def _handle_response(self, response):
        if response.status_code != 200:
            response.raise_for_status()
        
        return response.json()
    
    def gera_token(self) -> str:
        try:
            response = self.session.get(f"{base_url}/gera-token", headers=self.headers, timeout=timeout)

            return self._handle_response(response).get("token")
        except requests.RequestException as exception:
            logger.exception("Erro ao obter token: %s", exception)

            raise

    def fgts_saldo(self, cpf: str, token: str) -> dict:
        try:
            headers = {"Authorization": f"Bearer {token}"}
            response = self.session.get(f"{base_url}/fgts/saldo?cpf={cpf}", headers=headers, timeout=timeout)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro ao consultar saldo FGTS para CPF %s: %s", cpf, exception)

            raise
    
    def fgts_calculo(self, token: str, payload: dict) -> dict:
        try:
            headers = {
                "Authorization": f"Bearer {token}", 
                "Content-Type": "application/json"
            }

            response = self.session.post(f"{base_url}/fgts/calculo", headers=headers, json=payload, timeout=timeout)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro ao realizar cálculo FGTS: %s", exception)

            raise

    def proposta_etapa1_simulador(self, token: str, payload: dict) -> dict:
        try:
            headers = {"Authorization": f"Bearer {token}"}
            response = self.session.post(f"{base_url}/proposta/etapa1-simulador", headers=headers, json=payload, timeout=timeout)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro na Etapa 1 do simulador: %s", exception)

            raise

    def proposta_etapa2_dados_pessoais(self, token: str, payload: dict) -> dict:
        try:
            headers = {"Authorization": f"Bearer {token}"}
            response = self.session.post(f"{base_url}/proposta/etapa2-dados-pessoais", headers=headers, json=payload, timeout=timeout)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro na Etapa 2 dos dados pessoais: %s", exception)

            raise

    def proposta_combos_estado_civil(self, token: str, estadoCivil: str) -> str | None:
        try:
            headers = {"Authorization": f"Bearer {token}"}
            response = self.session.get(f"{base_url}/proposta-combos/estado-civil", headers=headers, timeout=timeout)
            data = self._handle_response(response)
            matrialStatus = data.get("estado_civil")

            for key, value in matrialStatus.items():
            
                if value == estadoCivil:
                    return key

            return None  
        except requests.RequestException as exception:
            logger.exception("Erro ao obter estado civil: %s", exception)

            raise

    def proposta_combos_cidade(self, token: str, estado: str, cidade: str) -> str:
        try:
            headers = {"Authorization": f"Bearer {token}"}
            
            params = {
                "estado": estado,
                "nome_cidade": cidade
            }

            response = self.session.get(f"{base_url}/proposta-combos/cidade", headers=headers, params=params, timeout=timeout)
            data = self._handle_response(response)
            cities = data.get("cidade") or {}

            if not cities:
                raise ValueError(f"Cidade '{cidade}' não encontrada para o estado '{estado}'.")
            
            city_id = next(iter(cities), None)

            if not city_id:
                raise ValueError(f"Cidade '{cidade}' não encontrada na resposta.")
            
            return city_id
        except requests.RequestException as exception:
            logger.exception("Erro ao consultar cidade combo para cidade %s, estado %s: %s", cidade, estado, exception)

            raise
        except ValueError as value_error:
            logger.exception(value_error)

            raise
    
    def proposta_etapa3_proposta_cadastro(self, token: str, payload: dict):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            response = self.session.post(f"{base_url}/proposta/etapa3-proposta-cadastro", headers=headers, json=payload, timeout=timeout)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro na Etapa 3 do cadastro da proposta: %s", exception)

            raise

def register_proposal_facta(contactId, cpf, dataNascimento, renda, nome, sexo, estadoCivil, rg, estadoRg, dataExpedicao, celular, cep, endereco, numero, bairro, estado, nomeMae, nomePai, clienteIletradoImpossibilitado, banco, agencia, conta, tipoConta, cidade):
    try:
        state_json = redis_get(contactId)
        state = json.loads(state_json)
        simulacao_fgts = state.get("simulacao_fgts")
        client = FactaClient()
        token = client.gera_token()

        # monta payload inicial
        payload = {
            "produto": "D",
            "tipo_operacao": "13",
            "averbador": "20095",
            "convenio": "3",
            "cpf": cpf,
            "data_nascimento": dataNascimento,
            "valor_renda": renda,
            "simulacao_fgts": simulacao_fgts,
            "login_certificado": os.getenv("LOGIN_CERTIFICADO"),  
        }

        # etapa 1
        response = client.proposta_etapa1_simulador(token, payload)
        logger.debug(f"[RESPONSE - proposta_etapa1_simulador]: {response}")
        # busca código do estado civil e cidade
        estado_civil = client.proposta_combos_estado_civil(token, estadoCivil)
        city = client.proposta_combos_cidade(token, estado, cidade)

        # etapa 2
        payload_etapa2 = {
            "id_simulador": response.get("id_simulador"),
            "cpf": cpf,
            "nome": nome,
            "sexo": sexo[0] if sexo else None,
            "estado_civil": estado_civil,
            "data_nascimento": dataNascimento,
            "rg": rg,
            "estado_rg": estadoRg,
            "orgao_emissor": "SSP",
            "data_expedicao": dataExpedicao,
            "estado_natural": estado,
            "cidade_natural": city,
            "nacionalidade": "1",
            "celular": celular,
            "renda": renda,
            "cep": cep,
            "endereco": endereco,
            "numero": numero,
            "bairro": bairro,
            "cidade": city,
            "estado": estado,
            "nome_mae": nomeMae,
            "nome_pai": nomePai,
            "valor_patrimonio": "1",
            "cliente_iletrado_impossibilitado": "S" if clienteIletradoImpossibilitado else "N",
            "banco": banco,
            "agencia": agencia,
            "conta": conta,
            "tipo_conta": "C" if tipoConta == "CONTA_CORRENTE" else "P",
            "email": os.getenv("EMAIL")
        }

        responseEtapa2 = client.proposta_etapa2_dados_pessoais(token, payload_etapa2)

        # etapa 3
        payload_etapa3 = {
            "codigo_cliente": responseEtapa2.get("codigo_cliente"),
            "id_simulador": response.get("id_simulador"),
            "po_formalizacao": "DIG"
        }

        responseEtapa3 = client.proposta_etapa3_proposta_cadastro(token, payload_etapa3)

        return responseEtapa3.get("codigo"), responseEtapa3.get("url_formalizacao")
    except requests.RequestException as exception:
        logger.exception("Erro ao registrar proposta: %s", exception)

        raise