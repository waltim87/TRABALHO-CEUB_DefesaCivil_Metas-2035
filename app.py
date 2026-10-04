import json
import hashlib
import html
import os
import time
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from google import genai
from html.parser import HTMLParser

# Configuração da página
st.set_page_config(page_title="Centro de Monitoramento - Defesa Civil", layout="wide")
st_autorefresh(interval=5 * 60 * 1000, key="atualizacao_automatica")
st.title("🚨 Centro de Monitoramento de Risco - Defesa Civil")
st.write("Monitoramento em tempo real via redes sociais e IA")
st.caption(f"Painel atualizado em {datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')} (horário de Brasília)")

# --- Dados de apoio para geolocalização ---
REGIOES_DF = [
    "df", "distrito federal", "brasilia", "gama", "taguatinga", "ceilândia",
    "samambaia", "sobradinho", "brazlândia", "planaltina", "paranoá",
    "candangolândia", "nucleo bandeirante", "santo antonio do descoberto",
    "luziânia", "valparaíso", "formosa", "mimoso", "lago paranoá",
    "são sebastião", "águas claras", "guará"
]

TERMOS_DE_RISCO = [
    "buraco", "buracos", "assoreamento", "assoreada", "rua quebrada",
    "rua danificada", "deslizamento", "deslizamentos", "alto do rio",
    "rio transbordando", "lago transbordando", "água subindo", "enchente",
    "alagamento", "erosão", "cratera", "calçada cede", "desbarrancamento",
    "aterro", "vale em rua", "quebra de rua", "via destruída"
]

TERMOS_NOTICIAS_RISCO = [
    "alagamento", "enchente", "inundacao", "desabamento", "desabou", "colapso",
    "afundamento", "deslizamento", "chuva forte", "temporal", "vendaval",
    "rajada", "queda de arvore", "erosao", "buraco", "transbordamento",
    "ponte caiu", "ponte desabou", "ponte cedeu", "ponte interditada",
    "ponte comprometida", "ponte em risco", "ponte com rachadura", "viaduto caiu",
    "viaduto desabou", "viaduto cedeu", "viaduto interditado", "viaduto comprometido",
    "estrutura abalada", "estrutura comprometida", "risco estrutural", "rachadura estrutural",
    "predio desabou", "predio interditado", "edificio desabou", "edificio interditado",
]

LOCAL_CIDADES = {
    "brasilia": {"nome": "Brasília", "lat": -15.7939, "lon": -47.8828},
    "taguatinga": {"nome": "Taguatinga", "lat": -15.8331, "lon": -48.0568},
    "ceilandia": {"nome": "Ceilândia", "lat": -15.8174, "lon": -48.1087},
    "gama": {"nome": "Gama", "lat": -16.0167, "lon": -48.0667},
    "sobradinho": {"nome": "Sobradinho", "lat": -15.6500, "lon": -47.7900},
    "planaltina": {"nome": "Planaltina", "lat": -15.6170, "lon": -47.6500},
    "samambaia": {"nome": "Samambaia", "lat": -15.8750, "lon": -48.0800},
    "lago paranoa": {"nome": "Lago Paranoá", "lat": -15.7700, "lon": -47.8000},
    "sao sebastiao": {"nome": "São Sebastião", "lat": -15.9000, "lon": -47.7700},
    "guara": {"nome": "Guará", "lat": -15.8300, "lon": -47.9800},
    "aguas claras": {"nome": "Águas Claras", "lat": -15.8400, "lon": -48.0200},
    "luziania": {"nome": "Luziânia", "lat": -16.2520, "lon": -47.9500},
    "valparaiso": {"nome": "Valparaíso de Goiás", "lat": -16.0650, "lon": -47.9750},
    "formosa": {"nome": "Formosa", "lat": -15.5400, "lon": -47.3350},
}

# --- Funções auxiliares ---
def montar_query_df():
    regioes = " OR ".join(REGIOES_DF)
    termos = " OR ".join(TERMOS_DE_RISCO)
    return f"({regioes}) AND ({termos})"


def filtrar_df_entorno(texto: str):
    texto_lower = normalizar_texto(texto)
    menciona_regiao = any(normalizar_texto(regiao) in texto_lower for regiao in REGIOES_DF)
    menciona_termo = any(normalizar_texto(termo) in texto_lower for termo in TERMOS_DE_RISCO)
    return menciona_regiao and menciona_termo


def normalizar_texto(texto: str):
    import unicodedata

    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere))


def obter_segredo(nome: str):
    try:
        return st.secrets.get(nome, os.getenv(nome, ""))
    except Exception:
        return os.getenv(nome, "")


class LeitorTextoHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.partes = []

    def handle_data(self, dado):
        self.partes.append(dado)


