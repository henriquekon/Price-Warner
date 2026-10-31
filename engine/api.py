import os
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Query as FastAPIQuery
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from data.models import SessionLocal, Product, Store
from pydantic import BaseModel, Field
from typing import List, Optional
from engine.scraper import AddonScraper
from engine.config import ADDONS_DIR

router = APIRouter()

# Schema for creating a new product
class ProductCreate(BaseModel):
    name: str
    url: str
    store_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    interval: int = Field(default=30, ge=1, le=10080, description="Interval in minutes")
    target_drop_percentage: float = Field(default=10.0, ge=0, le=100)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/products")
def get_all_products(db: Session = Depends(get_db)):
    return db.query(Product).all()

# Search by name
@router.get("/products/search")
def search_products(q: str = FastAPIQuery(..., min_length=1), db: Session = Depends(get_db)):
    results = db.query(Product).filter(Product.name.ilike(f"%{q}%")).all()
    return results

@router.post("/products")
def add_new_product(prod: ProductCreate, db: Session = Depends(get_db)):
    if db.query(Product).filter(Product.url == prod.url).first():
        raise HTTPException(status_code=409, detail="Product URL is already monitored")

    # Checks if the store exists before adding the product
    store = db.query(Store).filter(Store.id == prod.store_id).first()
    if not store:
        addon_path = ADDONS_DIR / f"{prod.store_id}.json"
        if not addon_path.is_file():
            raise HTTPException(status_code=400, detail="Unsupported store addon")
        store = Store(id=prod.store_id, name=prod.store_id.capitalize(), is_active=True)
        db.add(store)
        db.flush()

    data = prod.model_dump()

    db_product = Product(**data)
    db.add(db_product)
    try:
        db.commit()
    except Exception as exc:
        from sqlalchemy.exc import IntegrityError
        db.rollback()
        if isinstance(exc, IntegrityError):
            raise HTTPException(status_code=409, detail="Product URL is already monitored") from exc
        raise
    db.refresh(db_product)
    
    return {"message": "Product added successfully", "product_id": db_product.id}

@router.get("/products/search-external")
def search_external_store(
    q: str = FastAPIQuery(..., min_length=2), 
    store_id: str = FastAPIQuery(default="kabum", pattern=r"^[a-z0-9_-]+$")
):
    """
    Triggers real-time store search delegating all rules to the scraper and addons.
    """
    addon_path = ADDONS_DIR / f"{store_id}.json"
    if not os.path.exists(addon_path):
        raise HTTPException(status_code=404, detail=f"Store addon '{store_id}' not found.")
        
    with AddonScraper(addon_path) as scraper:
        results = scraper.search_external(q)

    print(f"[DEBUG API] Returned: {len(results)}")
    print(f"[DEBUG API] Data returned: {results}\n")
    
    return results

