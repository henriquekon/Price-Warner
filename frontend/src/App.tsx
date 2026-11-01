import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, Bell, Box, CheckCircle2, ChevronDown, CircleAlert, Clock3, ExternalLink, LayoutDashboard, LogIn, LogOut, Menu, PackageSearch, RefreshCw, Search, Settings2, ShieldCheck, TrendingDown, X } from 'lucide-react';

type Product = { id: number; name: string; url: string; store_id: string; image_url: string | null; is_active: boolean; last_checked: string | null; last_error: string | null; price: number | null; previous_price: number | null; price_change_percent: number | null; availability: string; currency: string; target_drop_percentage: number; interval: number };
type Dashboard = { summary: { total: number; active: number; price_drops: number; errors: number }; products: Product[] };
type Store = { id: string; name: string; supports_search: boolean; currency: string };
type Config = { mode: 'local' | 'private' | 'public'; registration_enabled: boolean };
type User = { email: string; mode: string };

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
  const [mobileMenu, setMobileMenu] = useState(false);

  const loadData = async () => {
    const [data, storeData] = await Promise.all([api<Dashboard>('/dashboard'), api<Store[]>('/stores')]);
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
          await loadData();
        } catch (cause) {
          if (authConfig.mode === 'local') throw cause;
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Failed to load the application');
      } finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, []);

  const filtered = useMemo(() => (dashboard?.products ?? []).filter(product => {
    if (storeFilter !== 'all' && product.store_id !== storeFilter) return false;
    if (statusFilter === 'active' && !product.is_active) return false;
    if (statusFilter === 'errors' && !product.last_error) return false;
    if (statusFilter === 'drops' && !(product.price_change_percent !== null && product.price_change_percent < 0)) return false;
    return `${product.name} ${product.store_id}`.toLowerCase().includes(query.toLowerCase());
  }), [dashboard, storeFilter, statusFilter, query]);

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
      setUser(account); setPassword(''); await loadData();
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
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}><div className="brand"><span className="brand-icon"><Activity size={22}/></span><span>price<span className="brand-accent">warner</span></span><button className="mobile-close" onClick={()=>setMobileMenu(false)} aria-label="Close menu"><X size={20}/></button></div><div className="side-label">WORKSPACE</div><nav><a href="#dashboard" className="nav-item selected" onClick={()=>setMobileMenu(false)}><LayoutDashboard size={19}/>Overview</a><a href="#products" className="nav-item" onClick={()=>setMobileMenu(false)}><PackageSearch size={19}/>Monitored products</a><div className="nav-item disabled-item"><Bell size={19}/>Alerts <span>SOON</span></div><div className="nav-item disabled-item"><Settings2 size={19}/>Settings <span>SOON</span></div></nav><div className="sidebar-foot"><div className="status-light"/><span>Self-hosted instance</span><small>Stage 6.2</small></div></aside>
    <div className="main-area"><header className="topbar"><button className="menu-button" aria-label="Open menu" onClick={()=>setMobileMenu(true)}><Menu size={22}/></button><span className="breadcrumb">Workspace <span>/</span> Overview</span><div className="top-actions"><span className="account-pill"><ShieldCheck size={15}/>{config?.mode === 'local' ? 'Local mode' : user.email}</span>{config?.mode !== 'local' && <button className="icon-button" title="Sign out" aria-label="Sign out" onClick={signOut}><LogOut size={18}/></button>}</div></header>
      <main className="content" id="dashboard"><div className="page-heading"><div><div className="eyebrow">MONITORING OVERVIEW</div><h1>Your dashboard<span className="heading-dot">.</span></h1><p>A clear view of everything you're tracking, in one place.</p></div><button className="secondary refresh-button" onClick={refresh} disabled={refreshing}><RefreshCw size={17} className={refreshing ? 'spin' : ''}/>Refresh data</button></div>
      {error && <div className="notice error"><CircleAlert size={16}/>{error}<button onClick={()=>setError('')} aria-label="Dismiss"><X size={15}/></button></div>}
      <div className="stats-grid"><Stat label="Products monitored" value={dashboard?.summary.total ?? 0} detail="In your collection" icon={<Box size={20}/>} /><Stat label="Active tracking" value={dashboard?.summary.active ?? 0} detail="Currently monitored" icon={<Activity size={20}/>} /><Stat label="Recent price drops" value={dashboard?.summary.price_drops ?? 0} detail="Compared to previous check" icon={<TrendingDown size={20}/>} accent /><Stat label="Products with errors" value={dashboard?.summary.errors ?? 0} detail="Require attention" icon={<CircleAlert size={20}/>} /></div>
      <section className="products-section" id="products"><div className="section-heading"><div><div className="eyebrow">YOUR WATCHLIST</div><h2>Monitored products <span className="count">{filtered.length}</span></h2></div><span className="section-subtitle">Live data from your Price-Warner instance</span></div><div className="filter-bar"><div className="search-field"><Search size={18}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search your products..." aria-label="Search monitored products" /></div><label className="select-field"><span>Store</span><select value={storeFilter} onChange={e=>setStoreFilter(e.target.value)} aria-label="Filter by store"><option value="all">All stores</option>{stores.map(store=><option key={store.id} value={store.id}>{store.name}</option>)}</select><ChevronDown size={15}/></label><label className="select-field"><span>Status</span><select value={statusFilter} onChange={e=>setStatusFilter(e.target.value)} aria-label="Filter by status"><option value="all">All products</option><option value="active">Active</option><option value="drops">Price drops</option><option value="errors">Errors</option></select><ChevronDown size={15}/></label></div>
        {!filtered.length ? <div className="empty-state"><div className="empty-icon"><PackageSearch size={28}/></div><h3>{dashboard?.summary.total ? 'No matching products' : 'Your watchlist is empty'}</h3><p>{dashboard?.summary.total ? 'Try a different search or filter.' : 'Products added through the existing API will appear here automatically.'}</p>{(query || storeFilter !== 'all' || statusFilter !== 'all') && <button className="secondary" onClick={()=>{setQuery('');setStoreFilter('all');setStatusFilter('all')}}>Clear filters</button>}</div> : <div className="table-wrap"><table><thead><tr><th>PRODUCT</th><th>STORE</th><th>CURRENT PRICE</th><th>CHANGE</th><th>STATUS</th><th>LAST CHECKED</th><th></th></tr></thead><tbody>{filtered.map(product=><tr key={product.id}><td><div className="product-cell"><span className="product-thumb">{product.image_url ? <img src={product.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <Box size={20}/>}</span><div><strong title={product.name}>{product.name}</strong><small>Target drop {product.target_drop_percentage}%</small></div></div></td><td><span className="store-tag">{stores.find(s=>s.id===product.store_id)?.name ?? product.store_id}</span></td><td className="price-cell">{money(product.price, product.currency)}</td><td><Change value={product.price_change_percent}/></td><td><span className={`state ${product.last_error ? 'state-error' : product.is_active ? 'state-active':'state-paused'}`}><span/>{product.last_error ? 'Error' : product.is_active ? 'Active' : 'Paused'}</span></td><td className="muted">{age(product.last_checked)}</td><td><a href={product.url} target="_blank" rel="noopener noreferrer" className="external" title="View product" aria-label={`View ${product.name}`}><ExternalLink size={17}/></a></td></tr>)}</tbody></table></div>}
      </section><footer className="app-footer"><span><CheckCircle2 size={14}/>Connected to Price-Warner API</span><span>Price-Warner 0.6.2</span></footer></main></div></div>;
}

function Stat({label,value,detail,icon,accent=false}:{label:string;value:number;detail:string;icon:React.ReactNode;accent?:boolean}) {return <div className={`stat ${accent?'stat-accent':''}`}><div className="stat-top"><span>{label}</span><div className="stat-icon">{icon}</div></div><div className="stat-value">{value.toLocaleString('en-US')}</div><div className="stat-detail"><Clock3 size={13}/>{detail}</div></div>}
function Change({value}:{value:number|null}) {if(value===null) return <span className="muted">No history</span>; if(value===0) return <span className="muted">0.0%</span>;const down=value<0;return <span className={`change ${down?'down':'up'}`}>{down?<ArrowDownRight size={16}/>:<ArrowUpRight size={16}/>} {Math.abs(value).toFixed(1)}%</span>}
