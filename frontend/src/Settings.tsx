import { useEffect, useState } from 'react';
import { Activity, BellRing, CheckCircle2, CircleAlert, Eye, EyeOff, Mail, RefreshCw, Save, Send, ShieldCheck } from 'lucide-react';

type SettingsData = {
  enabled: boolean;
  recipient_email: string | null;
  smtp_host: string;
  smtp_port: number;
  smtp_security: 'starttls' | 'ssl';
  smtp_username: string;
  has_password: boolean;
  from_email: string | null;
  cooldown_hours: number;
};
type Account = { email: string; mode: string; is_admin?: boolean };
type SystemHealth = {
  worker: {
    status: 'healthy' | 'degraded' | 'stale' | 'error' | 'running' | 'not_started';
    last_started_at: string | null;
    last_finished_at: string | null;
    last_success_at: string | null;
    last_cycle: {due: number; checked: number; failed: number; out_of_stock: number} | null;
  };
  summary: {monitored: number; errors: number; pending: number; overdue: number; failed_emails_7d: number};
  stores: {store_id: string; monitored: number; errors: number; pending: number; overdue: number}[];
  recent_errors: {product_id: number; product_name: string; store_id: string; error: string; last_checked: string | null}[];
};
const formatTime = (value: string | null) => value ? new Date(value + (value.endsWith('Z') ? '' : 'Z')).toLocaleString() : 'Never';
const request = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, { credentials: 'same-origin', ...init });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
};
async function csrfHeaders(): Promise<Record<string, string>> {
  const result = await request<{csrf_token: string | null}>('/auth/csrf');
  return { 'Content-Type': 'application/json', ...(result.csrf_token ? {'X-CSRF-Token': result.csrf_token} : {}) };
}