def limpar_resumo_html(conteudo):
    leitor = LeitorTextoHTML()
    leitor.feed(conteudo or "")
    return " ".join(" ".join(leitor.partes).split())


@st.cache_data(ttl=300, show_spinner=False)
def buscar_noticias_dfagora():
    resposta = requests.get("https://www.dfagora.com.br/feed/", timeout=20)
    resposta.raise_for_status()
    raiz = ET.fromstring(resposta.content)
    noticias = []
    termos_risco = [normalizar_texto(termo) for termo in TERMOS_NOTICIAS_RISCO]
    termos_localidade = [
        normalizar_texto(regiao) for regiao in REGIOES_DF
        if regiao not in {"df", "mimoso"}
    ]

    for item in raiz.findall("./channel/item"):
        titulo = limpar_resumo_html(item.findtext("title", ""))
        resumo = limpar_resumo_html(item.findtext("description", ""))
        link = item.findtext("link", "")
        categorias = [limpar_resumo_html(categoria.text or "") for categoria in item.findall("category")]
        texto_busca = normalizar_texto(f"{titulo} {resumo}")
        e_risco = any(termo in texto_busca for termo in termos_risco)
        e_df = any(normalizar_texto(categoria) == "distrito federal" for categoria in categorias)
        e_df = e_df or any(regiao in texto_busca for regiao in termos_localidade)
        if not (e_risco and e_df and link):
            continue

        data_publicacao = item.findtext("pubDate", "")
        try:
            data_formatada = parsedate_to_datetime(data_publicacao).astimezone(
                ZoneInfo("America/Sao_Paulo")
            ).strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError, OverflowError):
            data_formatada = data_publicacao
        noticias.append({
            "titulo": titulo,
            "resumo": resumo[:420],
            "link": link,
            "data": data_formatada,
            "categoria": ", ".join(categorias),
            "risco": classificar_risco_noticia(f"{titulo} {resumo}"),
        })
    return noticias


def classificar_risco_noticia(texto):
    texto_normalizado = normalizar_texto(texto)
    if any(termo in texto_normalizado for termo in ["desabamento", "desabou", "colapso", "soterrado", "morte", "mortos", "feridos"]):
        return "ALTO"
    if any(termo in texto_normalizado for termo in ["ponte", "viaduto", "estrutura", "rachadura", "interdit", "alagamento", "enchente", "deslizamento", "vendaval"]):
        return "MÉDIO"
    return "BAIXO"


@st.cache_data(ttl=900, show_spinner=False)
def buscar_previsao_clima(pontos):
    parametros = {
        "latitude": ",".join(str(ponto[1]) for ponto in pontos),
        "longitude": ",".join(str(ponto[2]) for ponto in pontos),
        "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_gusts_10m",
        "hourly": "precipitation_probability,precipitation,wind_gusts_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_gusts_10m_max",
        "forecast_days": 7,
        "timezone": "America/Sao_Paulo",
    }
    resposta = requests.get("https://api.open-meteo.com/v1/forecast", params=parametros, timeout=25)
    resposta.raise_for_status()
    dados = resposta.json()
    return dados if isinstance(dados, list) else [dados]


@st.cache_data(ttl=86400, show_spinner=False)
def buscar_historico_clima(pontos, inicio, fim):
    parametros = {
        "latitude": ",".join(str(ponto[1]) for ponto in pontos),
        "longitude": ",".join(str(ponto[2]) for ponto in pontos),
        "start_date": inicio,
        "end_date": fim,
        "daily": "precipitation_sum,wind_gusts_10m_max",
        "timezone": "America/Sao_Paulo",
    }
    resposta = requests.get("https://archive-api.open-meteo.com/v1/archive", params=parametros, timeout=30)
    resposta.raise_for_status()
    dados = resposta.json()
    return dados if isinstance(dados, list) else [dados]


def descricao_tempo(codigo):
    descricoes = {
        0: "Céu limpo", 1: "Predomínio de céu limpo", 2: "Parcialmente nublado", 3: "Encoberto",
        45: "Neblina", 48: "Neblina com geada", 51: "Garoa leve", 53: "Garoa moderada",
        55: "Garoa intensa", 61: "Chuva leve", 63: "Chuva moderada", 65: "Chuva forte",
        80: "Pancadas leves", 81: "Pancadas moderadas", 82: "Pancadas fortes",
        95: "Tempestade", 96: "Tempestade com granizo", 99: "Tempestade forte com granizo",
    }
    return descricoes.get(codigo, f"Código meteorológico {codigo}")


