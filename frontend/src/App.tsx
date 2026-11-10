import Pagination from './Pagination';
import Settings from './Settings';
import Alerts from './Alerts';
import ProductDetails from './ProductDetails';
import Discover from './Discover';
import { useEffect, useState } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, Bell, Box, CheckCircle2, ChevronDown, CircleAlert, Clock3, ExternalLink, LayoutDashboard, LogIn, LogOut, Menu, PackageSearch, RefreshCw, Search, Plus, Settings2, ShieldCheck, TrendingDown, Trash2, X } from 'lucide-react';

type Product = { id: number; name: string; url: string; store_id: string; image_url: string | null; image_proxy_url?: string | null; is_active: boolean; last_checked: string | null; last_error: string | null; price: number | null; previous_price: number | null; price_change_percent: number | null; availability: string; currency: string; target_drop_percentage: number; interval: number; tags: string[] };
type SortMode = 'newest' | 'name_asc' | 'name_desc' | 'price_asc' | 'price_desc' | 'change_asc' | 'change_desc' | 'last_checked';
type ChangePeriod = 'last' | '24h' | '7d' | '30d';
type Dashboard = { period: ChangePeriod; pagination: {page:number;page_size:number;total:number;pages:number}; summary: { total: number; active: number; price_drops: number; errors: number }; products: Product[] };
type Store = { id: string; name: string; supports_search: boolean; currency: string };
type Config = { mode: 'local' | 'private' | 'public'; registration_enabled: boolean };
type User = { email: string; mode: string; is_admin?: boolean };