@router.get("/", response_class=HTMLResponse)
def index_page():
    return """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Price Tracker Sandbox 🎯</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-gray-100 font-sans min-h-screen">

        <div class="max-w-6xl mx-auto px-4 py-8">
            <!-- Header -->
            <header class="mb-10 text-center">
                <h1 class="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-amber-500">
                    Price Tracker Engine
                </h1>
                <p class="text-gray-400 text-sm mt-2">Sandbox de Testes: Busca Externa e Ingestão de Produtos</p>
            </header>

            <!-- Área de Busca -->
            <section class="bg-gray-800 p-6 rounded-2xl shadow-xl border border-gray-700 max-w-2xl mx-auto mb-10">
                <h2 class="text-lg font-semibold mb-4 text-gray-200 flex items-center gap-2">
                    🔎 Buscar Produto na Loja
                </h2>
                <div class="flex gap-3">
                    <input type="text" id="search-input" placeholder="Ex: teclado mecanico, rtx 4060..." 
                           class="flex-1 bg-gray-900 border border-gray-600 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-orange-500 transition-colors">
                    <button onclick="performSearch()" id="search-btn"
                            class="bg-orange-500 hover:bg-orange-600 text-white font-medium px-6 py-3 rounded-xl transition-colors shadow-lg shadow-orange-500/20 active:scale-95">
                        Pesquisar
                    </button>
                </div>
                <div id="loading-state" class="hidden text-center text-orange-400 text-sm mt-4 animate-pulse">
                    Varrendo a KaBuM! aguarde...
                </div>
            </section>

            <!-- Grid de Resultados Externos -->
            <section class="mb-12">
                <h2 class="text-xl font-bold mb-6 text-gray-300 hidden" id="results-title">
                    Resultados Encontrados na Loja
                </h2>
                <div id="search-results" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
                    <!-- Cards de busca vão brotar aqui via JS -->
                </div>
            </section>

            <hr class="border-gray-800 my-8">

            <!-- Seção de Itens Já Cadastrados (Monitorados) -->
            <section>
                <div class="flex justify-between items-center mb-6">
                    <h2 class="text-xl font-bold text-gray-300">📋 Produtos Sendo Monitorados</h2>
                    <button onclick="loadMonitoredProducts()" class="text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 px-3 py-1.5 rounded-lg border border-gray-700 transition-colors">
                        🔄 Atualizar Lista
                    </button>
                </div>
                <div id="monitored-list" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    <!-- Itens monitorados vão aqui -->
                </div>
            </section>
        </div>

        <!-- Notificação Flutuante (Toast) -->
        <div id="toast" class="fixed bottom-5 right-5 bg-green-600 text-white px-5 py-3 rounded-xl shadow-2xl transition-all duration-300 transform translate-y-20 opacity-0 pointer-events-none font-medium text-sm">
            Produto adicionado com sucesso!
        </div>

        <script>
            let monitoredProductKeys = new Set();
            const searchCards = [];

            function escapeHTML(value) {
                return String(value ?? '').replace(/[&<>"']/g, character => ({
                    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
                })[character]);
            }

            function productKey(url) {
                try {
                    const parsed = new URL(url, window.location.origin);
                    const match = parsed.pathname.match(/^\\/produto\\/(\\d+)(?:\\/|$)/);
                    if (match && parsed.hostname.endsWith('kabum.com.br')) {
                        return `kabum:${match[1]}`;
                    }
                    return `${parsed.hostname}${parsed.pathname.replace(/\\/$/, '')}`;
                } catch {
                    return String(url || '').trim();
                }
            }

            function setMonitorButtonState(button, monitored) {
                button.disabled = monitored;
                button.textContent = monitored ? 'Already monitoring' : 'Monitor this item';
                button.className = monitored
                    ? 'w-full bg-green-700 text-white font-semibold py-2 rounded-xl text-xs cursor-not-allowed'
                    : 'w-full bg-gray-700 hover:bg-green-600 text-gray-300 font-semibold py-2 rounded-xl text-xs';
            }

            function refreshSearchButtons() {
                searchCards.forEach(({button, url}) => {
                    setMonitorButtonState(button, monitoredProductKeys.has(productKey(url)));
                });
            }

            // Search external store products
            async function performSearch() {
                const query = document.getElementById('search-input').value.trim();
                if (query.length < 2) return alert('Digite pelo menos 2 caracteres.');

                const btn = document.getElementById('search-btn');
                const loader = document.getElementById('loading-state');
                const container = document.getElementById('search-results');
                const title = document.getElementById('results-title');

                // UI Loading state
                btn.disabled = true;
                loader.classList.remove('hidden');
                container.innerHTML = '';
                searchCards.length = 0;

                try {
                    const response = await fetch(`/products/search-external?q=${encodeURIComponent(query)}&store_id=kabum`);
                    if (!response.ok) throw new Error(`Search failed (HTTP ${response.status})`);
                    const products = await response.json();

                    btn.disabled = false;
                    loader.classList.add('hidden');

                    if (products.length === 0) {
                        container.innerHTML = `<p class="col-span-full text-center text-gray-500 py-8">Nenhum produto encontrado ou erro no Scraper.</p>`;
                        return;
                    }

                    title.classList.remove('hidden');

                    // Renderiza os cards dinamicamente
                    products.forEach(prod => {
                        const card = document.createElement('div');
                        card.className = "bg-gray-800 rounded-2xl p-4 border border-gray-700/50 flex flex-col justify-between hover:border-gray-600 transition-all group shadow-md";
                        
                        // Fallback caso a imagem fale
                        const imgUrl = prod.image_url || 'https://placehold.co/150?text=Sem+Foto';
                        const displayPrice = prod.price ? `R$ ${prod.price.toLocaleString('pt-BR', {minimumFractionDigits: 2})}` : 'Indisponível';

                        card.innerHTML = `
                            <div>
                                <div class="bg-gray-900 rounded-xl p-2 flex items-center justify-center h-40 mb-4 overflow-hidden relative">
                                    <img src="${escapeHTML(imgUrl)}" alt="Product image" class="max-h-full max-w-full object-contain group-hover:scale-105 transition-transform duration-300">
                                </div>
                                <h3 class="text-sm font-semibold text-gray-200 line-clamp-2 mb-2 min-h-[40px]" title="${escapeHTML(prod.name)}">
                                    ${escapeHTML(prod.name)}
                                </h3>
                            </div>
                            <div class="mt-4">
                                <div class="text-amber-400 font-bold text-lg mb-3">${displayPrice}</div>
                                <button onclick="monitorProduct('${btoa(unescape(encodeURIComponent(JSON.stringify(prod))))}', this)"
                                        class="w-full bg-gray-700 hover:bg-green-600 hover:text-white text-gray-300 font-semibold py-2 rounded-xl text-xs transition-all flex items-center justify-center gap-1 active:scale-95">
                                    ➕ Monitorar este Item
                                </button>
                            </div>
                        `;
                        container.appendChild(card);
                        const monitorButton = card.querySelector('button');
                        searchCards.push({button: monitorButton, url: prod.url});
                        setMonitorButtonState(monitorButton, monitoredProductKeys.has(productKey(prod.url)));
                    });

                } catch (error) {
                    btn.disabled = false;
                    loader.classList.add('hidden');
                    console.error(error);
                    alert('Erro ao conectar com a API de busca externa.');
                }
            }

            // Envia os dados do card selecionado para o banco de dados via POST /products
            async function monitorProduct(encodedData, buttonElement) {
                // Decoda o objeto do produto que embutimos no botão
                const productData = JSON.parse(decodeURIComponent(escape(atob(encodedData))));
                
                // Payload estruturado exatamente como o Pydantic 'ProductCreate' espera
                const payload = {
                    name: productData.name,
                    url: productData.url,
                    store_id: productData.store_id,
                    interval: 30, // Nosso novo padrão refinado
                    target_drop_percentage: 10.0
                };

                // Desativa botão para evitar cliques duplos
                const originalText = buttonElement.textContent;
                buttonElement.disabled = true;
                buttonElement.textContent = "Adding...";

                try {
                    const response = await fetch('/products', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    const raw = await response.text();
                    let result = {};
                    try { result = JSON.parse(raw); } catch { /* Non-JSON error response */ }

                    if (response.ok) {
                        monitoredProductKeys.add(productKey(productData.url));
                        refreshSearchButtons();
                        showToast();
                        loadMonitoredProducts(); // Recarrega o painel inferior automaticamente
                    } else {
                        if (response.status === 409) {
                            monitoredProductKeys.add(productKey(productData.url));
                            refreshSearchButtons();
                        } else {
                            buttonElement.disabled = false;
                            buttonElement.textContent = originalText;
                        }
                        alert(`Failed to monitor product (HTTP ${response.status}): ${result.detail || raw || 'Unknown error'}`);
                    }
                } catch (error) {
                    buttonElement.disabled = false;
                    buttonElement.textContent = originalText;
                    console.error(error);
                    alert(`Failed to monitor product: ${error.message}`);
                }
            }

            // Carrega os itens salvos no banco para vermos se persistiu mesmo
            async function loadMonitoredProducts() {
                const container = document.getElementById('monitored-list');
                container.innerHTML = '<p class="text-gray-500 text-sm animate-pulse">Lendo banco de dados...</p>';
                
                try {
                    const response = await fetch('/products');
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const products = await response.json();
                    monitoredProductKeys = new Set(products.map(p => productKey(p.url)));
                    refreshSearchButtons();

                    container.innerHTML = '';
                    if(products.length === 0) {
                        container.innerHTML = '<p class="text-gray-600 text-sm italic col-span-full">Nenhum produto cadastrado no banco ainda.</p>';
                        return;
                    }
                    
                    products.forEach(p => {
                        const item = document.createElement('div');
                        item.className = "bg-gray-800/40 border border-gray-800 rounded-xl p-3 flex items-center gap-3 text-xs";
                        item.innerHTML = `
                            <div class="w-10 h-10 bg-gray-900 rounded-lg p-1 shrink-0 flex items-center justify-center">
                                <img src="${escapeHTML(p.image_url || 'https://placehold.co/50')}" class="max-h-full max-w-full object-contain">
                            </div>
                            <div class="overflow-hidden flex-1">
                                <p class="font-medium text-gray-300 truncate" title="${escapeHTML(p.name)} Margem: ${p.target_drop_percentage}%">${escapeHTML(p.name)}</p>
                                <p class="text-gray-500 text-[10px] mt-0.5 truncate">${escapeHTML(p.url)}</p>
                            </div>
                            <span class="bg-gray-900 border border-gray-700 text-gray-400 px-2 py-1 rounded font-mono text-[10px]">
                                i:${p.interval}m
                            </span>
                        `;
                        container.appendChild(item);
                    });
                } catch (e) {
                    container.innerHTML = '<p class="text-red-500 text-sm">Erro ao carregar monitorados.</p>';
                }
            }

            function showToast() {
                const toast = document.getElementById('toast');
                toast.classList.remove('opacity-0', 'translate-y-20', 'pointer-events-none');
                setTimeout(() => {
                    toast.classList.add('opacity-0', 'translate-y-20', 'pointer-events-none');
                }, 2500);
            }

            // Inicialização automática ao abrir a página
            window.onload = loadMonitoredProducts;
        </script>
    </body>
    </html>
    """