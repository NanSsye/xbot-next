import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, Search, X, SlidersHorizontal } from 'lucide-react';
import { api } from '../api';
import type { ConfigSnapshot } from '../types';
import { ConfigCenter, type ConfigAppliedEvent } from './ConfigCenter';
import { fieldCopy, settingGroups, settingsRows, type SettingGroup } from './settingsTasks';

type Editor = { id:string; title:string; paths:string[]; choices:string[]; snapshot:ConfigSnapshot };
export function SettingsHome({children,onChat,onApplied}:{children:ReactNode;onChat:()=>void;onApplied:(e:ConfigAppliedEvent)=>Promise<void>}) {
  const [snapshot,setSnapshot]=useState<ConfigSnapshot|null>(null);
  const [error,setError]=useState('');
  const [query,setQuery]=useState('');
  const [group,setGroup]=useState<SettingGroup>('AI 对话');
  const [editor,setEditor]=useState<Editor|null>(null);
  const [choices,setChoices]=useState<string[]>([]);
  const [busy,setBusy]=useState(false);
  const dirty=useRef(false);
  const drawer=useRef<HTMLDialogElement>(null), discard=useRef<HTMLDialogElement>(null);
  const load=useCallback(async()=>{setError('');try{setSnapshot(await api.config());}catch(e){setError(e instanceof Error?e.message:String(e));}},[]);
  useEffect(()=>{void load();},[load]);
  const rows=settingsRows(snapshot?.sections??[]);
  const fields=new Map(rows.flatMap(r=>r.fields).map(f=>[f.path,f]));
  const model=String(fields.get('agent.llm.model')?.value??'');
  const pool=fields.get('agent.llm.enabled_models')?.value;
  const provider=fields.get('agent.llm.provider')?.value;
  const connected=fields.get('agent.llm.api_key')?.configured && fields.get('agent.llm.base_url')?.value;
  const enabled=fields.get('agent.enabled')?.value && fields.get('agent.llm.enabled')?.value;
  const next=!connected?'connection':!model?'model':!enabled?'enable':'chat';
  function edit(id:string, path?:string){
    const row=rows.find(r=>r.id===id); if(!row || !snapshot)return;
    const paths=row.fields.map(f=>f.path);
    if(id==='model')paths.push('agent.llm.enabled_models');
    setEditor({id,title:row.title,paths,choices,snapshot});
    dirty.current=false;setBusy(false);
    if(!drawer.current?.open)drawer.current?.showModal();
    if(path)window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{
      const el=document.getElementById('config-field-'+path.replace(/[^a-zA-Z0-9_-]/g,'-'));
      el?.closest('details')?.setAttribute('open','');el?.scrollIntoView({block:'center'});el?.querySelector<HTMLElement>('input,button,select,textarea')?.focus();
    }));
  }
  const changed=useCallback((d:boolean,b:boolean)=>{dirty.current=d;setBusy(b);},[]);
  function close(){if(busy)return;if(dirty.current)discard.current?.showModal();else drawer.current?.close();}
  const q=query.trim().toLowerCase();
  return <div className="settings-layout settings-home">
    <div className="settings-top"><nav className="settings-tabs" aria-label="设置类别">{settingGroups.map(g=><button key={g} aria-current={group===g?'page':undefined} onClick={()=>{setGroup(g);setQuery('');}}>{g}</button>)}</nav>
    <label className="config-search"><Search size={15}/><input type="search" aria-label="搜索全部设置" placeholder="搜索设置" value={query} onChange={e=>setQuery(e.target.value)}/></label></div>
    {error ? <div role="alert">设置加载失败：{error} <button className="ghost-button" onClick={()=>void load()}>重试</button></div> : !snapshot ? <p role="status">正在读取设置…</p> : <>
    {!q && group==='AI 对话' && <div className="settings-summary"><SlidersHorizontal size={20}/><div><strong>{!connected?'还没有连接模型服务':!model?'尚未选择默认模型':!enabled?'AI 对话尚未开启':'模型已配置'}</strong><p>{!connected?'连接模型服务后，机器人才能生成回复。':!enabled?`默认模型：${model || '未选择'}。请检查智能助手和模型调用开关。`:'发送一条消息，验证当前配置能否正常回复。'}</p></div><button className="primary-button" onClick={()=>next==='chat'?onChat():edit(next)}>{next==='connection'?'连接模型服务':next==='model'?'选择模型':next==='enable'?'检查开关':'去试聊'}</button></div>}
    {group==='控制台偏好'&&!q && children}
    <div className="settings-rows">{rows.flatMap(row=>{
      const matches=row.fields.filter(f=>[f.label,f.path,f.env_name,f.description,...fieldCopy[f.path]??[]].some(v=>v?.toLowerCase().includes(q)));
      if(!q && row.group!==group || q && !matches.length && !row.title.includes(q))return [];
      const hits=q && matches.length ? matches : [null];
      return hits.map(hit=><button type="button" key={hit?.path??row.id} onClick={()=>edit(row.id,hit?.path)}><span><strong>{hit?(fieldCopy[hit.path]?.[0]??hit.label):row.title}</strong><small>{q?`${row.group} · ${row.title}`:row.description}</small></span><span className="settings-value">{hit?'定位':row.id==='connection'?(provider==='openai_compatible'?'OpenAI 兼容接口':String(provider??'未配置')):row.id==='model'?model||'未选择':row.id==='pool'?`${Array.isArray(pool)?pool.length:0} 个`:'管理'}<ChevronRight size={15}/></span></button>);
    })}</div>{q && <p className="settings-no-results">没有找到匹配的设置。</p>}</>}
    <dialog className="channel-config-dialog settings-drawer" ref={drawer} aria-labelledby="settings-edit-title" onCancel={e=>{if(e.target===e.currentTarget){e.preventDefault();close();}}} onClose={e=>{if(e.target===e.currentTarget)setEditor(null);}}>
      <header className="modal-header"><h2 className="modal-title" id="settings-edit-title">{editor?.title}</h2><button autoFocus className="icon-button" disabled={busy} aria-label="关闭设置" onClick={close}><X size={17}/></button></header>
      {editor && <ConfigCenter key={editor.id} scope="system" task={editor} onState={changed} onNext={()=>edit('model')} onFound={setChoices} onApplied={async(e)=>{setSnapshot(e.result.snapshot);await onApplied(e);if(editor.id!=='connection')drawer.current?.close();}}/>}
      <dialog className="config-confirm-dialog" ref={discard} aria-labelledby="discard-title"><h2 id="discard-title">放弃未保存的修改？</h2><p>已经保存的设置不会改变。</p><div className="config-confirm-dialog__actions"><button autoFocus className="ghost-button" onClick={()=>discard.current?.close()}>继续编辑</button><button className="primary-button" onClick={()=>{sessionStorage.removeItem(`xbot.config.draft.v1.system.${editor?.id}`);discard.current?.close();drawer.current?.close();}}>放弃修改</button></div></dialog>
    </dialog>
  </div>;
}
