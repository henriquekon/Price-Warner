import os
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Query as FastAPIQuery
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from data.models import SessionLocal, Product, Store, Monitoring, User
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from engine.scraper import AddonScraper
from engine.config import ADDONS_DIR
from engine.auth import current_user

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
def get_all_products(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(Product, Monitoring).join(Monitoring, Monitoring.product_id == Product.id).filter(Monitoring.user_id == user.id).all()
    return [product_response(product, monitoring) for product, monitoring in rows]


def product_response(product: Product, monitoring: Monitoring):
    return {"id": product.id, "name": product.name, "url": product.url, "image_url": product.image_url,
            "store_id": product.store_id, "interval": monitoring.interval,
            "target_drop_percentage": monitoring.target_drop_percentage,
            "is_active": monitoring.is_active, "last_checked": product.last_checked,
            "last_error": product.last_error}


# Search by name
@router.get("/products/search")
def search_products(q: str = FastAPIQuery(..., min_length=1), db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(Product, Monitoring).join(Monitoring, Monitoring.product_id == Product.id).filter(
        Monitoring.user_id == user.id, Product.name.ilike(f"%{q}%")).all()
    return [product_response(product, monitoring) for product, monitoring in rows]

@router.post("/products", status_code=201)
def add_new_product(prod: ProductCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    addon_path = ADDONS_DIR / f"{prod.store_id}.json"
    if not addon_path.is_file():
        raise HTTPException(400, "Unsupported store addon")
    product = db.query(Product).filter(Product.url == prod.url).first()
    if product:
        monitored = db.query(Monitoring).filter(Monitoring.product_id == product.id, Monitoring.user_id == user.id).first()
        if monitored:
            raise HTTPException(409, "Product is already monitored by this account")
    else:
        store = db.get(Store, prod.store_id)
        if not store:
            db.add(Store(id=prod.store_id, name=prod.store_id.capitalize(), is_active=True))
            db.flush()
        product = Product(name=prod.name, url=prod.url, store_id=prod.store_id,
                          interval=prod.interval, target_drop_percentage=prod.target_drop_percentage)
        db.add(product)
        db.flush()
    db.add(Monitoring(user_id=user.id, product_id=product.id,
                      interval=prod.interval, target_drop_percentage=prod.target_drop_percentage))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Product is already monitored or concurrently registered") from exc
    return {"message": "Product monitoring created", "product_id": product.id}


@router.delete("/products/{product_id}")
def stop_monitoring(product_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    monitoring = db.query(Monitoring).filter(Monitoring.user_id == user.id, Monitoring.product_id == product_id).first()
    if not monitoring:
        raise HTTPException(404, "Monitoring not found")
    db.delete(monitoring)
    db.commit()
    return {"message": "Monitoring removed"}


@router.get("/products/search-external")
def search_external_store(
    q: str = FastAPIQuery(..., min_length=2), 
    store_id: str = FastAPIQuery(default="kabum", pattern=r"^[a-z0-9_-]+$"),
    user: User = Depends(current_user),
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

            <section class="bg-gray-800 border border-gray-700 rounded-2xl p-6 mt-10 max-w-2xl mx-auto">
                <h2 class="text-xl font-semibold mb-2">Email notifications</h2>
                <p class="text-sm text-gray-400 mb-5">Configure your own SMTP account. Passwords are encrypted before storage.</p>
                <form id="email-settings" class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <label class="text-sm col-span-full"><input id="mail-enabled" type="checkbox" class="mr-2">Enable email alerts</label>
                    <input id="mail-host" placeholder="SMTP host" required class="bg-gray-900 border border-gray-600 rounded p-2">
                    <input id="mail-port" type="number" min="1" max="65535" placeholder="Port" value="587" required class="bg-gray-900 border border-gray-600 rounded p-2">
                    <select id="mail-security" class="bg-gray-900 border border-gray-600 rounded p-2"><option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option></select>
                    <input id="mail-user" placeholder="SMTP username" class="bg-gray-900 border border-gray-600 rounded p-2">
                    <input id="mail-password" type="password" autocomplete="new-password" placeholder="SMTP password (leave blank to keep)" class="bg-gray-900 border border-gray-600 rounded p-2 col-span-full">
                    <input id="mail-from" type="email" placeholder="Sender email" class="bg-gray-900 border border-gray-600 rounded p-2">
                    <input id="mail-recipient" type="email" placeholder="Recipient email" class="bg-gray-900 border border-gray-600 rounded p-2">
                    <label class="col-span-full text-sm">Cooldown (hours) <input id="mail-cooldown" type="number" min="1" max="720" value="24" class="bg-gray-900 border border-gray-600 rounded p-2 ml-2 w-24"></label>
                    <button type="submit" class="bg-orange-500 rounded p-2 font-semibold">Save settings</button>
                    <button id="mail-test" type="button" class="bg-gray-700 rounded p-2 font-semibold">Send test email</button>
                </form>
                <p id="mail-status" class="text-sm text-gray-300 mt-3" role="status"></p>
            </section>
        </div>

        <!-- Notificação Flutuante (Toast) -->
        <div id="toast" class="fixed bottom-5 right-5 bg-green-600 text-white px-5 py-3 rounded-xl shadow-2xl transition-all duration-300 transform translate-y-20 opacity-0 pointer-events-none font-medium text-sm">
            Produto adicionado com sucesso!
        </div>

        <script>
            let csrfToken = null;
            async function initializeAuth() {
                const config = await (await fetch('/auth/config')).json();
                if (config.mode === 'local') return true;
                const me = await fetch('/auth/me');
                if (me.ok) {
                    const response = await fetch('/auth/csrf');
                    csrfToken = (await response.json()).csrf_token;
                    return true;
                }
                document.body.innerHTML = `<main style="max-width:420px;margin:5rem auto;font-family:sans-serif;color:white">
                  <h1>Price-Warner</h1><h2>Sign in</h2>
                  <form id="login-form"><input id="email" type="email" required placeholder="Email" style="display:block;margin:12px 0;padding:12px;width:100%">
                  <input id="password" type="password" minlength="12" required placeholder="Password" style="display:block;margin:12px 0;padding:12px;width:100%">
                  <button type="submit">Sign in</button></form><p id="auth-error"></p>
                  ${config.registration_enabled ? '<button id="register">Create account</button>' : ''}</main>`;
                async function submitAuth(path) {
                    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                        body:JSON.stringify({email:document.getElementById('email').value,
                            password:document.getElementById('password').value})});
                    if (response.ok) location.reload();
                    else document.getElementById('auth-error').textContent = (await response.json()).detail || 'Authentication failed';
                }
                document.getElementById('login-form').onsubmit = event => {event.preventDefault();submitAuth('/auth/login')};
                if (config.registration_enabled) document.getElementById('register').onclick = () => submitAuth('/auth/register');
                return false;
            }
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
                        headers: { 'Content-Type': 'application/json', ...(csrfToken ? {'X-CSRF-Token':csrfToken} : {}) },
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

            async function loadEmailSettings() {
                const response = await fetch('/notifications/settings');
                if (!response.ok) return;
                const data = await response.json();
                const fields = {enabled:'mail-enabled', recipient_email:'mail-recipient',
                    smtp_host:'mail-host', smtp_port:'mail-port', smtp_security:'mail-security',
                    smtp_username:'mail-user', from_email:'mail-from', cooldown_hours:'mail-cooldown'};
                for (const [key, id] of Object.entries(fields)) {
                    const node = document.getElementById(id);
                    if (key === 'enabled') node.checked = data[key];
                    else node.value = data[key] ?? '';
                }
                document.getElementById('mail-password').placeholder = data.has_password
                    ? 'Password saved (leave blank to keep)' : 'SMTP password';
            }

            document.getElementById('email-settings').addEventListener('submit', async event => {
                event.preventDefault();
                const status = document.getElementById('mail-status');
                const payload = {
                    enabled: document.getElementById('mail-enabled').checked,
                    smtp_host: document.getElementById('mail-host').value,
                    smtp_port: Number(document.getElementById('mail-port').value),
                    smtp_security: document.getElementById('mail-security').value,
                    smtp_username: document.getElementById('mail-user').value,
                    from_email: document.getElementById('mail-from').value || null,
                    recipient_email: document.getElementById('mail-recipient').value || null,
                    cooldown_hours: Number(document.getElementById('mail-cooldown').value)
                };
                const password = document.getElementById('mail-password').value;
                if (password) payload.smtp_password = password;
                try {
                    const response = await fetch('/notifications/settings', {method:'PUT',
                        headers:{'Content-Type':'application/json', ...(csrfToken ? {'X-CSRF-Token':csrfToken} : {})},
                        body:JSON.stringify(payload)});
                    if (!response.ok) throw new Error(`HTTP ${response.status}: ${JSON.stringify((await response.json()).detail)}`);
                    status.textContent = 'Email settings saved.';
                    document.getElementById('mail-password').value = '';
                    await loadEmailSettings();
                } catch (error) { status.textContent = `Could not save settings: ${error.message}`; }
            });

            document.getElementById('mail-test').addEventListener('click', async () => {
                const status = document.getElementById('mail-status');
                status.textContent = 'Sending test email...';
                try {
                    const response = await fetch('/notifications/test', {method:'POST',
                        headers: csrfToken ? {'X-CSRF-Token':csrfToken} : {}});
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    status.textContent = 'Test email sent.';
                } catch (error) { status.textContent = `Test failed: ${error.message}`; }
            });

            // Inicialização automática ao abrir a página
            window.onload = async () => { if (await initializeAuth()) { loadMonitoredProducts(); loadEmailSettings(); } };
        </script>
    </body>
    </html>
    """