def resumir_previsao_clima(previsao, local, chuva_limite, vento_limite):
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    horaria = previsao.get("hourly", {})
    horas_futuras = [
        indice for indice, instante in enumerate(horaria.get("time", []))
        if datetime.fromisoformat(instante).replace(tzinfo=agora.tzinfo) >= agora
    ][:24]
    chuva_horaria = horaria.get("precipitation", [])
    probabilidade_horaria = horaria.get("precipitation_probability", [])
    rajadas_horarias = horaria.get("wind_gusts_10m", [])
    chuva_24h = sum((chuva_horaria[i] or 0) for i in horas_futuras if i < len(chuva_horaria))
    prob_chuva = max((probabilidade_horaria[i] or 0) for i in horas_futuras if i < len(probabilidade_horaria)) if horas_futuras else 0
    rajada_prevista = max((rajadas_horarias[i] or 0) for i in horas_futuras if i < len(rajadas_horarias)) if horas_futuras else 0
    atual = previsao.get("current", {})
    codigo = int(atual.get("weather_code", 0) or 0)
    tempestade = codigo in {95, 96, 97, 99}

    if tempestade or chuva_24h >= chuva_limite * 1.7 or rajada_prevista >= vento_limite * 1.4:
        risco, icone = "ALTO", "🔴"
    elif chuva_24h >= chuva_limite or rajada_prevista >= vento_limite or (prob_chuva >= 70 and chuva_24h >= 5):
        risco, icone = "MÉDIO", "🟡"
    else:
        risco, icone = "BAIXO", "🟢"

    return {
        "Localidade": local[0], "lat": local[1], "lon": local[2],
        "risco": risco, "icone": icone,
        "Temperatura (°C)": atual.get("temperature_2m"),
        "Umidade (%)": atual.get("relative_humidity_2m"),
        "Chuva atual (mm)": atual.get("precipitation"),
        "Vento atual (km/h)": atual.get("wind_speed_10m"),
        "Rajada atual (km/h)": atual.get("wind_gusts_10m"),
        "Chuva 24h prevista (mm)": round(chuva_24h, 1),
        "Prob. chuva 24h (%)": prob_chuva,
        "Rajada máx. prevista (km/h)": round(rajada_prevista, 1),
        "Condição": descricao_tempo(codigo),
    }


def extrair_local(texto: str):
    texto_lower = normalizar_texto(texto)
    for nome, coordenadas in LOCAL_CIDADES.items():
        if nome in texto_lower:
            return coordenadas["nome"], coordenadas["lat"], coordenadas["lon"]
    if "rua" in texto_lower or "avenida" in texto_lower or "bairro" in texto_lower:
        return "Local identificado no texto", None, None
    return "Local não identificado", None, None


def classificar_risco_local(texto: str):
    texto_lower = texto.lower()
    if any(p in texto_lower for p in ["soterrado", "preso", "deslizamento", "água subindo", "risco de morte", "morto", "feridos"]):
        return "ALTO", "🔴"
    if any(p in texto_lower for p in ["alagamento", "sem saída", "ponte caída", "queda de árvore", "falta de energia", "estrada bloqueada"]):
        return "MÉDIO", "🟡"
    return "BAIXO", "🟢"


def classificar_risco_ia(texto: str):
    texto_limpo = (texto or "").strip()
    if not texto_limpo:
        return "BAIXO", "🟢", "Texto vazio"

    chave = st.session_state.get("google_api_key") or obter_segredo("GOOGLE_API_KEY")
    if not chave:
        risco, icone = classificar_risco_local(texto_limpo)
        return risco, icone, "Classificação local por fallback"

    try:
        client = genai.Client(api_key=chave)
        prompt = f"""
        Analise esse relato de emergência em contexto brasileiro.
        Responda APENAS em JSON, sem texto extra, no formato:
        {{"risco":"ALTO|MEDIO|BAIXO","motivo":"explicação curta"}}

        Relato: {texto_limpo}
        """
        response = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
        resposta = response.text.strip()
        if "```" in resposta:
            resposta = resposta.replace("```json", "").replace("```", "").strip()
        payload = json.loads(resposta)
        nivel = str(payload.get("risco", "BAIXO")).upper()
        if nivel == "ALTO":
            return "ALTO", "🔴", payload.get("motivo", "Alto risco")
        if nivel in ["MEDIO", "MÉDIO"]:
            return "MÉDIO", "🟡", payload.get("motivo", "Risco moderado")
        return "BAIXO", "🟢", payload.get("motivo", "Baixo risco")
    except Exception as erro:
        risco, icone = classificar_risco_local(texto_limpo)
        return risco, icone, f"Fallback local. Detalhe: {erro}"


