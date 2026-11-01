import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowUpRight, CheckCircle2, CircleAlert, ExternalLink, Save } from 'lucide-react';

type Observation = { id:number; price:number|null; availability:string|null; fetched_at:string; strategy_used:string|null };
type Details = { id:number; name:string; url:string; store_id:string; image_url:string|null; last_checked:string|null; last_error:string|null; interval:number; target_drop_percentage:number; is_active:boolean; history:Observation[] };
const formatMoney = (price:number|null) => price===null?'Unavailable':new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(price);
const formatDate = (date:string) => new Date(date.endsWith('Z')?date:`${date}Z`).toLocaleString('pt-BR');

function HistoryChart({history}:{history:Observation[]}) {
  const values = history.filter((row):row is Observation & {price:number}=>row.price!==null && row.price>0);
  if (!values.length) return <div className="history-empty">No recorded prices yet. The chart will appear after the worker collects prices.</div>;
  const width=840,height=250,padding=36;
  const minimum=Math.min(...values.map(row=>row.price));
  const maximum=Math.max(...values.map(row=>row.price));
  const span=Math.max(maximum-minimum,minimum*0.02,0.01);
  const points=values.map((row,index)=>({
    x:padding+(values.length===1?0.5:index/(values.length-1))*(width-padding*2),
    y:height-padding-((row.price-minimum+span*0.1)/(span*1.2))*(height-padding*2),
    row,
  }));
  const path=points.map((point,index)=>`${index?'L':'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
  return <div className="history-chart"><svg role="img" aria-label="Price history line chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
    {[0,1,2,3,4].map(step=><line key={step} x1={padding} y1={padding+step*(height-2*padding)/4} x2={width-padding} y2={padding+step*(height-2*padding)/4} stroke="#36404e" strokeDasharray="4 7"/>)}
    <path d={path} fill="none" stroke="#c9ff68" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round"/>
    {points.map(point=><circle key={point.row.id} cx={point.x} cy={point.y} r="4" fill="#c9ff68"><title>{`${formatDate(point.row.fetched_at)}: ${formatMoney(point.row.price)}`}</title></circle>)}
    <text x={padding} y={height-6} fill="#94a0ae" fontSize="12">{formatDate(values[0].fetched_at)}</text>
    <text x={width-padding} y={height-6} textAnchor="end" fill="#94a0ae" fontSize="12">{formatDate(values[values.length-1].fetched_at)}</text>
  </svg></div>;
}

export default function ProductDetails({id,onBack,onSaved}:{id:number;onBack:()=>void;onSaved:()=>Promise<void>}) {
  const [data,setData]=useState<Details|null>(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [saved,setSaved]=useState(false);
  const [interval,setInterval]=useState(60);
  const [drop,setDrop]=useState(10);
  const [active,setActive]=useState(true);
  useEffect(()=>{
    let alive=true;
    setLoading(true);setError('');setSaved(false);
    fetch(`/products/${id}/details`,{credentials:'same-origin'}).then(async response=>{
      if(!response.ok)throw new Error(`Unable to load details (${response.status})`);
      return response.json() as Promise<Details>;
    }).then(result=>{if(alive){setData(result);setInterval(result.interval);setDrop(result.target_drop_percentage);setActive(result.is_active)}})
      .catch(cause=>{if(alive)setError(cause instanceof Error?cause.message:'Unable to load details')})
      .finally(()=>{if(alive)setLoading(false)});
    return ()=>{alive=false};
  },[id]);
  const values=useMemo(()=>data?.history.filter(row=>row.price!==null&&row.price>0).map(row=>row.price as number)??[],[data]);
  const save=async(event:React.FormEvent)=>{
    event.preventDefault();setError('');setSaved(false);setSaving(true);
    try{
      const csrfResponse=await fetch('/auth/csrf',{credentials:'same-origin'});
      if(!csrfResponse.ok)throw new Error('Unable to retrieve CSRF token');
      const {csrf_token}=await csrfResponse.json() as {csrf_token:string|null};
      const response=await fetch(`/products/${id}/monitoring`,{method:'PATCH',credentials:'same-origin',headers:{'Content-Type':'application/json',...(csrf_token?{'X-CSRF-Token':csrf_token}:{})},body:JSON.stringify({interval,target_drop_percentage:drop,is_active:active})});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(typeof body.detail==='string'?body.detail:`Unable to save (${response.status})`)}
      setData(previous=>previous?{...previous,interval,target_drop_percentage:drop,is_active:active}:null);
      setSaved(true);await onSaved();
    }catch(cause){setError(cause instanceof Error?cause.message:'Unable to save settings')}
    finally{setSaving(false)}
  };
  return <section className="details-page">
    <button className="secondary detail-back" type="button" onClick={onBack}><ArrowLeft size={16}/>Back to dashboard</button>
    {loading&&<p className="muted">Loading product details...</p>}
    {error&&<div className="notice error"><CircleAlert size={16}/>{error}</div>}
    {data&&<>
      <div className="detail-title"><div><span className="eyebrow">PRODUCT DETAILS / {data.store_id.toUpperCase()}</span><h1>{data.name}</h1><p>{data.is_active?'Monitoring active':'Monitoring paused'} · {data.history.length} saved observations</p></div><a className="secondary detail-link" href={data.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={16}/>View at store</a></div>
      <div className="detail-metrics"><div><span>Latest price</span><strong>{formatMoney(values.length?values[values.length-1]:null)}</strong></div><div><span>Lowest recorded</span><strong>{formatMoney(values.length?Math.min(...values):null)}</strong></div><div><span>Highest recorded</span><strong>{formatMoney(values.length?Math.max(...values):null)}</strong></div><div><span>Target drop</span><strong>{data.target_drop_percentage}%</strong></div></div>
      {data.last_error&&<div className="notice error"><CircleAlert size={16}/>Last check error: {data.last_error}</div>}
      <div className="detail-columns"><section className="detail-panel"><div className="detail-panel-head"><h2>Price history</h2><span>Last {data.history.length} observations</span></div><HistoryChart history={data.history}/><p className="detail-footnote">Recorded prices are shared across monitors of this product. Alerts and settings remain private to your account.</p></section>
      <form className="detail-panel detail-settings" onSubmit={save}><h2>Monitoring settings</h2><label>Check interval (minutes)<input type="number" min={1} max={10080} required value={interval} onChange={e=>setInterval(Number(e.target.value))}/></label><label>Target price drop (%)<input type="number" min={0.1} max={100} step={0.1} required value={drop} onChange={e=>setDrop(Number(e.target.value))}/></label><label className="detail-toggle"><input type="checkbox" checked={active} onChange={e=>setActive(e.target.checked)}/>Enable monitoring</label><p className="detail-footnote">Further drops of at least 5% from the last emailed price can trigger another alert while the target condition holds.</p><button type="submit" className="primary" disabled={saving}><Save size={16}/>{saving?'Saving...':'Save settings'}</button>{saved&&<p className="detail-success"><CheckCircle2 size={15}/>Settings saved successfully</p>}</form></div>
      <section className="detail-panel detail-observations"><h2>Recent observations</h2>{data.history.length===0?<p className="muted">No observations yet.</p>:<div className="detail-history-scroll"><table><thead><tr><th>CHECKED AT</th><th>PRICE</th><th>AVAILABILITY</th><th>STRATEGY</th></tr></thead><tbody>{[...data.history].reverse().slice(0,20).map(row=><tr key={row.id}><td>{formatDate(row.fetched_at)}</td><td>{formatMoney(row.price)}</td><td>{row.availability||'Unknown'}</td><td>{row.strategy_used||'Not available'}</td></tr>)}</tbody></table></div>}</section>
    </>}
  </section>;
}
