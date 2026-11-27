import type { ConfigField, ConfigSection } from '../types';

export const settingGroups = ['AI 对话', '控制台偏好', '高级管理'] as const;
export const optionCopy: Record<string,[string,string]> = {
  safe:['安全模式','适合日常使用。工具列表包含通用工具和标为安全模式可用的工具。'],
  developer:['开发模式','开发或调试时使用。工具列表包含通用工具和支持开发模式的工具；终端与文件写入另有权限设置。'],
  admin:['管理员模式','维护服务时使用。工具列表包含通用工具和支持管理员模式的工具；选择此项不会授予用户管理员身份。'],
  postgresql:['PostgreSQL 数据库','将数据保存在数据库服务中，需要可用的数据库连接。'],sqlite:['SQLite 本地数据库','将数据保存在本机数据库文件中，无需单独运行数据库服务。'],
  memory:['内存队列','待处理消息放在当前进程内，进程退出后不会保留。'],redis:['Redis 队列','通过 Redis 服务传递待处理消息，需要配置 Redis 连接地址。'],
  fixed:['固定间隔','每次重试等待相同的时间。'],exponential:['递增间隔','连续失败时逐步延长等待时间，直到达到配置的上限。'],
  private:['私聊','用于与单个用户的一对一对话。'],group:['群聊','用于群内消息的会话上下文。'],channel:['频道','用于频道消息的会话上下文。'],agent_task:['助手任务','用于助手执行任务时的会话上下文。'],system:['系统','用于系统内部消息的会话上下文。'],
  openai_compatible:['OpenAI 兼容接口','服务商提供 OpenAI 兼容地址时选择，不要求模型来自 OpenAI。'],anthropic:['Anthropic 接口','服务商明确提供 Anthropic 消息接口时选择。'],
  member:['成员','未单独指定身份的用户按成员权限处理。'],guest:['访客','未单独指定身份的用户按访客权限处理，不自动视为成员。'],
};
export type SettingGroup = typeof settingGroups[number];
const core: Record<string, string> = {
  'agent.enabled': 'enable', 'agent.llm.enabled': 'enable', 'agent.llm.provider': 'connection',
  'agent.llm.base_url': 'connection', 'agent.llm.api_key': 'connection', 'agent.llm.model': 'model', 'agent.llm.enabled_models': 'pool',
};
const tasks: Record<string, [SettingGroup, string, string]> = {
  connection: ['AI 对话','模型服务','服务地址、访问密钥与接口类型'], model: ['AI 对话','默认对话模型','用于没有单独指定模型的对话'],
  pool: ['AI 对话','群聊可选模型','允许群聊管理员选择的模型'], enable: ['AI 对话','对话开关','管理智能助手与模型调用'], conversation: ['AI 对话','会话设置','消息记忆、上下文和并发'],
  xbot: ['控制台偏好','基础信息','机器人名称、时区与日志'], api: ['控制台偏好','访问安全','访问密钥与允许访问的网页来源'],
  agent: ['高级管理','智能助手运行参数','工具权限、推理参数与任务调度'], network: ['高级管理','网络与代理','控制外部请求经过的代理'],
  server: ['高级管理','服务监听','服务绑定的地址与端口'], storage: ['高级管理','数据库','连接、初始化和连接池'], queue: ['高级管理','消息队列','消息分发、容量和重试'],
  runtime: ['高级管理','运行限制','并发任务数量与等待时间'], plugins: ['高级管理','插件','插件目录和自动加载'], skills: ['高级管理','技能','技能目录和自动加载'],
};
export const fieldCopy: Record<string,[string,string]> = {
  'agent.enabled':['智能助手','关闭后不运行智能助手。'], 'agent.llm.enabled':['模型调用','开启后，助手才可向模型服务发送请求。'],
  'agent.llm.provider':['接口类型','按服务商提供的接口类型选择。'], 'agent.llm.base_url':['服务地址','填写服务商提供的接口地址，不是官网登录网址。'],
  'agent.llm.api_key':['访问密钥','在模型服务商后台创建；已保存的密钥无需重新填写。'], 'agent.llm.model':['默认对话模型','可选择已有模型，或填写服务商提供的完整模型 ID。'],
  'agent.llm.enabled_models':['群聊可选模型','移除后，群聊将不能再选择该模型。默认模型必须保留。'],
  'api.auth_enabled':['控制台访问验证','开启后，访问控制台接口需要提供有效密钥。'], 'xbot.timezone':['时区','用来解释本地时间，例如 Asia/Shanghai。'],
  'server.host':['监听地址','决定服务接受来自哪些网络接口的连接。'], 'server.port':['监听端口','客户端连接控制台时使用的端口号。'],
};
export function settingsRows(sections: ConfigSection[]) {
  const rows = new Map<string,{id:string; title:string; group:SettingGroup; description:string; fields:ConfigField[]}>();
  for (const section of sections.filter(s=>s.scope==='system')) for (const f of section.fields) {
    const id = core[f.path] ?? section.key;
    const [group,title,description] = tasks[id] ?? ['高级管理',section.title,section.description];
    if (!rows.has(id)) rows.set(id,{id,title,group,description,fields:[]});
    rows.get(id)!.fields.push(f);
  }
  const order = Object.keys(tasks);
  return [...rows.values()].sort((a,b)=>(order.includes(a.id)?order.indexOf(a.id):999)-(order.includes(b.id)?order.indexOf(b.id):999));
}