def gerar_posts_demo():
    return [
        {
            "texto": "Alagamento em rua de Taguatinga, água subindo e trânsito bloqueado.",
            "usuario": "alerta_df",
            "local": "Taguatinga",
            "lat": -15.8331,
            "lon": -48.0568,
            "fonte": "demo",
            "hora": datetime.now().strftime("%H:%M:%S"),
        },
        {
            "texto": "Água subindo rapidamente na Ceilândia após chuva forte, moradores pedem ajuda.",
            "usuario": "chuva_df",
            "local": "Ceilândia",
            "lat": -15.8174,
            "lon": -48.1087,
            "fonte": "demo",
            "hora": datetime.now().strftime("%H:%M:%S"),
        },
        {
            "texto": "Assoreamento na margem do Lago Paranoá preocupa moradores de Brasília.",
            "usuario": "aguas_df",
            "local": "Lago Paranoá",
            "lat": -15.7700,
            "lon": -47.8000,
            "fonte": "demo",
            "hora": datetime.now().strftime("%H:%M:%S"),
        },
        {
            "texto": "Buraco grande abriu na pista do Gama e danificou a rua.",
            "usuario": "df_agora",
            "local": "Gama",
            "lat": -16.0167,
            "lon": -48.0667,
            "fonte": "demo",
            "hora": datetime.now().strftime("%H:%M:%S"),
        },
    ]


def buscar_posts_x(query_texto: str, token: str):
    if not token:
        return gerar_posts_demo()

    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "query": query_texto,
        "max_results": 10,
        "tweet.fields": "created_at,author_id,text",
        "user.fields": "username,name",
    }
    url = "https://api.x.com/2/tweets/search/recent"
    try:
        resposta = requests.get(url, headers=headers, params=params, timeout=20)
        if resposta.status_code != 200:
            st.sidebar.warning(f"X API retornou erro: {resposta.status_code}. Usando dados demonstrativos.")
            return gerar_posts_demo()
        dados = resposta.json()
        posts = []
        users = {u["id"]: u for u in dados.get("includes", {}).get("users", [])}
        for item in dados.get("data", []):
            texto = item.get("text", "")
            user_id = item.get("author_id")
            usuario = users.get(user_id, {}).get("username", "usuario")
            local, lat, lon = extrair_local(texto)
            posts.append({
                "texto": texto,
                "usuario": usuario,
                "local": local,
                "lat": lat,
                "lon": lon,
                "fonte": "x",
                "hora": item.get("created_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")),
            })
        return posts if posts else gerar_posts_demo()
    except Exception as erro:
        st.sidebar.warning(f"Não foi possível consultar o X: {erro}. Usando dados demonstrativos.")
        return gerar_posts_demo()


def renderizar_mapa_google(mapa_df: pd.DataFrame, chave: str):
        ocorrencias = []
        for _, item in mapa_df.iterrows():
                ocorrencias.append({
                        "lat": float(item["lat"]),
                        "lng": float(item["lon"]),
                        "local": str(item["local"]),
                        "risco": str(item["risco"]),
                        "texto": str(item["texto"]),
                        "hora": str(item["hora"]),
                })
        dados_js = json.dumps(ocorrencias, ensure_ascii=False)
        dados_js = dados_js.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        chave_url = quote(chave, safe="")
        html_mapa = f"""
        <div id="map" style="height:490px;width:100%;"></div>
        <script>
            const ocorrencias = {dados_js};
            function initMap() {{
                const centro = {{ lat: -15.7939, lng: -47.8828 }};
                const mapa = new google.maps.Map(document.getElementById("map"), {{
                    center: centro, zoom: 10, mapTypeControl: false, streetViewControl: false,
                    fullscreenControl: true
                }});
                const janela = new google.maps.InfoWindow();
                const cores = {{ ALTO: "#d64b42", "MÉDIO": "#df9b2b", BAIXO: "#27866b" }};
                ocorrencias.forEach((ocorrencia) => {{
                    const marcador = new google.maps.Marker({{
                        position: {{ lat: ocorrencia.lat, lng: ocorrencia.lng }},
                        map: mapa,
                        title: `${{ocorrencia.risco}} | ${{ocorrencia.local}}`,
                        icon: {{
                            path: google.maps.SymbolPath.CIRCLE, scale: 9,
                            fillColor: cores[ocorrencia.risco] || "#426b80", fillOpacity: 0.95,
                            strokeColor: "#ffffff", strokeWeight: 2
                        }}
                    }});
                    marcador.addListener("click", () => {{
                        const conteudo = document.createElement("div");
                        conteudo.style.cssText = "max-width:280px;font:14px sans-serif;white-space:pre-wrap";
                        conteudo.textContent = `${{ocorrencia.risco}} | ${{ocorrencia.local}} | ${{ocorrencia.hora}}\\n${{ocorrencia.texto}}`;
                        janela.setContent(conteudo);
                        janela.open({{ anchor: marcador, map: mapa }});
                    }});
                }});
            }}
        </script>
        <script async src="https://maps.googleapis.com/maps/api/js?key={chave_url}&callback=initMap"></script>
        """
        components.html(html_mapa, height=510, scrolling=False)


