# Centro de Monitoramento de Risco

Dashboard Streamlit para acompanhar relatos de risco no DF e entorno, classificar gravidade e visualizar ocorrências por localidade.

## Executar localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Publicar

1. Envie este projeto para um repositório no GitHub.
2. Em [Streamlit Community Cloud](https://share.streamlit.io/), crie um app apontando para o repositório, a branch principal e `app.py`.
3. Nas configurações avançadas do app, cadastre os segredos necessários:

```toml
GOOGLE_API_KEY = "sua-chave-gemini"
X_BEARER_TOKEN = "seu-token-x"
GOOGLE_MAPS_API_KEY = "sua-chave-maps-javascript"
```

As chaves são opcionais para abrir o dashboard: sem credenciais, o app mantém a classificação local e os dados demonstrativos; o mapa alternativo continua disponível sem a chave do Google Maps.

## Monitoramento meteorológico e ocorrências

- O painel consulta condições atuais e previsão de chuva, probabilidade de precipitação e rajadas do [Open-Meteo](https://open-meteo.com/en/docs), com cache de 15 minutos.
- O histórico meteorológico usa reanálise estimada do [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), que pode ter alguns dias de atraso e não confirma que ocorreu um alagamento.
- Os limiares de chuva e rajada são configuráveis na lateral e servem como triagem preventiva; os níveis exibidos não são alertas oficiais.
- Ocorrências inseridas no formulário ficam na sessão atual. Exporte o CSV para preservar os registros e importe-o novamente quando necessário.
- O painel de trânsito do [DF Agora](https://www.dfagora.com.br/transito-df-ao-vivo/) é uma fonte externa para consulta; as ocorrências registradas precisam de verificação independente.