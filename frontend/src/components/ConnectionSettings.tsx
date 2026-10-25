import { useEffect, useRef, useState } from 'react'
import Modal from './Modal'

interface Profile {
  configured: boolean; imported: boolean; host: string; port: number; username: string
  auth_method: 'password' | 'key'; identity_file: string; legacy_rsa: boolean
  has_password: boolean; remember_password: boolean; remote_base: string
  environment_script: string; virtuoso_bin: string; spectre_bin: string; cadence_cds_lib: string; cmn018_model_file: string
}
const empty: Profile = { configured: false, imported: false, host: '101.6.64.74', port: 35167, username: '', auth_method: 'password', identity_file: '', legacy_rsa: false, has_password: false, remember_password: false, remote_base: '', environment_script: '/etc/profile', virtuoso_bin: '', spectre_bin: '', cadence_cds_lib: '', cmn018_model_file: '' }
const pathFields = [['remote_base', '远程运行目录'], ['environment_script', '环境初始化脚本'], ['virtuoso_bin', 'Virtuoso 程序路径'], ['spectre_bin', 'Spectre 程序路径'], ['cadence_cds_lib', 'Cadence cds.lib 路径'], ['cmn018_model_file', 'CMN018 主模型文件']] as const

export default function ConnectionSettings({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [profile, setProfile] = useState<Profile>(empty)
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [trust, setTrust] = useState<{ fingerprint: string; host: string } | null>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    const ctrl = new AbortController(); controller.current = ctrl
    fetch('/api/v2/connection', { signal: ctrl.signal }).then(async response => {
      if (!response.ok) throw new Error('无法读取服务器设置，请确认使用新版 AutoCadence 后端。')
      const saved = await response.json() as Profile
      setProfile({ ...empty, ...saved, host: saved.host || empty.host, port: saved.host ? saved.port : empty.port })
    }).catch(e => { if (!ctrl.signal.aborted) setError(e.message) }).finally(() => { if (!ctrl.signal.aborted) setLoading(false) })
    return () => controller.current?.abort()
  }, [])

  function change<K extends keyof Profile>(key: K, value: Profile[K]) {
    setProfile(p => ({ ...p, [key]: value, ...(['host', 'port', 'username', 'auth_method', 'identity_file'].includes(key) ? { has_password: false, remember_password: false } : {}) }))
    if (['host', 'port', 'username', 'auth_method', 'identity_file'].includes(key)) setPassword('')
    setTrust(null); setError(''); setMessage('')
  }
  async function save(trusted?: string) {
    if (busy || !profile.host.trim() || !profile.username.trim()) return
    setBusy(true); setError(''); setMessage(''); setTrust(null)
    const ctrl = new AbortController(); controller.current = ctrl
    const timer = setTimeout(() => ctrl.abort(), 85000)
    try {
      const response = await fetch('/api/v2/connection', { method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        host: profile.host.trim(), port: profile.port, username: profile.username.trim(), auth_method: profile.auth_method,
        password: password || undefined, use_saved_password: !password && profile.has_password,
        remember_password: profile.remember_password, identity_file: profile.identity_file,
        legacy_rsa: profile.legacy_rsa, ...Object.fromEntries(pathFields.map(([key]) => [key, profile[key]])), trusted_fingerprint: trusted
      }) })
      const result = await response.json()
      if (!response.ok) {
        if (result.error?.code === 'SSH_HOST_UNTRUSTED' && result.error.details?.fingerprint) { setTrust(result.error.details); return }
        throw new Error(result.error?.message || '连接未成功，请核对填写的信息。')
      }
      setProfile({ ...empty, ...result.connection }); setPassword(''); setMessage(result.message); setAdvanced(!result.ready); onSaved()
    } catch (e) { setError(ctrl.signal.aborted ? '连接等待超时，请检查网络后重试。' : e instanceof Error ? e.message : '连接失败') }
    finally { clearTimeout(timer); setBusy(false) }
  }
  async function forget() {
    setBusy(true); setError(''); setMessage('')
    try {
      const response = await fetch('/api/v2/connection/forget-password', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error?.message || '清除密码失败')
      setProfile({ ...empty, ...result }); setPassword(''); setMessage('已清除保存的密码。下次连接请重新输入。'); onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : '清除密码失败') }
    finally { setBusy(false) }
  }
  return <Modal title="仿真服务器" onClose={() => { if (!busy) onClose() }} wide>
    <p className="sub">使用你自己的 SSH 账号连接装有 Cadence / Spectre 的 Linux 服务器。连接测试只检查登录与环境路径。</p>
    {loading ? <p role="status">正在读取本机配置…</p> : <form onSubmit={event => { event.preventDefault(); void save() }}>
      {profile.imported && <div className="note info">已读取本机原有连接。可以继续使用，也可以填写另一组服务器账号。</div>}
      <div className="connection-grid">
        <div className="param-item"><label htmlFor="ssh-host">服务器地址</label><input id="ssh-host" type="text" autoComplete="off" required disabled={busy} value={profile.host} onChange={e => change('host', e.target.value)} placeholder="服务器 IP 或域名" /></div>
        <div className="param-item"><label htmlFor="ssh-port">SSH 端口</label><input id="ssh-port" type="number" min={1} max={65535} required disabled={busy} value={profile.port} onChange={e => change('port', Number(e.target.value))} /></div>
        <div className="param-item"><label htmlFor="ssh-username">账号</label><input id="ssh-username" type="text" autoComplete="off" required disabled={busy} value={profile.username} onChange={e => change('username', e.target.value)} placeholder="你的服务器账号" /></div>
        <div className="param-item"><label htmlFor="ssh-auth">认证方式</label><select id="ssh-auth" disabled={busy} value={profile.auth_method} onChange={e => change('auth_method', e.target.value as Profile['auth_method'])}><option value="password">账号密码</option><option value="key">私钥文件</option></select></div>
      </div>
      {profile.auth_method === 'key' && <div className="param-item"><label htmlFor="ssh-key">本机私钥路径</label><input id="ssh-key" type="text" required autoComplete="off" disabled={busy} value={profile.identity_file} onChange={e => change('identity_file', e.target.value)} placeholder="例如 C:\Users\你的用户名\.ssh\id_ed25519" /></div>}
      <div className="param-item"><label htmlFor="ssh-password">{profile.auth_method === 'key' ? '私钥口令（未加密的私钥可留空）' : 'SSH 密码'}</label><input id="ssh-password" type="password" autoComplete="new-password" required={profile.auth_method === 'password' && !profile.has_password} disabled={busy} value={password} onChange={e => { setPassword(e.target.value); setTrust(null) }} placeholder={profile.has_password ? '已保存；留空继续使用，填写新值可替换' : '仅提交给本机后端用于 SSH 登录'} /></div>
      <div className="connection-remember"><label><input type="checkbox" disabled={busy} checked={profile.remember_password} onChange={e => change('remember_password', e.target.checked)} />记住密码（仅此 Windows 用户，可随时清除）</label>{profile.has_password && <button type="button" className="text-button" disabled={busy} onClick={forget}>清除已保存密码</button>}</div>
      <details className="detail-section" open={advanced} onToggle={e => setAdvanced(e.currentTarget.open)}><summary>高级设置 · 环境路径与兼容选项</summary><p className="small muted">程序路径留空时自动探测。路径由服务器管理员提供；默认运行目录位于你的服务器主目录下。0.7.3 起 NMOS/PMOS 题目默认使用 CMN018 工艺模型（nch/pch），第一次跑 MOS 题前必须在这里填写 cmn018_model_file：服务器上模型卡的绝对路径，例如 /data/home/你的学号/cmn018_models/cmn018_gp2a_5v_v1d4.scs，同目录还需有 cmn018_gp2a_5v_v1d4_usage.scs。每位用户的服务器家目录需要各传一份模型文件，或由管理员放到公共只读目录共用；未配置时 MOS 仿真预检会失败。R/C/L、二极管、BJT 题目不受影响。</p><div className="connection-grid">{pathFields.map(([key, label]) => <div className="param-item" key={key}><label htmlFor={`ssh-${key}`}>{label}</label><input id={`ssh-${key}`} type="text" disabled={busy} value={profile[key]} onChange={e => change(key, e.target.value)} placeholder={key === 'remote_base' ? '自动创建专用运行目录' : key === 'cmn018_model_file' ? '/服务器路径/cmn018_gp2a_5v_v1d4.scs' : '留空自动探测'} /></div>)}</div><label className="small"><input type="checkbox" disabled={busy} checked={profile.legacy_rsa} onChange={e => change('legacy_rsa', e.target.checked)} />旧服务器 RSA 兼容模式</label></details>
      {trust && <div className="note warn"><strong>确认服务器身份</strong><p>{trust.host}</p><code className="host-fingerprint">{trust.fingerprint}</code><p>首次连接时，请向服务器管理员核对这个指纹。确认后才会发送登录凭据。</p><button type="button" className="btn" onClick={() => save(trust.fingerprint)}>指纹正确，继续连接</button></div>}
      {message && <p className="note info" role="status">{message}</p>}
      <div className="connection-actions"><span className="small muted">密码不会发送给 AI，也不会写入仿真报告。</span><button type="submit" className="btn" disabled={busy}>{busy ? '正在连接并检查环境…' : '连接并保存'}</button></div>
    </form>}
    {error && <p className="note err" role="alert">{error}</p>}
  </Modal>
}