# --- Configuração das chaves e filtros ---
with st.sidebar:
        st.header("APIs e filtros")

        google_api_key = st.text_input(
            "Google API Key (Gemini)", type="password",
            value=obter_segredo("GOOGLE_API_KEY"), help="Chave usada para classificação por IA",
        )
        if google_api_key:
                st.session_state["google_api_key"] = google_api_key

        x_bearer = st.text_input(
            "X Bearer Token", type="password", value=obter_segredo("X_BEARER_TOKEN"),
            help="Token da API do X/Twitter",
        )
        if x_bearer:
                st.session_state["x_bearer"] = x_bearer

        maps_api_key = obter_segredo("GOOGLE_MAPS_API_KEY")
        query = st.text_input("Busca do monitoramento", value=montar_query_df())
        municipio = st.selectbox("Localidade", ["Todas"] + sorted({item["nome"] for item in LOCAL_CIDADES.values()}))
        risco_filtro = st.selectbox("Gravidade", ["Todos", "ALTO", "MÉDIO", "BAIXO"])
        chuva_limite = st.number_input("Atenção a chuva em 24h (mm)", min_value=1.0, max_value=200.0, value=30.0, step=5.0)
        vento_limite = st.number_input("Atenção a rajadas (km/h)", min_value=10.0, max_value=150.0, value=60.0, step=5.0)
        local_clima = st.selectbox("Localidade para previsão detalhada", sorted({item["nome"] for item in LOCAL_CIDADES.values()}))
        pesquisa = st.button("Buscar agora")


# --- Painel meteorológico ---
st.header("Clima e alertas preventivos")
st.caption("Previsões indicativas; não são alertas oficiais nem substituem INMET, Defesa Civil ou CBMDF.")
pontos_clima = tuple((item["nome"], item["lat"], item["lon"]) for item in LOCAL_CIDADES.values())
if st.button("Atualizar clima"):
    buscar_previsao_clima.clear()

try:
    previsoes_clima = buscar_previsao_clima(pontos_clima)
    if len(previsoes_clima) != len(pontos_clima):
        raise ValueError("A fonte retornou uma quantidade inesperada de localidades.")
    resumos_clima = [
        resumir_previsao_clima(previsao, ponto, chuva_limite, vento_limite)
        for previsao, ponto in zip(previsoes_clima, pontos_clima)
    ]
    clima_df = pd.DataFrame(resumos_clima)
    alto_clima = int((clima_df["risco"] == "ALTO").sum())
    medio_clima = int((clima_df["risco"] == "MÉDIO").sum())
    col_clima_1, col_clima_2, col_clima_3 = st.columns(3)
    col_clima_1.metric("Alertas altos", alto_clima)
    col_clima_2.metric("Atenção", medio_clima)
    col_clima_3.metric("Localidades monitoradas", len(clima_df))
    st.caption("Fonte: Open-Meteo · dados em lote · cache de 15 minutos")

    mapa_clima = clima_df.copy()
    mapa_clima["cor"] = mapa_clima["risco"].map({
        "ALTO": [214, 75, 66], "MÉDIO": [223, 155, 43], "BAIXO": [39, 134, 107]
    })
    mapa_clima["local"] = mapa_clima["Localidade"]
    mapa_clima["chuva"] = mapa_clima["Chuva 24h prevista (mm)"]
    mapa_clima["rajada"] = mapa_clima["Rajada máx. prevista (km/h)"]
    camada_clima = pdk.Layer(
        "ScatterplotLayer", data=mapa_clima, get_position="[lon, lat]",
        get_fill_color="cor", get_radius=1500, radius_min_pixels=6,
        radius_max_pixels=18, pickable=True,
    )
    vista_clima = pdk.ViewState(latitude=-15.82, longitude=-47.93, zoom=7.5, pitch=0)
    st.pydeck_chart(pdk.Deck(
        layers=[camada_clima], initial_view_state=vista_clima,
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={"html": "<b>{local}</b><br/>Risco: {risco}<br/>Chuva 24h: {chuva} mm<br/>Rajadas: {rajada} km/h"},
    ), use_container_width=True)
    st.dataframe(clima_df.drop(columns=["lat", "lon", "icone"]), hide_index=True, use_container_width=True)

    indice_local = next(i for i, ponto in enumerate(pontos_clima) if ponto[0] == local_clima)
    previsao_local = previsoes_clima[indice_local]
    serie_horaria = previsao_local.get("hourly", {})
    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    indices_24h = [
        i for i, instante in enumerate(serie_horaria.get("time", []))
        if datetime.fromisoformat(instante) >= agora
    ][:24]
    if indices_24h:
        st.subheader(f"Previsão para {local_clima}")
        horarios = [serie_horaria["time"][i] for i in indices_24h]
        col_chuva, col_probabilidade, col_rajada = st.columns(3)
        col_chuva.line_chart(pd.Series(
            [serie_horaria["precipitation"][i] for i in indices_24h], index=horarios, name="Chuva (mm)"
        ))
        col_probabilidade.line_chart(pd.Series(
            [serie_horaria["precipitation_probability"][i] for i in indices_24h], index=horarios, name="Probabilidade (%)"
        ))
        col_rajada.line_chart(pd.Series(
            [serie_horaria["wind_gusts_10m"][i] for i in indices_24h], index=horarios, name="Rajada (km/h)"
        ))
        diario = previsao_local.get("daily", {})
        previsao_7d = pd.DataFrame({
            "Chuva (mm)": diario.get("precipitation_sum", []),
            "Probabilidade máx. (%)": diario.get("precipitation_probability_max", []),
            "Rajada máx. (km/h)": diario.get("wind_gusts_10m_max", []),
            "Temp. máx. (°C)": diario.get("temperature_2m_max", []),
            "Temp. mín. (°C)": diario.get("temperature_2m_min", []),
        }, index=diario.get("time", []))
        st.dataframe(previsao_7d, use_container_width=True)
