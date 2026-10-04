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