export default function Settings({account}: {account: Account}) {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [healthError, setHealthError] = useState('');
  const [healthBusy, setHealthBusy] = useState(false);
  const refreshHealth = async () => {
    setHealthBusy(true);
    try {
      setHealth(await request<SystemHealth>('/system/health'));
      setHealthError('');
    } catch (cause) {
      setHealthError(cause instanceof Error ? cause.message : 'Unable to load worker health');
    } finally {
      setHealthBusy(false);
    }
  };
  useEffect(() => {
    let active = true;
    request<SettingsData>('/notifications/settings')
      .then(data => { if (active) setSettings(data); })
      .catch(cause => { if (active) setError(cause instanceof Error ? cause.message : 'Unable to load settings'); });
    return () => {active = false;};
  }, []);
  useEffect(() => {
    let active = true;
    const poll = () => {
      request<SystemHealth>('/system/health')
        .then(value => {if (active) {setHealth(value); setHealthError('');}})
        .catch(cause => {if (active) setHealthError(cause instanceof Error ? cause.message : 'Unable to load worker health');});
    };
    poll();
    const timer = window.setInterval(poll, 60000);
    return () => {active = false; window.clearInterval(timer);};
  }, []);
  const update = <K extends keyof SettingsData>(key: K, value: SettingsData[K]) => setSettings(prev => prev ? {...prev, [key]: value} : prev);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!settings) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const payload: Record<string, unknown> = {
        enabled: settings.enabled,
        recipient_email: settings.recipient_email || null,
        smtp_host: settings.smtp_host,
        smtp_port: settings.smtp_port,
        smtp_security: settings.smtp_security,
        smtp_username: settings.smtp_username,
        from_email: settings.from_email || null,
        cooldown_hours: settings.cooldown_hours
      };
      if (password !== '') payload.smtp_password = password;
      const result = await request<SettingsData>('/notifications/settings', {method: 'PUT', headers: await csrfHeaders(), body: JSON.stringify(payload)});
      setSettings(result); setPassword(''); setNotice('Notification settings saved.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to save settings'); }
    finally { setBusy(false); }
  };
  const sendTest = async () => {
    setTesting(true); setError(''); setNotice('');
    try {
      await request('/notifications/test', {method:'POST', headers:await csrfHeaders()});
      setNotice('Test email sent. Check your inbox.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to send test'); }
    finally { setTesting(false); }
  };
  const changePassword = async (event: React.FormEvent) => {
    event.preventDefault(); setChangingPassword(true); setError(''); setNotice('');
    try {
      await request('/auth/password', {method: 'PUT', headers:await csrfHeaders(), body:JSON.stringify({current_password:currentPassword, new_password:newPassword})});
      setCurrentPassword(''); setNewPassword(''); setNotice('Password updated.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to update password'); }
    finally { setChangingPassword(false); }
  };
  return <>
    <div className="page-heading"><div><div className="eyebrow">ACCOUNT & NOTIFICATIONS</div><h1>Settings<span className="heading-dot">.</span></h1><p>Manage email alerts and account security.</p></div></div>
    {error && <div role="alert" className="notice error"><CircleAlert size={17}/>{error}</div>}
    {notice && <div role="status" className="notice"><CheckCircle2 size={17}/>{notice}</div>}
    <div className="settings-layout">
      <div className="detail-panel settings-card">
        <div className="settings-heading"><BellRing size={21}/><div><h2>Email notifications</h2><p>SMTP credentials are stored encrypted by the backend.</p></div></div>
        {settings ? <form onSubmit={save} className="settings-form">
          <label className="settings-check"><input type="checkbox" checked={settings.enabled} onChange={e=>update('enabled',e.target.checked)}/><span>Enable email notifications</span></label>
          <div className="settings-two">
            <label>Recipient email<input type="email" value={settings.recipient_email ?? ''} onChange={e=>update('recipient_email',e.target.value)}/></label>
            <label>Sender email<input type="email" value={settings.from_email ?? ''} onChange={e=>update('from_email',e.target.value)}/></label>
          </div>
          <div className="settings-two">
            <label>SMTP host<input value={settings.smtp_host} onChange={e=>update('smtp_host',e.target.value)} placeholder="smtp.example.com"/></label>
            <label>SMTP port<input type="number" min="1" max="65535" required value={settings.smtp_port} onChange={e=>update('smtp_port',Number(e.target.value))}/></label>
          </div>
          <div className="settings-two">
            <label>Connection security<select value={settings.smtp_security} onChange={e=>update('smtp_security',e.target.value as 'ssl'|'starttls')}><option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option></select></label>
            <label>Cooldown (hours)<input type="number" min="1" max="720" required value={settings.cooldown_hours} onChange={e=>update('cooldown_hours',Number(e.target.value))}/></label>
          </div>
          <label>SMTP username<input autoComplete="username" value={settings.smtp_username} onChange={e=>update('smtp_username',e.target.value)}/></label>
          <label>SMTP password {settings.has_password && <span className="settings-help">Saved. Leave empty to keep the existing password.</span>}
            <div className="settings-password"><input type={showPassword ? 'text' : 'password'} value={password} autoComplete="new-password" onChange={e=>setPassword(e.target.value)} placeholder={settings.has_password?'Keep existing password':'Enter SMTP password'}/><button type="button" className="icon-button" onClick={()=>setShowPassword(v=>!v)} aria-label={showPassword?'Hide password':'Show password'}>{showPassword?<EyeOff size={17}/>:<Eye size={17}/>}</button></div>
          </label>
          <div className="settings-actions"><button className="primary" disabled={busy} type="submit"><Save size={16}/>{busy?'Saving...':'Save settings'}</button><button className="secondary" type="button" disabled={busy || testing} onClick={sendTest}><Send size={16}/>{testing?'Sending...':'Send test email'}</button></div>
          <p className="settings-help">Save your settings before sending a test. The server requires SMTP_ENCRYPTION_KEY to store a password.</p>
        </form> : <p className="settings-help">Loading notification settings...</p>}
      </div>
      <div className="settings-side">
        <div className="detail-panel settings-card">
          <div className="settings-heading"><Activity size={21}/><div><h2>Monitoring health</h2><p>Worker heartbeat and checks for your products.</p></div></div>
          <button className="secondary" type="button" disabled={healthBusy} onClick={refreshHealth}><RefreshCw size={15}/>{healthBusy ? 'Refreshing...' : 'Refresh status'}</button>
          {healthError && <p className="settings-help" role="alert">{healthError}</p>}
          {health ? <>
            <div className="account-detail"><span>Worker</span><strong>{health.worker.status.replace('_', ' ')}</strong></div>
            <div className="account-detail"><span>Last cycle finished</span><strong>{formatTime(health.worker.last_finished_at)}</strong></div>
            <div className="account-detail"><span>Active monitors</span><strong>{health.summary.monitored}</strong></div>
            <div className="account-detail"><span>Errors / overdue / pending</span><strong>{health.summary.errors} / {health.summary.overdue} / {health.summary.pending}</strong></div>
            <div className="account-detail"><span>Failed emails (7 days)</span><strong>{health.summary.failed_emails_7d}</strong></div>
            {health.worker.last_cycle && <p className="settings-help">Last cycle: {health.worker.last_cycle.checked} checked, {health.worker.last_cycle.failed} failed, {health.worker.last_cycle.out_of_stock} out of stock.</p>}
            {health.stores.length > 0 && <><h3>Stores</h3>{health.stores.map(store => <div className="account-detail" key={store.store_id}><span>{store.store_id}</span><strong>{store.monitored} products, {store.errors} errors</strong></div>)}</>}
            {health.recent_errors.length > 0 && <><h3>Recent issues</h3>{health.recent_errors.slice(0, 5).map(item => <p className="settings-help" key={item.product_id}><strong>{item.product_name}</strong>: {item.error}</p>)}</>}
          </> : <p className="settings-help">Loading monitoring health...</p>}
        </div>
        <div className="detail-panel settings-card"><div className="settings-heading"><ShieldCheck size={21}/><div><h2>Account</h2><p>Your current session.</p></div></div><div className="account-detail"><span>Email</span><strong>{account.email}</strong></div><div className="account-detail"><span>Authentication mode</span><strong>{account.mode}</strong></div>{account.is_admin && <div className="account-detail"><span>Role</span><strong>Administrator</strong></div>}</div>
        {account.mode !== 'local' && <div className="detail-panel settings-card"><div className="settings-heading"><Mail size={21}/><div><h2>Change password</h2><p>Update the password for this account.</p></div></div><form onSubmit={changePassword} className="settings-form"><label>Current password<input type="password" autoComplete="current-password" required minLength={12} value={currentPassword} onChange={e=>setCurrentPassword(e.target.value)}/></label><label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={newPassword} onChange={e=>setNewPassword(e.target.value)}/></label><button className="secondary" type="submit" disabled={changingPassword}>{changingPassword?'Updating...':'Update password'}</button></form></div>}
      </div>
    </div>
  </>;
}