except Exception as erro:
    st.warning(f"Não foi possível atualizar os dados meteorológicos agora: {erro}")

with st.expander("Histórico meteorológico por localidade"):
    st.caption("Reanálise estimada de chuva e vento, com alguns dias de atraso. Não representa um cadastro confirmado de alagamentos.")
    dias_historico = st.selectbox(
        "Período do histórico", [7, 30, 90], index=1,
        format_func=lambda dias: f"Últimos {dias} dias",
    )
    if st.button("Carregar histórico meteorológico"):
        data_fim = datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=5)
        data_inicio = data_fim - timedelta(days=dias_historico - 1)
        with st.spinner("Consultando histórico meteorológico..."):
            try:
                historicos = buscar_historico_clima(pontos_clima, data_inicio.isoformat(), data_fim.isoformat())
                linhas_historico = []
                for ponto, historico in zip(pontos_clima, historicos):
                    diario = historico.get("daily", {})
                    chuvas = [valor for valor in diario.get("precipitation_sum", []) if valor is not None]
                    rajadas = [valor for valor in diario.get("wind_gusts_10m_max", []) if valor is not None]
                    linhas_historico.append({
                        "Localidade": ponto[0], "Início": data_inicio.isoformat(), "Fim": data_fim.isoformat(),
                        "Chuva acumulada (mm)": round(sum(chuvas), 1),
                        "Maior chuva diária (mm)": round(max(chuvas, default=0), 1),
                        "Maior rajada (km/h)": round(max(rajadas, default=0), 1),
                    })
                st.session_state["historico_meteorologico"] = pd.DataFrame(linhas_historico)
            except Exception as erro:
                st.error(f"Falha ao carregar histórico: {erro}")
    if "historico_meteorologico" in st.session_state:
        st.dataframe(st.session_state["historico_meteorologico"], hide_index=True, use_container_width=True)


st.subheader("Notícias e alertas do DF Agora")
st.caption("Manchetes e resumos do RSS público, filtrados por termos de risco e referências ao DF. Confirme o conteúdo no artigo original.")
if st.button("Atualizar notícias do DF Agora"):
    buscar_noticias_dfagora.clear()
try:
    noticias_dfagora = buscar_noticias_dfagora()
    if not noticias_dfagora:
        st.info("Nenhuma notícia recente corresponde aos filtros de risco e localidade.")
    else:
        st.caption(f"{len(noticias_dfagora)} notícias relevantes encontradas · cache de 5 minutos")
        for noticia in noticias_dfagora[:10]:
            with st.container():
                st.markdown(f"**{html.escape(noticia['titulo'])}**")
                st.caption(f"Risco preliminar {noticia['risco']} · {noticia['data']} · {noticia['categoria'] or 'DF Agora'}")
                st.write(noticia["resumo"])
                st.link_button("Abrir notícia original", noticia["link"])
                st.markdown("---")
except Exception as erro:
    st.warning(f"Não foi possível consultar o feed do DF Agora neste momento: {erro}")


# --- Estado inicial ---
if "posts" not in st.session_state:
    st.session_state["posts"] = []

# --- Busca e processamento ---
if pesquisa:
    with st.spinner("Coletando e validando ocorrências..."):
        posts = buscar_posts_x(query, st.session_state.get("x_bearer") or obter_segredo("X_BEARER_TOKEN"))
        registros = []
        for post in posts:
            texto = post.get("texto", "")
            local_nome = post.get("local", "Local não identificado")
            if not filtrar_df_entorno(texto + " " + local_nome):
                continue
            risco, icone, motivo = classificar_risco_ia(texto)
            registros.append({
                "texto": texto,
                "usuario": post.get("usuario", "anonimo"),
                "local": local_nome,
                "lat": post.get("lat"),
                "lon": post.get("lon"),
                "risco": risco,
                "icone": icone,
                "motivo": motivo,
                "fonte": post.get("fonte", "manual"),
                "hora": post.get("hora", datetime.now().strftime("%H:%M:%S")),
            })
        st.session_state["posts"] = registros

