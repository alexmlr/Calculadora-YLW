from flask import Flask, render_template, request
import pandas as pd
import math
import unicodedata
import re

app = Flask(__name__)

# ===========================
# Helpers
# ===========================
def remove_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def slugify(s: str) -> str:
    s = remove_acentos(s.strip().lower())
    s = re.sub(r"[^a-z0-9\s\-_/]", "", s)
    s = s.replace("/", " ").replace("-", " ").replace("  ", " ")
    s = re.sub(r"\s+", "_", s).strip("_")
    return s

# ===========================
# Catálogo (m³, empilhamento, altura unidade em m, limite por pilha)
# Ajuste as alturas e limites conforme sua operação.
# ===========================
catalogo = {
    "sofa":                 {"m3": 2.50, "empilhavel": False, "altura": 1.00},
    "geladeira":            {"m3": 1.20, "empilhavel": False, "altura": 1.80},
    "mesa":                 {"m3": 1.80, "empilhavel": False, "altura": 0.75},
    "cadeira de jantar":    {"m3": 0.50, "empilhavel": True,  "max_emp": 4, "altura": 1.00},
    "caixa pequena":        {"m3": 0.10, "empilhavel": True,  "max_emp": 6, "altura": 0.40},
    "caixa media":          {"m3": 0.30, "empilhavel": True,  "max_emp": 5, "altura": 0.50},
    "caixa grande":         {"m3": 0.50, "empilhavel": True,  "max_emp": 4, "altura": 0.60},
    "fogao":                {"m3": 0.30, "empilhavel": False, "altura": 0.90},
    "cama box":             {"m3": 1.60, "empilhavel": False, "altura": 0.60},
    "colchao de casal":     {"m3": 0.80, "empilhavel": True,  "max_emp": 3, "altura": 0.25},
    "colchao de solteiro":  {"m3": 0.50, "empilhavel": True,  "max_emp": 3, "altura": 0.25},
    "maquina de lavar":     {"m3": 0.30, "empilhavel": False, "altura": 1.00},
    "mesa de jantar":       {"m3": 0.84, "empilhavel": False, "altura": 0.75},
    "rack":                 {"m3": 0.22, "empilhavel": False, "altura": 0.55},
    "sofa 2 lugares":       {"m3": 1.18, "empilhavel": False, "altura": 0.90},
    "sofa 3 lugares":       {"m3": 2.34, "empilhavel": False, "altura": 1.00},
    "tv":                   {"m3": 0.41, "empilhavel": False, "altura": 0.70},
    "escrivaninha":         {"m3": 0.41, "empilhavel": False, "altura": 0.75},
    "cadeira de escritorio":{"m3": 0.30, "empilhavel": True,  "max_emp": 3, "altura": 1.00},
    "poltrona":             {"m3": 0.53, "empilhavel": False, "altura": 1.00},
}

# Monta lista para UI (usada no template) com slug e metadados
itens_ui = []
for nome, meta in catalogo.items():
    itens_ui.append({
        "nome": nome,
        "slug": slugify(nome),
        "m3": meta["m3"],
        "empilhavel": meta.get("empilhavel", False),
        "max_emp": meta.get("max_emp", 1),
        "altura": meta.get("altura", 0.5),
    })
itens_ui = sorted(itens_ui, key=lambda x: x["nome"])

# ===========================
# Boxes
# ===========================
df_boxes = pd.read_excel("Boxes.xlsx")

# Renomeia colunas para nomes estáveis
df_boxes = df_boxes.rename(columns={
    "M²": "Metros Quadrados",
    "M³": "Metros Cubicos"
})

# Converte colunas numéricas
for col in ["Metros Quadrados", "Metros Cubicos", "Largura", "Comprimento", "Altura"]:
    if col in df_boxes.columns:
        df_boxes[col] = pd.to_numeric(df_boxes[col], errors="coerce")

# Filtra apenas disponíveis se a coluna existir
if "Status" in df_boxes.columns:
    df_boxes = df_boxes[df_boxes["Status"].astype(str).str.strip().str.lower() == "disponível"]

# Remove linhas sem volume/altura
df_boxes = df_boxes.dropna(subset=["Metros Cubicos", "Altura"])

# ===========================
# Cálculo com empilhamento por altura do box
# ===========================
def calcular_itens(qtd_por_slug: dict):
    """Transforma as quantidades do formulário em uma lista de itens normalizados com metadados."""
    itens = []
    slug_to_nome = {slugify(k): k for k in catalogo.keys()}

    for slug, qtd in qtd_por_slug.items():
        if qtd <= 0:
            continue
        nome = slug_to_nome.get(slug)
        if not nome:
            continue
        meta = catalogo[nome]
        itens.append({
            "nome": nome,
            "qtd": int(qtd),
            "m3": meta["m3"],
            "empilhavel": meta.get("empilhavel", False),
            "max_emp": meta.get("max_emp", 1),
            "altura": meta.get("altura", 0.5),
        })
    return itens

