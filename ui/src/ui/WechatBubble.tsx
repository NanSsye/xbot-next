import { useState } from 'react';
import { ImageOff } from 'lucide-react';
import type { WechatAttachment, WechatMessage } from '../types';

function Attachment({ item }: { item: WechatAttachment }) {
  const [failed, setFailed] = useState('');
  const image = item.kind === 'image' || item.mime?.startsWith('image/');
  let url = '';
  if (item.url) {
    try {
      const resolved = new URL(item.url, window.location.origin);
      if (resolved.origin === window.location.origin && /^\/(media\/(wechat869|wechat_ilink)\/media|files\/wechat_outbox)\//.test(resolved.pathname)) url = resolved.href;
    } catch { /* Malformed historical media references have no preview. */ }
  }
  if (image && url && failed !== url) return <a href={url} target="_blank" rel="noopener noreferrer" aria-label="查看原图"><img className="wechat-photo" src={url} alt="微信图片" loading="lazy" decoding="async" onError={() => setFailed(url)} /></a>;
  if (!image && url) return <a href={url} target="_blank" rel="noopener noreferrer">{item.filename || '查看附件'}</a>;
  return <span className="wechat-media-missing"><ImageOff size={15} aria-hidden="true" />{image ? '图片暂不可用' : '附件暂不可用'}</span>;
}

export function WechatBubble({ message }: { message: WechatMessage }) {
  const attachments = message.attachments ?? [];
  const direct = attachments.filter(a => !a.quoted), quoted = attachments.filter(a => a.quoted);
  const raw = message.raw?.quote;
  const quote = raw && typeof raw === 'object' ? raw as Record<string, unknown> : undefined;
  const content = message.content ?? '';
  const marker = /(?:^|\n)\[引用(图片|文件|视频)?\]\s*/.exec(content);
  const hasQuote = !!quote || quoted.length > 0 || !!marker;
  const body = marker ? content.slice(0, marker.index) : content;
  const legacy = marker && !marker[1] ? content.slice(marker.index + marker[0].length) : '';
  const quoteText = typeof quote?.content === 'string' ? quote.content.trim() : legacy;
  const sender = typeof quote?.sender_name === 'string' ? quote.sender_name : '';
  const placeholder = body.trim() === '[图片]' || (!body && message.type === 'image');
  return <div className="wechat-bubble-box">
    {!placeholder && body && <div className="wechat-message-text">{body}</div>}
    {direct.map(item => <Attachment key={item.id} item={item} />)}
    {placeholder && !direct.length && <span className="wechat-media-missing"><ImageOff size={15} />图片暂不可用</span>}
    {hasQuote && <blockquote className="wechat-quote"><strong>{sender ? `引用 · ${sender}` : '引用消息'}</strong>
      {quoteText && !quoteText.startsWith('<') && <div className="wechat-message-text">{quoteText}</div>}
      {quoted.map(item => <Attachment key={item.id} item={item} />)}
      {!quoted.length && (!quoteText || quoteText.startsWith('<')) && <span>{marker?.[1] === '图片' || quote?.msg_type === 3 ? '原图暂不可用' : '原消息暂不可用'}</span>}
    </blockquote>}
  </div>;
}