# --- Painel filtrado ---
if st.session_state["posts"]:
    df = pd.DataFrame(st.session_state["posts"])
    df_visivel = df.copy()
    if municipio != "Todas":
        df_visivel = df_visivel[df_visivel["local"] == municipio]
    if risco_filtro != "Todos":
        df_visivel = df_visivel[df_visivel["risco"] == risco_filtro]

    if df_visivel.empty:
        st.info("Nenhuma ocorrência corresponde aos filtros selecionados.")
    else:
        contagem = df_visivel["risco"].value_counts().to_dict()

        col1, col2, col3 = st.columns(3)
        col1.metric("Alto", contagem.get("ALTO", 0))
        col2.metric("Médio", contagem.get("MÉDIO", 0))
        col3.metric("Baixo", contagem.get("BAIXO", 0))

        st.subheader("Distribuição por zona e risco")
        zonas = df_visivel["local"].fillna("Não identificado").astype(str)
        risco_df = df_visivel.assign(zona=zonas)
        resumo = risco_df.groupby(["zona", "risco"]).size().reset_index(name="total")
        st.bar_chart(resumo.pivot(index="zona", columns="risco", values="total").fillna(0))

        st.subheader("Tendência por gravidade")
        tendencia = df_visivel.groupby("risco").size().reset_index(name="quantidade")
        st.bar_chart(tendencia.set_index("risco")["quantidade"])

        st.subheader("Mapa de ocorrências")
        mapa_df = df_visivel.dropna(subset=["lat", "lon"]).copy()
        if not mapa_df.empty:
            chave_maps = maps_api_key or obter_segredo("GOOGLE_MAPS_API_KEY")
            if chave_maps:
                renderizar_mapa_google(mapa_df, chave_maps)
            else:
                mapa_df["cor"] = mapa_df["risco"].map({
                    "ALTO": [214, 75, 66], "MÉDIO": [223, 155, 43], "BAIXO": [39, 134, 107]
                })
                mapa_df["local_seguro"] = mapa_df["local"].astype(str).map(html.escape)
                mapa_df["risco_seguro"] = mapa_df["risco"].astype(str).map(html.escape)
                mapa_df["texto_seguro"] = mapa_df["texto"].astype(str).map(html.escape)
                camada = pdk.Layer(
                    "ScatterplotLayer", data=mapa_df, get_position="[lon, lat]",
                    get_fill_color="cor", get_radius=700, radius_min_pixels=7,
                    radius_max_pixels=18, pickable=True,
                )
                vista = pdk.ViewState(latitude=-15.7939, longitude=-47.8828, zoom=9, pitch=0)
                dica = {"html": "<b>{local_seguro}</b><br/>Risco: {risco_seguro}<br/>{texto_seguro}", "style": {"color": "white"}}
                st.pydeck_chart(pdk.Deck(
                    layers=[camada], initial_view_state=vista,
                    map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
                    tooltip=dica,
                ), use_container_width=True)
                st.caption("Para ativar o Google Maps, configure GOOGLE_MAPS_API_KEY nos segredos do app.")
        else:
            st.info("Ainda não há coordenadas válidas para exibir no mapa.")

        st.subheader("Feed de ocorrências")
        for _, item in df_visivel.iterrows():
            with st.container():
                st.info(f"{item['icone']} **Risco {item['risco']}** | {item['local']} | {item['hora']} | Fonte: {item['fonte']}")
                st.write(item["texto"])
                st.caption(f"Motivo da IA: {item['motivo']}")
                st.markdown("---")
else:
    st.subheader("📊 Fila de monitoramento")
    st.write("Ainda não houve busca. Use os filtros da lateral para iniciar a coleta.")

# --- Entrada e histórico de ocorrências ---
st.divider()
st.header("Registro de ocorrências")
st.caption("Os registros ficam na sessão atual. Exporte o CSV para preservar ou importar históricos anteriores.")
st.link_button("Abrir painel de trânsito ao vivo do DF Agora", "https://www.dfagora.com.br/transito-df-ao-vivo/")

if "registros_manuais" not in st.session_state:
    st.session_state["registros_manuais"] = []

