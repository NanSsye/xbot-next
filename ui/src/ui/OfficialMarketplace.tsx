import { useEffect, useState } from "react";
import { Download, Package, RefreshCw, Zap } from "lucide-react";
import { api } from "../api";
import { PageHeading } from "./IllustrationHero";

export function OfficialMarketplace() {
  const [kind, setKind] = useState<"plugin" | "skill">("plugin");
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof api.officialCatalog>> | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy,setBusy]=useState('');
  const [notice,setNotice]=useState('');
  async function install(digest:string,name:string){
    if(!window.confirm(`安装官方扩展 ${name}？`))return;
    setBusy(digest);setNotice('');
    try{await api.installRelease(digest);setNotice(`${name} 已安装`)}catch(e){setNotice(e instanceof Error?e.message:'安装失败')}finally{setBusy('')}
  }
  const [revision, refresh] = useState(0);
  useEffect(() => {
    let active = true;
    setCatalog(null);
    setFailed(false);
    api.officialCatalog().then(items => {
      if (active) setCatalog(items);
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [revision]);
  const label = kind === "plugin" ? "插件" : "技能";
  const Icon = kind === "plugin" ? Package : Zap;
  const releases = catalog?.filter(item => item.Kind === kind);
  return <div className="content-scroll">
    <PageHeading title="官方市场" tagline="Xbot 官方插件与技能发行目录" actions={[
      { label: failed ? "重试" : "刷新目录", icon: <RefreshCw size={14} />, onClick: () => refresh(i => i + 1), disabled: !catalog && !failed },
    ]} />
    <div role="group" aria-label="资源类型" style={{ display: "flex", gap: 8, marginBottom: 16 }}>
      {(["plugin", "skill"] as const).map(type => <button type="button" key={type} aria-pressed={kind === type}
        className={kind === type ? "primary-button" : "ghost-button"} onClick={() => setKind(type)}>
        {type === "plugin" ? <><Package size={15} />插件</> : <><Zap size={15} />技能</>}
      </button>)}
    </div>
    {notice && <p role="status">{notice}</p>}
    {failed ? <p role="alert">无法读取官方目录，请重试。</p>
      : !releases ? <section className="market-loading" aria-label="市场目录">
          <p role="status"><RefreshCw size={14} aria-hidden="true"/>正在获取{label}目录</p>
          <div className="extensions-grid" aria-hidden="true">{[0, 1, 2].map(i =>
            <div key={i} className="extension-card market-placeholder"><div className="extension-card__head"><div className="extension-icon-wrap"><Icon size={19}/></div><i/></div><b/><span/><span/></div>
          )}</div>
        </section>
      : releases.length === 0 ? <div className="empty-state" role="status"><Icon size={24} /><p>暂无已发布的官方{label}</p></div>
      : <div className="extensions-grid">{releases.map(item => <article className="extension-card" key={`${item.Name}:${item.Version}`}>
        <div className="extension-card__head"><div className="extension-icon-wrap"><Icon size={20} /></div><small>{item.Version}</small></div>
        <h3 style={{ margin: 0, overflowWrap: "anywhere" }}>{item.Name}</h3>
        {item.Notes && <p style={{ margin: 0, overflowWrap: "anywhere" }}>{item.Notes}</p>}
        {item.Signature && <button className="primary-button" disabled={!!busy} onClick={()=>void install(item.Digest,item.Name)}><Package size={14}/>{busy===item.Digest?'安装中…':'安装'}</button>}
        <a className="ghost-button" href={`https://xbot.catmi.si/api/download/${encodeURIComponent(item.Digest)}`}><Download size={14} />下载发行包</a>
      </article>)}</div>}
  </div>;
}
