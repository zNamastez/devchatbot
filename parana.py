import requests, os, logging
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ParanaClient:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://api-marketplace.paranabanco.com.br"
        # variáveis sensíveis via ENV
        self.client_id = os.getenv("CLIENT_ID")
        self.client_secret = os.getenv("CLIENT_SECRET")
        self.username = os.getenv("USER")
        self.password = os.getenv("password")

        # usa sessão com retry pra tolerar falhas transitórias
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)

        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    # validar resposta: se não for status 200, dá erro
    def _handle_response(self, response):
        if response.status_code != 200:
            response.raise_for_status()
        
        return response.json()

    # pega token com grant type password
    def auth_token(self) -> dict:
        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Client-Id": self.client_id
            }

            data = {
                "grant_type": "password",
                "scope": "openid",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "username": self.username,
                "password": self.password
            }

            response = self.session.post(f"{self.base_url}/v1/auth/token", headers=headers, data=data, timeout=60)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro ao obter token: %s", exception)

            raise

    # pega saldo disponível de saque aniversário usando token + CPF
    def fgts_saque_aniversario_saldo_disponivel(self, token: str, cpf: str) -> dict:
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Client-Id": self.client_id,
                "Content-Type": "application/json"
            }

            payload = {
                "cpf": cpf,
                "quantidadeDePeriodos": "10",
                "cacheParam": cpf,
                "fromCacheFGTS": False
            }

            response = self.session.post(f"{self.base_url}/v1/fgts/saque-aniversario/saldo-disponivel", headers=headers, json=payload, timeout=60)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro ao consultar saldo disponível para CPF %s: %s", cpf, exception)

            raise

    # simula saque aniversário usando vários parâmetros, inclusive data atual UTC
    def fgts_saque_aniversario_simulacao(self, token: str, cpf: str, saldosPorPeriodos: dict) -> dict:
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Client-Id": self.client_id,
                "Content-Type": "application/json"
            }

            payload = {
                "cpf": cpf,
                "dataDeNascimento": "1991-02-19T00:00:00.763Z",
                "dataDeCalculo": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "codigoDaRegra": "040030",
                "tipoDeSimulacaoSaqueAniversario": 2,
                "quantidadeDeParcelas": 10,
                "taxaMensal": 1.79,
                "percentualProtecaoFGTS": 6,
                "incluirSeguro": False,
                "incluirTarifaDeCadastro": False,
                "usuarioBanco": self.username,
                "saldoDisponivel": None,
                "valorSolicitado": 999999,
                "saldosPorPeriodos": saldosPorPeriodos
            }

            response = self.session.post(f"{self.base_url}/v3/fgts/saque-aniversario/simulacao", headers=headers, json=payload)

            return self._handle_response(response)
        except requests.RequestException as exception:
            logger.exception("Erro na simulação para CPF %s: %s", cpf, exception)

            raise