with st.form("form_ocorrencia", clear_on_submit=True):
    coluna_data, coluna_tipo = st.columns(2)
    data_evento = coluna_data.date_input("Data do evento", value=datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    tipo_evento = coluna_tipo.selectbox("Tipo de evento", [
        "Alagamento", "Enchente", "Ponte comprometida", "Estrutura/edificação abalada",
        "Deslizamento", "Rajada de vento", "Queda de árvore", "Buraco ou erosão", "Outro",
    ])
    coluna_local, coluna_gravidade = st.columns(2)
    local_evento = coluna_local.selectbox(
        "Localidade do evento", sorted({item["nome"] for item in LOCAL_CIDADES.values()}) + ["Outra / não identificada"]
    )
    gravidade_evento = coluna_gravidade.selectbox("Gravidade informada", ["ALTO", "MÉDIO", "BAIXO", "A avaliar"])
    referencia_evento = st.text_input("Endereço, via ou referência")
    descricao_evento = st.text_area("Descrição do evento", max_chars=1000)
    coluna_fonte, coluna_status = st.columns(2)
    fonte_evento = coluna_fonte.selectbox("Fonte do relato", ["DF Agora", "INMET", "Defesa Civil", "CBMDF", "Morador", "Outra"])
    status_evento = coluna_status.selectbox("Verificação", ["Pendente de verificação", "Confirmado por equipe", "Não confirmado", "Encerrado"])
    link_evento = st.text_input("Link da notícia ou evidência (opcional)")
    coordenadas_texto = st.text_input("Coordenadas opcionais (latitude, longitude)", placeholder="-15.7939, -47.8828")
    enviar_evento = st.form_submit_button("Registrar ocorrência")

if enviar_evento:
    if not descricao_evento.strip():
        st.error("Informe uma descrição antes de registrar.")
    else:
        latitude_evento, longitude_evento = None, None
        coordenadas_validas = True
        precisao_coordenadas = "Não informada"
        if coordenadas_texto.strip():
            try:
                latitude_evento, longitude_evento = [float(valor.strip()) for valor in coordenadas_texto.split(",", maxsplit=1)]
                if not (-90 <= latitude_evento <= 90 and -180 <= longitude_evento <= 180):
                    raise ValueError("Coordenadas fora dos limites válidos.")
                precisao_coordenadas = "Informada manualmente"
            except ValueError:
                coordenadas_validas = False
                st.error("Coordenadas inválidas. Use latitude, longitude; exemplo: -15.7939, -47.8828.")
        elif local_evento != "Outra / não identificada":
            dados_local = next(item for item in LOCAL_CIDADES.values() if item["nome"] == local_evento)
            latitude_evento, longitude_evento = dados_local["lat"], dados_local["lon"]
            precisao_coordenadas = "Centro aproximado da localidade"

        if coordenadas_validas:
            st.session_state["registros_manuais"].append({
                "data": data_evento.isoformat(), "tipo": tipo_evento, "localidade": local_evento,
                "referencia": referencia_evento.strip(), "gravidade": gravidade_evento,
                "descricao": descricao_evento.strip(), "fonte": fonte_evento,
                "verificacao": status_evento, "link": link_evento.strip(),
                "latitude": latitude_evento, "longitude": longitude_evento,
                "precisao_coordenadas": precisao_coordenadas,
            })
            st.success("Ocorrência registrada nesta sessão.")

arquivo_importado = st.file_uploader("Importar histórico de ocorrências (CSV)", type=["csv"], key="importar_ocorrencias")
if arquivo_importado:
    hash_arquivo = hashlib.sha256(arquivo_importado.getvalue()).hexdigest()
    if st.session_state.get("hash_csv_importado") != hash_arquivo:
        try:
            dados_importados = pd.read_csv(arquivo_importado)
            campos_necessarios = {"data", "tipo", "localidade", "gravidade", "descricao", "fonte", "verificacao"}
            if not campos_necessarios.issubset(dados_importados.columns):
                st.error("O CSV não contém as colunas obrigatórias do histórico de ocorrências.")
            else:
                st.session_state["registros_manuais"].extend(dados_importados.to_dict("records"))
                st.session_state["hash_csv_importado"] = hash_arquivo
                st.success(f"Importadas {len(dados_importados)} ocorrências.")
        except Exception as erro:
            st.error(f"Não foi possível importar o CSV: {erro}")

if st.session_state["registros_manuais"]:
    registros_df = pd.DataFrame(st.session_state["registros_manuais"])
    st.dataframe(registros_df, hide_index=True, use_container_width=True)
    st.download_button(
        "Exportar histórico CSV", data=registros_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="historico_ocorrencias_defesa_civil.csv", mime="text/csv",
    )

# --- Observações do projeto ---
with st.expander("📌 Próxima etapa do projeto"):
    st.write("1. Integrar alertas oficiais do INMET e observações hidrológicas do DF.")
    st.write("2. Conectar o cadastro a um armazenamento persistente compartilhado.")
    st.write("3. Refinar a geocodificação de ruas, pontes e estruturas para posicionar eventos com precisão.")