import json
import html
import os
import time
from datetime import datetime
from urllib.parse import quote

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from google import genai

# Configuração da página
st.set_page_config(page_title="Centro de Monitoramento - Defesa Civil", layout="wide")
st.title("🚨 Centro de Monitoramento de Risco - Defesa Civil")
st.write("Monitoramento em tempo real via redes sociais e IA")

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

        maps_api_key = st.text_input(
            "Google Maps API Key", type="password", value=obter_segredo("GOOGLE_MAPS_API_KEY"),
            help="Chave separada com Maps JavaScript API habilitada",
        )
        query = st.text_input("Busca do monitoramento", value=montar_query_df())
        municipio = st.selectbox("Localidade", ["Todas"] + sorted({item["nome"] for item in LOCAL_CIDADES.values()}))
        risco_filtro = st.selectbox("Gravidade", ["Todos", "ALTO", "MÉDIO", "BAIXO"])
        pesquisa = st.button("Buscar agora")


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
                st.caption("Mapa Google: informe uma chave com Maps JavaScript API habilitada na lateral.")
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

# --- Observações do projeto ---
with st.expander("📌 Próxima etapa do projeto"):
    st.write("1. Validar o acesso da API do X para coletar ocorrências reais.")
    st.write("2. Refinar a geocodificação de ruas e bairros para posicionar cada alerta com precisão.")
    st.write("3. Adicionar Threads, Instagram e Facebook após estabilizar a coleta inicial.")