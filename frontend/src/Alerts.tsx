import { useEffect, useState } from 'react';
import { ArrowDownRight, Bell, Check, CheckCheck, ChevronLeft, ChevronRight, CircleAlert, ExternalLink, RefreshCw } from 'lucide-react';

type Store = { id: string; name: string };
type AlertStatus = 'sent' | 'failed' | 'pending';
type AlertItem = {
  id: number;
  product_id: number;
  product_name: string;
  product_url: string;
  store_id: string;
  store_name: string;
  price: number | null;
  currency: string;
  reference_price: number | null;
  previous_alert_price: number | null;
  change_percent: number | null;
  reason: string | null;
  kind: string | null;
  status: AlertStatus;
  created_at: string;
  sent_at: string | null;
  read: boolean;
  error: string | null;
};
type AlertResponse = {
  items: AlertItem[];
  total: number;
  limit: number;
  offset: number;
  summary: { total: number; sent: number; failed: number; pending: number; unread: number };
};
type Props = { stores: Store[]; onOpenProduct: (id: number) => void };

const formatPrice = (value: number | null, currency: string) =>
  value === null ? 'Unavailable' : new Intl.NumberFormat('pt-BR', { style: 'currency', currency }).format(value);
const formatDate = (value: string | null) => {
  if (!value) return 'Not yet';
  const date = new Date(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? 'Unknown' : new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
};
const kinds: Record<string, string> = {
  first_drop: 'First opportunity',
  additional_drop: 'Further price drop',
  recovery: 'New promotion cycle',
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin', ...init });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

async function authenticatedWrite(url: string, method: string) {
  const token = await request<{ csrf_token: string | null }>('/auth/csrf');
  return request(url, { method, headers: token.csrf_token ? { 'X-CSRF-Token': token.csrf_token } : {} });
}

export default function Alerts({ stores, onOpenProduct }: Props) {
  const [status, setStatus] = useState('all');
  const [period, setPeriod] = useState('30d');
  const [storeId, setStoreId] = useState('all');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<AlertResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams({ status, period, store_id: storeId, q: search, limit: '25', offset: String(offset) });
    setLoading(true);
    request<AlertResponse>(`/alerts?${params}`).then(result => {
      if (alive) { setData(result); setError(''); }
    }).catch(cause => {
      if (alive) setError(cause instanceof Error ? cause.message : 'Unable to load alerts');
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [status, period, storeId, search, offset, revision]);

  const write = async (path: string, method: string) => {
    setWriting(true); setError('');
    try { await authenticatedWrite(path, method); setRevision(current => current + 1); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to update alerts'); }
    finally { setWriting(false); }
  };

  const summary = data?.summary;
  return <>
    <div className="page-heading">
      <div><div className="eyebrow">NOTIFICATION HISTORY</div><h1>Your alerts<span className="heading-dot">.</span></h1><p>Review price opportunities and email delivery for your monitorings.</p></div>
      <button className="secondary refresh-button" onClick={() => setRevision(current => current + 1)} disabled={loading}>
        <RefreshCw size={17} className={loading ? 'spin' : ''}/>Refresh
      </button>
    </div>
    {error && <div className="notice error"><CircleAlert size={16}/>{error}</div>}
    <div className="alerts-summary">
      <div><span>Total alerts</span><strong>{summary?.total ?? 0}</strong></div>
      <div><span>Emails sent</span><strong>{summary?.sent ?? 0}</strong></div>
      <div><span>Delivery failures</span><strong>{summary?.failed ?? 0}</strong></div>
      <div><span>Unread alerts</span><strong>{summary?.unread ?? 0}</strong></div>
    </div>
    <section className="products-section alerts-section">
      <div className="section-heading"><div><div className="eyebrow">PRICE OPPORTUNITIES</div><h2>Alert history <span className="count">{data?.total ?? 0}</span></h2></div>
        <button className="secondary alerts-mark-all" disabled={writing || !summary?.unread} onClick={() => void write('/alerts/read-all', 'POST')}><CheckCheck size={16}/>Mark all as read</button>
      </div>
      <div className="filter-bar alerts-filters">
        <input className="alerts-search" aria-label="Search alert products" value={search} placeholder="Search by product name..." onChange={e => { setSearch(e.target.value); setOffset(0); }}/>
        <label className="alerts-select">Status<select aria-label="Filter alerts by status" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="all">All statuses</option><option value="sent">Sent</option><option value="failed">Failed</option><option value="pending">Pending</option></select></label>
        <label className="alerts-select">Period<select aria-label="Filter alerts by period" value={period} onChange={e => { setPeriod(e.target.value); setOffset(0); }}><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option><option value="90d">Last 90 days</option><option value="all">All time</option></select></label>
        <label className="alerts-select">Store<select aria-label="Filter alerts by store" value={storeId} onChange={e => { setStoreId(e.target.value); setOffset(0); }}><option value="all">All stores</option>{stores.map(store => <option key={store.id} value={store.id}>{store.name}</option>)}</select></label>
      </div>
      {loading && !data ? <div className="history-empty">Loading alerts...</div> : !data?.items.length ? <div className="empty-state"><div className="empty-icon"><Bell size={28}/></div><h3>No alerts found</h3><p>{data?.summary.total ? 'Try another filter or period.' : 'Email delivery attempts will appear here when price opportunities trigger notifications.'}</p></div> :
        <div className="alerts-list">{data.items.map(item => <article className={`alert-entry ${item.read ? '' : 'alert-unread'}`} key={item.id}>
          <div className="alert-main"><div className="alert-heading"><span className={`alert-status alert-${item.status}`}>{item.status === 'sent' ? 'Email sent' : item.status === 'failed' ? 'Delivery failed' : 'Pending'}</span>{!item.read && <span className="alert-new">Unread</span>}<span className="alert-timestamp">{formatDate(item.sent_at ?? item.created_at)}</span></div>
            <button type="button" className="alert-product" onClick={() => onOpenProduct(item.product_id)}>{item.product_name}</button>
            <div className="alert-subline"><span>{item.store_name}</span><span>{item.kind ? kinds[item.kind] ?? item.kind : 'Price opportunity'}</span></div>
            {item.reason && <p className="alert-reason">{item.reason}</p>}
            {item.error && <p className="alert-error">Delivery error: {item.error}</p>}
          </div>
          <div className="alert-aside"><strong>{formatPrice(item.price, item.currency)}</strong>
            {item.change_percent !== null && <span className="alert-drop"><ArrowDownRight size={15}/>{Math.abs(item.change_percent).toFixed(1)}% vs reference</span>}
            {item.reference_price !== null && <span className="alert-reference">Reference: {formatPrice(item.reference_price, item.currency)}</span>}
            <div className="alert-actions">{!item.read && <button className="secondary" disabled={writing} onClick={() => void write(`/alerts/${item.id}/read`, 'PATCH')}><Check size={15}/>Mark read</button>}
              <a href={item.product_url} target="_blank" rel="noopener noreferrer" className="alert-external"><ExternalLink size={15}/>Store</a></div>
          </div>
        </article>)}</div>}
      {data && data.total > data.limit && <div className="alerts-pages"><span>Showing {offset + 1} to {Math.min(offset + data.limit, data.total)} of {data.total}</span><div><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - data.limit))}><ChevronLeft size={16}/>Previous</button><button className="secondary" disabled={offset + data.limit >= data.total || loading} onClick={() => setOffset(offset + data.limit)}>Next<ChevronRight size={16}/></button></div></div>}
    </section>
  </>;
}
