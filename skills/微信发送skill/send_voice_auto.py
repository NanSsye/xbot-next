#!/usr/bin/env python3.11
"""
完全自动化的微信语音发送脚本
用法: python3.11 send_voice_auto.py "<文字内容>" "<目标wxid或群ID@chatroom>" [音色ID]

示例:
  python3.11 send_voice_auto.py "你好！" "wxid_xxx"
  python3.11 send_voice_auto.py "大家好！" "50540167809@chatroom"
  python3.11 send_voice_auto.py "你好！" "wxid_xxx" "Chinese (Mandarin)_Warm_Bestie"
"""
import sys
import urllib.request
import json
import os
import subprocess
import time

PYTHON_BIN = "/usr/local/bin/python3.11"
API_KEY = "sk-cp-_sb6YWyon1RmUZc9-2ELmpLQDq3cnKRdWGL_D24MBw4JLO6UKW1wf3Jl4lRj1UhXxCXjFIOatNiNqBSRUT8vdHR7jGZJAQzuR2PoCyGoe-pG-ACpAzgPTmM"
TTS_URL = "https://api.minimaxi.com/v1/t2a_v2"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEND_SCRIPT = SCRIPT_DIR + "/send_869_media.py"
TMP = "/home/nans/.openclaw/tmp"
os.makedirs(TMP, exist_ok=True)

DEFAULT_VOICE = "Chinese (Mandarin)_Warm_Bestie"
DEFAULT_EMOTION = "happy"


def tts_synthesize(text, voice_id=DEFAULT_VOICE, emotion=DEFAULT_EMOTION):
    """Step 1: TTS 合成 → Step 2: 下载 MP3"""
    print(f"[TTS] 合成: {text[:30]}...")
    payload = {
        "model": "speech-2.8-hd",
        "text": text,
        "stream": False,
        "output_format": "url",
        "voice_setting": {
            "voice_id": voice_id,
            "speed": 1,
            "vol": 1,
            "pitch": 0,
            "emotion": emotion
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1
        }
    }
    data_enc = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        TTS_URL, data=data_enc,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if "data" not in result:
        raise Exception(f"TTS 错误: {result}")

    mp3_url = result["data"]["audio"]
    audio_ms = result["extra_info"]["audio_length"]
    audio_sec = audio_ms / 1000.0

    filename = f"voice_{int(time.time())}.mp3"
    mp3_path = os.path.join(TMP, filename)
    urllib.request.urlretrieve(mp3_url, mp3_path)
    size = os.path.getsize(mp3_path)
    print(f"[TTS] 完成: {size} bytes, {audio_sec:.1f}s")
    return mp3_path, audio_sec


def send_voice(target, mp3_path, audio_sec):
    """Step 3: 869 发微信语音（自动 SILK 编码 + 自动发送）"""
    print(f"[869] 发送至: {target}")
    args = [
        PYTHON_BIN, SEND_SCRIPT,
        "send-voice",
        "--to", target,
        "--path", mp3_path,
        "--format", "mp3",
        "--seconds", str(int(audio_sec) + 2)
    ]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate(timeout=30)
    out = stdout.decode("utf-8")

    try:
        parsed = json.loads(out)
        data = parsed.get("Data", {})
        if isinstance(data, list):
            data = data[0] if data else {}
        # ret 在 baseResponse 里
        ret_code = data.get("baseResponse", {}).get("ret")
        new_msg_id = data.get("newMsgId", 0)
        is_ok = (ret_code == -104 and new_msg_id != 0)
        print(f"[869] ret={ret_code} newMsgId={new_msg_id} ok={is_ok}")
        return is_ok, new_msg_id
    except Exception as e:
        # fallback: 字符串检测
        has_ret = '"ret": -104' in out or "'ret': -104" in out
        has_msgid = "newMsgId" in out and out.count("newMsgId") >= 2  # 确保不是 baseResponse 里也有
        is_ok = has_ret and has_msgid
        print(f"[869] fallback检测 ret={has_ret} msgid={has_msgid} ok={is_ok}")
        return is_ok, 0


def main():
    if len(sys.argv) < 3:
        print("用法: python3.11 send_voice_auto.py \"<文字>\" \"<目标>\" [音色]")
        print("示例:")
        print("  python3.11 send_voice_auto.py \"你好！\" \"wxid_xxx\"")
        print("  python3.11 send_voice_auto.py \"大家好！\" \"50540167809@chatroom\"")
        print("  python3.11 send_voice_auto.py \"发语音！\" \"wxid_xxx\" \"Chinese (Mandarin)_Warm_Bestie\"")
        sys.exit(1)

    text = sys.argv[1]
    target = sys.argv[2]
    voice_id = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_VOICE

    try:
        # 全自动: TTS → 下载 → SILK → 发送
        mp3_path, audio_sec = tts_synthesize(text, voice_id)
        is_ok, new_msg_id = send_voice(target, mp3_path, audio_sec)
        if is_ok:
            print(f"✅ 发送成功 newMsgId={new_msg_id}")
        else:
            print(f"❌ 发送失败")
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