def volume_para_box(itens: list, altura_box: float, folga: float = 0.15):
    """
    Calcula volume total (com folga) e altura máxima usada para UM box específico,
    respeitando a altura do box no empilhamento.
    Retorna (volume_total, altura_maxima_usada, detalhes_por_item) ou (None, None, motivo) se algum item não couber.
    """
    total = 0.0
    max_alt_uso = 0.0
    detalhes = []

    for it in itens:
        qtd = it["qtd"]
        m3 = it["m3"]
        alt = it["altura"]

        if it["empilhavel"]:
            # quantas camadas cabem na altura do box
            camadas_por_pilha = int(altura_box // alt)
            camadas_por_pilha = min(camadas_por_pilha, it["max_emp"])
            if camadas_por_pilha < 1:
                return (None, None, f"{it['nome']} não cabe em altura ({alt:.2f} m) no box de {altura_box:.2f} m")

            pilhas = math.ceil(qtd / camadas_por_pilha)
            v_item = pilhas * m3
            total += v_item
            altura_pilha = min(camadas_por_pilha, qtd) * alt
            max_alt_uso = max(max_alt_uso, altura_pilha)

            detalhes.append(
                f"{qtd}× {it['nome']} → {pilhas} pilha(s), {v_item:.2f} m³ "
                f"(camadas/pilha={camadas_por_pilha}, alt usada {altura_pilha:.2f} m)"
            )
        else:
            v_item = qtd * m3
            total += v_item
            max_alt_uso = max(max_alt_uso, alt)
            detalhes.append(f"{qtd}× {it['nome']} → {v_item:.2f} m³ (não empilha, altura {alt:.2f} m)")

    total *= (1.0 + folga)
    return (total, max_alt_uso, detalhes)

def escolher_box_por_altura(itens: list):
    """
    Simula empilhamento respeitando a altura de CADA box.
    Retorna (box_escolhido, volume_calc, altura_usada, detalhes) ou (None, None, None, motivo)
    """
    candidatos = []

    for _, box in df_boxes.iterrows():
        altura_box = float(box["Altura"])
        res = volume_para_box(itens, altura_box)
        if isinstance(res, tuple) and len(res) == 3:
            vol, alt_uso, detalhes = res
        else:
            vol = alt_uso = None
            detalhes = res  # motivo
        if vol is None:
            # este box não comporta algum item em altura
            continue
        if box["Metros Cubicos"] >= vol:
            candidatos.append((vol, alt_uso, detalhes, box))

    if not candidatos:
        return (None, None, None, "Nenhum box atende ao volume/altura após simular empilhamento pela altura do box.")

    # escolhe o candidate com menor volume cúbico do box; em empate, o de menor volume calculado
    candidatos.sort(key=lambda t: (t[3]["Metros Cubicos"], t[0]))
    melhor = candidatos[0]
    return (melhor[3], melhor[0], melhor[1], melhor[2])

# ===========================
# Rota principal (usa template index.html)
# ===========================
@app.route("/", methods=["GET", "POST"])
def index():
    resultado_html = None
    detalhes_html = None

    if request.method == "POST":
        # Lê quantidades do formulário (qty_<slug>)
        qtd_por_slug = {}
        for item in itens_ui:
            field = f"qty_{item['slug']}"
            raw = (request.form.get(field, "0") or "0").strip()
            try:
                qtd = int(raw)
            except:
                qtd = 0
            qtd_por_slug[item["slug"]] = max(0, qtd)

        itens_sel = calcular_itens(qtd_por_slug)
        box, vol_calc, alt_usada, detalhes = escolher_box_por_altura(itens_sel)

        # Detalhes
        if itens_sel and isinstance(detalhes, list):
            detalhes_html = "<b>Itens:</b><br>" + "<br>".join(detalhes)
        elif isinstance(detalhes, str):
            detalhes_html = detalhes
        else:
            detalhes_html = "—"

        # Resultado
        if box is not None:
            resultado_html = (
                f"<b>Volume total (com folga):</b> {vol_calc:.2f} m³<br>"
                f"<b>Altura máxima empilhada usada:</b> {alt_usada:.2f} m<br>"
                f"<b>Box sugerido:</b> {box['Box']} "
                f"({box['Largura']}m × {box['Comprimento']}m × {box['Altura']}m = {box['Metros Cubicos']} m³)"
            )
        else:
            resultado_html = "❌ Nenhum box disponível atende ao volume/altura com empilhamento respeitando a altura do box."

    return render_template("index.html", itens=itens_ui, resultado=resultado_html, detalhes=detalhes_html)

# ===========================
# Run
# ===========================
if __name__ == "__main__":
    app.run(debug=True)
