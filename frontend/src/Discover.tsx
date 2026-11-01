import { useEffect, useState } from 'react';
import { CircleAlert, Link2, Plus, Search } from 'lucide-react';

type Store = {id:string; name:string; currency:string; supports_search:boolean};
type SearchItem = {name:string; url:string; price:number|null; image_url:string|null; store_id:string};
type Variant = {asin:string;label:string;url:string;selected:boolean;display_price:string|null};
type Preview = {variants?:Variant[];ok:boolean; status:string; reason:string|null; name:string|null; url:string; price:number|null; currency:string; availability:string; store_id:string};

async function request<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(path, {credentials:'same-origin',...init});
  const data = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
  return data as T;
}

export default function Discover({stores,onCreated}:{stores:Store[];onCreated:()=>Promise<void>}) {
  const [storeId,setStoreId] = useState('');
  const [query,setQuery] = useState('');
  const [url,setUrl] = useState('');
  const [results,setResults] = useState<SearchItem[]>([]);
  const [preview,setPreview] = useState<Preview|null>(null);
  const [variantLoading,setVariantLoading] = useState(false);
  const [interval,setInterval] = useState(60);
  const [drop,setDrop] = useState(10);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState('');
  const [message,setMessage] = useState('');
  useEffect(()=>{if (!stores.some(s=>s.id===storeId)) setStoreId(stores[0]?.id ?? '');},[stores,storeId]);
  const store = stores.find(s=>s.id===storeId);
  const search = async (event:React.FormEvent) => {
    event.preventDefault();setLoading(true);setError('');setMessage('');setResults([]);
    try {const params = new URLSearchParams({q:query.trim(),store_id:storeId});const data=await request<SearchItem[]>(`/products/search-external?${params}`);setResults(data);if (!data.length) setMessage('No results found for this search.');}
    catch(e){setError(e instanceof Error?e.message:'Search failed');}finally{setLoading(false);}
  };
  const inspect = async (event:React.FormEvent) => {
    event.preventDefault();setLoading(true);setError('');setMessage('');setPreview(null);
    try {const params=new URLSearchParams({url:url.trim(),store_id:storeId});const data=await request<Preview>(`/products/preview?${params}`);setPreview(data);if(!data.ok)setError(data.reason||`Preview unavailable (${data.status})`);}
    catch(e){setError(e instanceof Error?e.message:'Preview failed');}finally{setLoading(false);}
  };
  const selectVariant = async (variant:Variant) => {
    if (!preview || variant.url === preview.url) return;
    setVariantLoading(true);setError('');setMessage('');
    const previous = preview;
    setPreview(null);
    try {
      const params = new URLSearchParams({url:variant.url,store_id:storeId});
      const data = await request<Preview>(`/products/preview?${params}`);
      setPreview(data);setUrl(variant.url);
      if (!data.ok) setError(data.reason||`Preview unavailable (${data.status})`);
    } catch(e) {
      setPreview(previous);
      setError(e instanceof Error?e.message:'Unable to load this edition');
    } finally {setVariantLoading(false);}
  };
  const add = async (item:{name:string;url:string;store_id:string}) => {
    setLoading(true);setError('');setMessage('');
    try {
      const {csrf_token}=await request<{csrf_token:string|null}>('/auth/csrf');
      await request('/products',{method:'POST',headers:{'Content-Type':'application/json',...(csrf_token?{'X-CSRF-Token':csrf_token}:{})},body:JSON.stringify({name:item.name,url:item.url,store_id:item.store_id,interval,target_drop_percentage:drop})});
      await onCreated();setMessage('Product added to your watchlist.');setPreview(null);
    }catch(e){setError(e instanceof Error?e.message:'Unable to add product');}finally{setLoading(false);}
  };
  const money=(value:number|null)=>value===null?'Price unavailable':new Intl.NumberFormat('pt-BR',{style:'currency',currency:store?.currency||'BRL'}).format(value);
  return <>
    <div className="page-heading"><div><div className="eyebrow">PRODUCT DISCOVERY</div><h1>Discover products<span className="heading-dot">.</span></h1><p>Search supported stores or preview a product URL.</p></div></div>
    <div className="discovery-panel">
      <label className="discovery-label">Store<select value={storeId} onChange={e=>{setStoreId(e.target.value);setResults([]);setPreview(null);setError('');setMessage('');}}>{stores.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label>
      {store?.supports_search ? <form className="discovery-form" onSubmit={search}><label className="discovery-label">Search by product name<input minLength={2} required value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search products..."/></label><button type="submit" className="primary" disabled={loading}><Search size={17}/>Search</button></form> : <div className="discovery-hint">This store currently supports product URLs only. Name search is not available.</div>}
      <form className="discovery-form" onSubmit={inspect}><label className="discovery-label">Product URL<input type="url" required value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://www.amazon.com.br/dp/..."/></label><button className="secondary" disabled={loading} type="submit"><Link2 size={17}/>Preview URL</button></form>
      <div className="discovery-options"><label>Check interval (minutes)<input type="number" value={interval} min={1} max={10080} onChange={e=>setInterval(Number(e.target.value))}/></label><label>Target price drop (%)<input type="number" value={drop} min={0} max={100} step={0.5} onChange={e=>setDrop(Number(e.target.value))}/></label></div>
      {error && <div className="notice error"><CircleAlert size={16}/>{error}</div>}{message && <div className="notice">{message}</div>}
    </div>
    {preview && <section className="discovery-results"><h2>Product preview</h2><article className="discovery-card"><div><h3>{preview.name||'Product unavailable'}</h3><strong>{money(preview.price)}</strong><p>{preview.availability} · {preview.status}</p>{(preview.variants?.length ?? 0)>1 && <label className="discovery-label">Edition or format<select aria-label="Edition or format" value={preview.url} disabled={loading||variantLoading} onChange={e=>{const variant=preview.variants?.find(v=>v.url===e.target.value);if(variant) void selectVariant(variant);}}>{preview.variants?.map(v=><option key={v.asin} value={v.url}>{v.label}{v.selected?' (current)':''}</option>)}</select><small>Choosing a format loads its own product page and price before monitoring.</small></label>}</div><button className="primary" disabled={loading||variantLoading||!preview.ok||!preview.name} onClick={()=>preview.name && add({name:preview.name,url:preview.url,store_id:preview.store_id})}><Plus size={17}/>Monitor product</button></article></section>}
    {store?.supports_search && <section className="discovery-results"><h2>Search results <span className="count">{results.length}</span></h2><div className="discovery-grid">{results.map(item=><article className="discovery-card" key={item.url}><div className="discovery-result-info">{item.image_url && <img src={item.image_url} alt="" loading="lazy" referrerPolicy="no-referrer"/>}<div><h3>{item.name}</h3><strong>{money(item.price)}</strong><p><a href={item.url} rel="noopener noreferrer" target="_blank">View at store</a></p></div></div><button className="primary" disabled={loading||!item.url} onClick={()=>add(item)}><Plus size={17}/>Monitor product</button></article>)}</div></section>}
  </>;
}