const api = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, { credentials: 'same-origin', ...init });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
};
const money = (value: number | null, currency = 'BRL') => value === null ? 'Not checked yet' : new Intl.NumberFormat('pt-BR', {style:'currency', currency}).format(value);
const age = (value: string | null) => value ? new Intl.DateTimeFormat('en-US', { dateStyle:'medium', timeStyle:'short' }).format(new Date(value.endsWith('Z') ? value : `${value}Z`)) : 'Never';

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [stores, setStores] = useState<Store[]>([]);
  const [busy, setBusy] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [register, setRegister] = useState(false);
  const [query, setQuery] = useState('');
  const [storeFilter, setStoreFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [changePeriod, setChangePeriod] = useState<ChangePeriod>('7d');
  const [watchPage, setWatchPage] = useState(1);
  const [watchSize, setWatchSize] = useState(20);
  const [watchSort, setWatchSort] = useState<SortMode>('newest');
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [page, setPage] = useState<'overview'|'discover'|'details'|'settings'|'alerts'>('overview');
  const [selectedProductId, setSelectedProductId] = useState<number|null>(null);

  const loadData = async () => {
    const params = new URLSearchParams({period:changePeriod, page:String(watchPage), page_size:String(watchSize),
      q:query.trim(), store_id:storeFilter, status:statusFilter, sort:watchSort});
    const [data, storeData] = await Promise.all([api<Dashboard>(`/dashboard?${params}`), api<Store[]>('/stores')]);
    setDashboard(data);
    setStores(storeData);
  };

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const authConfig = await api<Config>('/auth/config');
        if (!active) return;
        setConfig(authConfig);
        try {
          const account = await api<User>('/auth/me');
          if (!active) return;
          setUser(account);
        } catch (cause) {
          if (authConfig.mode === 'local') throw cause;
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Failed to load the application');
      } finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (user) {
      void loadData().catch(cause => setError(cause instanceof Error ? cause.message : 'Failed to load dashboard'));
    }
  }, [user?.email, changePeriod, watchPage, watchSize, watchSort, query, storeFilter, statusFilter]);

  const toggleSort = (ascending: SortMode, descending: SortMode) => {
    setWatchSort(current => current === ascending ? descending : ascending);
    setWatchPage(1);
  };
  const filtered = dashboard?.products ?? [];
  const matchingTotal = dashboard?.pagination.total ?? 0;

  const removeProduct = async (product: Product) => {
    if (!window.confirm(`Stop monitoring "${product.name}"? Its alerts for this account will be removed.`)) return;
    setDeletingId(product.id); setError('');
    try {
      const {csrf_token} = await api<{csrf_token:string | null}>('/auth/csrf');
      await api(`/products/${product.id}`, {method:'DELETE', headers:csrf_token ? {'X-CSRF-Token':csrf_token} : {}});
      if (watchPage > 1 && matchingTotal - 1 <= (watchPage - 1) * watchSize) {
        setWatchPage(watchPage - 1);
      } else {
        await loadData();
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to remove monitoring');
    } finally {setDeletingId(null);}
  };

  const refresh = async () => {
    setRefreshing(true); setError('');
    try { await loadData(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Failed to refresh'); }
    finally { setRefreshing(false); }
  };
  const signIn = async (event: React.FormEvent) => {
    event.preventDefault(); setAuthBusy(true); setError('');
    try {
      await api(register ? '/auth/register' : '/auth/login', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ email, password }) });
      const account = await api<User>('/auth/me');
      setUser(account); setPassword('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Authentication failed'); }
    finally { setAuthBusy(false); }
  };
  const signOut = async () => {
    setError('');
    try {
      const { csrf_token } = await api<{csrf_token:string | null}>('/auth/csrf');
      await api('/auth/logout', {method:'POST', headers:csrf_token ? {'X-CSRF-Token':csrf_token}:{} });
      setUser(null); setDashboard(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to sign out'); }
  };

  if (busy) return <div className="center-screen"><div className="loading-mark"><Activity size={32}/></div><p>Loading Price-Warner...</p></div>;
  if (!user) return <div className="auth-page"><div className="auth-panel"><div className="brand"><span className="brand-icon"><Activity size={22}/></span><span>price<span className="brand-accent">warner</span></span></div><div className="auth-heading"><span className="eyebrow">YOUR PRICE INTELLIGENCE</span><h1>{register ? 'Create your account' : 'Welcome back'}</h1><p>Track products, monitor prices and never miss a meaningful drop.</p></div>{error && <div className="notice error"><CircleAlert size={16}/>{error}</div>}{config?.mode === 'local' ? <div className="notice">The local account is not initialized. Check the API logs.</div> : <form onSubmit={signIn} className="auth-form"><label>Email address<input type="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com" /></label><label>Password<input type="password" minLength={12} required value={password} onChange={e=>setPassword(e.target.value)} placeholder="At least 12 characters" /></label><button className="primary" disabled={authBusy} type="submit"><LogIn size={17}/>{authBusy ? 'Please wait...' : register ? 'Create account' : 'Sign in'}</button>{config?.registration_enabled && <button type="button" className="text-button" onClick={()=>{setRegister(!register);setError('')}}>{register ? 'Already have an account? Sign in' : 'New here? Create an account'}</button>}</form>}</div></div>;

  return <div className="app-shell">
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}><div className="brand"><span className="brand-icon"><Activity size={22}/></span><span>price<span className="brand-accent">warner</span></span><button className="mobile-close" onClick={()=>setMobileMenu(false)} aria-label="Close menu"><X size={20}/></button></div><div className="side-label">WORKSPACE</div><nav><a href="#dashboard" className={`nav-item ${page === 'overview' ? 'selected' : ''}`} onClick={()=>{setPage('overview');setMobileMenu(false)}}><LayoutDashboard size={19}/>Overview</a><a href="#products" className="nav-item" onClick={()=>{setPage('overview');setMobileMenu(false)}}><PackageSearch size={19}/>Monitored products</a><a href="#discover" className={`nav-item ${page === 'discover' ? 'selected' : ''}`} onClick={()=>{setPage('discover');setMobileMenu(false)}}><Plus size={19}/>Discover products</a><a href="#alerts" className={`nav-item ${page === 'alerts' ? 'selected' : ''}`} onClick={()=>{setPage('alerts');setMobileMenu(false)}}><Bell size={19}/>Alerts</a><a href="#settings" className={`nav-item ${page === 'settings' ? 'selected' : ''}`} onClick={()=>{setPage('settings');setMobileMenu(false)}}><Settings2 size={19}/>Settings</a></nav><div className="sidebar-foot"><div className="status-light"/><span>Self-hosted instance</span><small>Beta 1.2</small></div></aside>
    <div className="main-area"><header className="topbar"><button className="menu-button" aria-label="Open menu" onClick={()=>setMobileMenu(true)}><Menu size={22}/></button><span className="breadcrumb">Workspace <span>/</span> {page === 'discover' ? 'Discover products' : page === 'details' ? 'Product details' : page === 'settings' ? 'Settings' : page === 'alerts' ? 'Alerts' : 'Overview'}</span><div className="top-actions"><span className="account-pill"><ShieldCheck size={15}/>{config?.mode === 'local' ? 'Local mode' : user.email}</span>{config?.mode !== 'local' && <button className="icon-button" title="Sign out" aria-label="Sign out" onClick={signOut}><LogOut size={18}/></button>}</div></header>
      <main className="content" id="dashboard">{page === 'alerts' ? <Alerts stores={stores} onOpenProduct={id=>{setSelectedProductId(id);setPage('details')}}/> : page === 'settings' ? <Settings account={user}/> : page === 'discover' ? <Discover stores={stores} onCreated={loadData}/> : page === 'details' && selectedProductId !== null ? <ProductDetails id={selectedProductId} onBack={()=>{setPage('overview');setSelectedProductId(null)}} onSaved={loadData}/> : <><div className="page-heading"><div><div className="eyebrow">MONITORING OVERVIEW</div><h1>Your dashboard<span className="heading-dot">.</span></h1><p>A clear view of everything you're tracking, in one place.</p></div><button className="secondary refresh-button" onClick={refresh} disabled={refreshing}><RefreshCw size={17} className={refreshing ? 'spin' : ''}/>Refresh data</button></div>
      {error && <div className="notice error"><CircleAlert size={16}/>{error}<button onClick={()=>setError('')} aria-label="Dismiss"><X size={15}/></button></div>}
      <div className="stats-grid"><Stat label="Products monitored" value={dashboard?.summary.total ?? 0} detail="In your collection" icon={<Box size={20}/>} /><Stat label="Active tracking" value={dashboard?.summary.active ?? 0} detail="Currently monitored" icon={<Activity size={20}/>} /><Stat label="Recent price drops" value={dashboard?.summary.price_drops ?? 0} detail={changePeriod === 'last' ? 'Compared to previous check' : `Over ${changePeriod}`} icon={<TrendingDown size={20}/>} accent /><Stat label="Products with errors" value={dashboard?.summary.errors ?? 0} detail="Require attention" icon={<CircleAlert size={20}/>} /></div>
      <section className="products-section" id="products"><div className="section-heading"><div><div className="eyebrow">YOUR WATCHLIST</div><h2>Monitored products <span className="count">{matchingTotal}</span></h2></div><span className="section-subtitle">Live data from your Price-Warner instance</span></div><div className="filter-bar"><div className="search-field"><Search size={18}/><input value={query} onChange={e=>{setQuery(e.target.value);setWatchPage(1)}} placeholder="Search products or tags (e.g. RAM)..." aria-label="Search monitored products" /></div><label className="select-field"><span>Store</span><select value={storeFilter} onChange={e=>{setStoreFilter(e.target.value);setWatchPage(1)}} aria-label="Filter by store"><option value="all">All stores</option>{stores.map(store=><option key={store.id} value={store.id}>{store.name}</option>)}</select><ChevronDown size={15}/></label><label className="select-field"><span>Change</span><select value={changePeriod} onChange={e=>{setChangePeriod(e.target.value as ChangePeriod);setWatchPage(1)}} aria-label="Change comparison period"><option value="last">Last check</option><option value="24h">Last 24 hours</option><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option></select><ChevronDown size={15}/></label><label className="select-field"><span>Status</span><select value={statusFilter} onChange={e=>{setStatusFilter(e.target.value);setWatchPage(1)}} aria-label="Filter by status"><option value="all">All products</option><option value="active">Active</option><option value="drops">Price drops</option><option value="errors">Errors</option></select><ChevronDown size={15}/></label><label className="select-field"><span>Sort</span><select value={watchSort} onChange={e=>{setWatchSort(e.target.value as SortMode);setWatchPage(1)}} aria-label="Sort monitored products"><option value="newest">Recently added</option><option value="name_asc">Name A-Z</option><option value="name_desc">Name Z-A</option><option value="price_asc">Lowest price</option><option value="price_desc">Highest price</option><option value="change_asc">Largest drops</option><option value="change_desc">Largest increases</option><option value="last_checked">Recently checked</option></select><ChevronDown size={15}/></label></div>
        {!filtered.length ? <div className="empty-state"><div className="empty-icon"><PackageSearch size={28}/></div><h3>{dashboard?.summary.total ? 'No matching products' : 'Your watchlist is empty'}</h3><p>{dashboard?.summary.total ? 'Try a different search or filter.' : 'Products added through the existing API will appear here automatically.'}</p>{(query || storeFilter !== 'all' || statusFilter !== 'all') && <button className="secondary" onClick={()=>{setQuery('');setStoreFilter('all');setStatusFilter('all');setWatchPage(1)}}>Clear filters</button>}</div> : <div className="table-wrap"><table><thead><tr><th><button type="button" className={`sort-header ${watchSort.startsWith('name_')?'active':''}`} onClick={()=>toggleSort('name_asc','name_desc')}>PRODUCT </button></th><th>STORE</th><th><button type="button" className={`sort-header ${watchSort.startsWith('price_')?'active':''}`} onClick={()=>toggleSort('price_asc','price_desc')}>CURRENT PRICE </button></th><th><button type="button" className={`sort-header ${watchSort.startsWith('change_')?'active':''}`} onClick={()=>toggleSort('change_asc','change_desc')}>CHANGE ({changePeriod === 'last' ? 'LAST CHECK' : changePeriod.toUpperCase()}) </button></th><th>STATUS</th><th><button type="button" className={`sort-header ${watchSort==='last_checked'?'active':''}`} onClick={()=>{setWatchSort(watchSort==='last_checked'?'newest':'last_checked');setWatchPage(1)}}>LAST CHECKED</button></th><th></th></tr></thead><tbody>{filtered.map(product=><tr key={product.id}><td><div className="product-cell"><span className="product-thumb"><Box size={20}/>{product.image_proxy_url && <img src={product.image_proxy_url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={event=>{event.currentTarget.style.display='none'}} />}</span><div><button type="button" className="product-detail-trigger" title={`View details for ${product.name}`} onClick={()=>{setSelectedProductId(product.id);setPage('details')}}>{product.name}</button><small>Target drop {product.target_drop_percentage}%</small>{product.tags?.length>0 && <div className="product-tags">{product.tags.map(tag=><button type="button" className="product-tag" key={tag} title={`Show products tagged ${tag}`} onClick={()=>{setQuery(tag);setWatchPage(1)}}>{tag}</button>)}</div>}</div></div></td><td><span className="store-tag">{stores.find(s=>s.id===product.store_id)?.name ?? product.store_id}</span></td><td className="price-cell">{money(product.price, product.currency)}{product.availability === 'out_of_stock' && product.price !== null && <small className="muted">Last known price</small>}</td><td><Change value={product.price_change_percent}/></td><td><span className={`state ${product.last_error ? 'state-error' : product.availability === 'out_of_stock' ? 'state-oos' : product.is_active ? 'state-active':'state-paused'}`}><span/>{product.last_error ? 'Error' : product.availability === 'out_of_stock' ? 'Out of stock' : product.is_active ? 'Active' : 'Paused'}</span></td><td className="muted">{age(product.last_checked)}</td><td><a href={product.url} target="_blank" rel="noopener noreferrer" className="external" title="View product" aria-label={`View ${product.name}`}><ExternalLink size={17}/></a><button type="button" className="delete-action" title={`Remove ${product.name}`} aria-label={`Remove ${product.name}`} disabled={deletingId !== null} onClick={() => void removeProduct(product)}><Trash2 size={17}/></button></td></tr>)}</tbody></table></div>}
        <Pagination page={watchPage} pageSize={watchSize} total={matchingTotal}
          disabled={deletingId !== null} onPage={setWatchPage}
          onPageSize={size=>{setWatchSize(size);setWatchPage(1)}}/>
      </section></>}<footer className="app-footer"><span><CheckCircle2 size={14}/>Connected to Price-Warner API</span><span>Price-Warner B1.4</span></footer></main></div></div>;
}

function Stat({label,value,detail,icon,accent=false}:{label:string;value:number;detail:string;icon:React.ReactNode;accent?:boolean}) {return <div className={`stat ${accent?'stat-accent':''}`}><div className="stat-top"><span>{label}</span><div className="stat-icon">{icon}</div></div><div className="stat-value">{value.toLocaleString('en-US')}</div><div className="stat-detail"><Clock3 size={13}/>{detail}</div></div>}
function Change({value}:{value:number|null}) {if(value===null) return <span className="muted">No history</span>; if(value===0) return <span className="muted">0.0%</span>;const down=value<0;return <span className={`change ${down?'down':'up'}`}>{down?<ArrowDownRight size={16}/>:<ArrowUpRight size={16}/>} {Math.abs(value).toFixed(1)}%</span>}
