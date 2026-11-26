export const WECHAT_CLIENT_LABEL = "微信客户端通道";

export function wechatChannelDisplayText(text: string): string {
  return text.replace(/微信\s*869(?:\s*客户端通道)?|wechat869(?:Adapter|Client)?|\b869\b/gi, WECHAT_CLIENT_LABEL);
}