const groups: Record<string, Record<string,string>> = {
  xbot:{name:'机器人名称|用于标识当前机器人实例。',debug:'调试日志|排查故障时记录更多细节，日常可关闭。'},
  api:{cors_origins:'允许的网页来源|哪些网页可以跨域请求控制台接口。'},
  storage:{type:'数据库类型|选择保存业务数据的数据库。',echo:'数据库查询日志|排查问题时记录数据库语句。',persist_runtime_events:'保存运行事件|将运行期间的事件写入数据库。',auto_bootstrap:'自动初始化|启动时准备数据库资源。',create_database:'自动创建数据库|初始化时创建所需数据库。',create_role:'自动创建账号|初始化时创建所需数据库角色。',run_migrations_on_startup:'启动时更新表结构|启动时应用数据库迁移。',pool_size:'常驻连接数|数据库连接池长期保留的连接数量。',max_overflow:'额外连接上限|高峰期允许超过常驻数量的连接数。',pool_recycle_seconds:'连接回收时间（秒）|超过此时长的连接可被替换。',pool_pre_ping:'连接可用性检查|取出连接时先检查是否还能使用。'},
  queue:{type:'队列类型|决定待处理消息存放在哪里。',redis_url:'Redis 地址|用于连接 Redis 队列服务。',main_queue:'主消息队列|接收入站消息的队列名称。',reply_queue:'回复队列|等待发送的回复存放在这里。',event_queue:'事件队列|用于传递运行事件。',agent_task_queue:'助手任务队列|用于传递待处理的助手任务。',dead_letter_queue:'失败消息队列|收集处理失败且不再重试的消息。',consumer_name:'消费者名称|用于标识读取队列的工作进程。',maxsize:'队列容量|队列允许积压的项目数。','retry.max_attempts':'最大尝试次数|消息处理失败后允许的总尝试次数。','retry.initial_delay_seconds':'首次重试等待（秒）|首次重试前的等待时长。','retry.max_delay_seconds':'最长重试等待（秒）|两次尝试之间等待的上限。','retry.backoff':'重试间隔倍率|控制后续重试间隔的增长速度。'},
  conversation:{enabled:'启用会话管理|管理同一段对话的上下文。',store:'会话存储|选择对话状态的保存方式。',default_scope:'会话划分方式|决定哪些消息共享一段对话。','context.recent_messages':'近期消息数|提供给对话上下文的近期消息条数。','context.max_chars':'上下文字符上限|限制带入对话的文字量。','context.auto_summarize':'自动摘要|将较早的消息整理为摘要。','context.summary_every_messages':'摘要间隔（条）|累计多少条消息后生成摘要。','concurrency.per_conversation_serial':'同一会话顺序处理|避免同一段对话的消息并行处理。','concurrency.max_active_conversations':'同时活跃会话数|限制同时处理的对话数量。'},
  agent:{uses_hermes_runtime:'使用 Hermes 引擎|决定是否使用 Hermes 运行助手。',mode:'助手运行模式|决定助手运行时采用的模式。',admin_mode_allowed:'允许管理员模式|决定是否允许使用管理员模式。',timezone:'助手时区|用于助手解释日期和本地时间。',workspace_root:'工作目录|助手处理文件时使用的根目录。',allow_shell:'允许终端命令|允许助手调用终端，开启前确认授权范围。',allow_file_write:'允许写入文件|决定助手能否修改工作区中的文件。',max_tool_iterations:'工具调用轮数|限制一次任务连续调用工具的轮数。',auto_delegate_channel_tasks:'自动分派通道任务|决定通道任务是否允许自动分派。',max_inline_tool_result_chars:'工具结果字符上限|限制直接放入上下文的工具输出。',tool_result_artifact_dir:'工具结果目录|较大的工具输出保存到此目录。','llm.context_window_tokens':'上下文容量|模型单次处理的上下文大小，以词元为单位。','llm.timeout_seconds':'模型请求超时（秒）|等待模型服务返回结果的最长时间。','llm.max_attempts':'模型请求尝试次数|限制调用模型失败后的重复尝试。','llm.retry_backoff_seconds':'模型重试等待（秒）|模型调用失败后等待再试的基础时长。','llm.max_tokens':'回复长度上限|限制一次回复的词元数量。','llm.temperature':'回答随机度|较低时回答更稳定，较高时变化更多。','mcp.enabled':'启用外部工具服务|允许助手连接配置的 MCP 服务。','mcp.servers':'外部工具服务|配置提供外部工具的 MCP 服务。','schedule.enabled':'启用任务调度|定时检查并处理到期任务。','schedule.tick_seconds':'调度检查间隔（秒）|两次到期任务检查之间的时间。','schedule.max_due_per_tick':'单次调度上限|每轮最多处理的到期任务数。','member_policy.enabled':'启用成员权限策略|为普通成员限制可用工具和资源。','member_policy.workspace_roots':'成员授权目录|成员可访问的工作区目录列表。','member_policy.allow_terminal':'允许成员使用终端|决定成员能否请求执行终端命令。','member_policy.allow_public_web':'允许成员访问公网|决定成员能否通过工具访问公共网站。','member_policy.block_private_network':'阻止成员访问内网|限制成员通过工具访问私有网络。'},
  network:{'proxy.enabled':'启用出站代理|让服务的外部请求经过指定代理。'},
};
for(const [section,entries] of Object.entries(groups)) for(const [key,copy] of Object.entries(entries)) {
  const [name,help]=copy.split('|');fieldCopy[`${section}.${key}`]=[name,help];
}
for(const [key,name] of Object.entries({dangerous_tools:'高风险工具',outside_workspace:'工作区外操作',delete_files:'删除文件',shell_exec:'终端命令',database_write:'数据库写入'})) fieldCopy[`agent.approval.${key}`]=[`${name}审批`,`设置${name}的审批要求。`];
for(const [key,name] of Object.entries({message:'消息处理',plugin:'插件',agent_task:'助手任务',tool:'工具调用'})) {
  fieldCopy[`runtime.timeout.${key}_seconds`]=[`${name}超时（秒）`,`限制${name}单次运行的等待时间。`];
  fieldCopy[`runtime.concurrency.max_${key==='agent_task'?'agent':key}_tasks`]=[`${name}并发数`,`限制同时执行的${name}数量。`];
}
fieldCopy['runtime.timeout.http_seconds']=['网络请求超时（秒）','等待网络请求返回的最长时间。'];
fieldCopy['runtime.concurrency.sync_worker_threads']=['同步工作线程数','用于执行同步工作的线程数量。'];
for(const [key,name] of [['plugins','插件'],['skills','技能']]) {
  fieldCopy[`${key}.directory`]=[`${name}目录`,`读取${name}文件的目录。`];fieldCopy[`${key}.auto_load`]=[`自动加载${name}`,`启动时从目录加载${name}。`];
}
