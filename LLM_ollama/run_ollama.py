import os
import subprocess
import time
import json
import requests
import atexit
import signal
from typing import Optional

# ========== 配置 ==========
CONFIG = {
    "OLLAMA_DIR": r"D:\ollama\ollama-windows-amd64",
    "OLLAMA_HOME": r"D:\ollama\ollama-data",
    "OLLAMA_GPU_MEM": "2048",
    "OLLAMA_PORT": "11434",
    "OLLAMA_URL": "http://127.0.0.1:11434",
}

MODEL_MAP = {
    "phi3": "phi3",
    "llama": "llama3.2:3b",
    "qwen": "qwen2.5:7b",
}

OLLAMA_EXE = os.path.join(CONFIG["OLLAMA_DIR"], "ollama.exe")

# 全局进程引用，用于清理
_ollama_process: Optional[subprocess.Popen] = None


# ========== 进程管理 ==========

def cleanup_process():
    """清理 Ollama 进程"""
    global _ollama_process
    if _ollama_process and _ollama_process.poll() is None:
        print("\n🛑 正在关闭 Ollama 服务...")
        _ollama_process.terminate()
        try:
            _ollama_process.wait(timeout=5)
            print("✅ Ollama 服务已关闭")
        except subprocess.TimeoutExpired:
            print("⚠️ 强制终止 Ollama 服务")
            _ollama_process.kill()


def start_ollama_server():
    """启动 Ollama 服务"""
    global _ollama_process
    
    env = os.environ.copy()
    env["OLLAMA_HOME"] = CONFIG["OLLAMA_HOME"]
    env["OLLAMA_GPU_MEM"] = CONFIG["OLLAMA_GPU_MEM"]
    env["OLLAMA_PORT"] = CONFIG["OLLAMA_PORT"]

    print("🚀 正在启动 Ollama 服务...")
    _ollama_process = subprocess.Popen(
        [OLLAMA_EXE, "serve"],
        cwd=CONFIG["OLLAMA_DIR"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # 注册清理函数
    atexit.register(cleanup_process)
    signal.signal(signal.SIGINT, lambda s, f: (cleanup_process(), exit(0)))
    
    return _ollama_process, env


def wait_for_ollama_ready(timeout=60):
    """等待 Ollama 服务就绪"""
    url = f"{CONFIG['OLLAMA_URL']}/api/tags"
    t0 = time.time()
    
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                print("✅ Ollama 服务已就绪")
                return True
        except Exception:
            pass
        print("⏳ 等待 Ollama 启动中...")
        time.sleep(2)
    
    print("❌ 等待 Ollama 启动超时")
    return False


# ========== 模型管理 ==========

def check_model_exists(env, model_name: str) -> bool:
    """检查模型是否已经下载"""
    try:
        result = subprocess.run(
            [OLLAMA_EXE, "list"],
            cwd=CONFIG["OLLAMA_DIR"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        # 检查模型名是否在输出中
        return model_name in result.stdout
    except Exception as e:
        print(f"⚠️ 检查模型时出错: {e}")
        return False


def pull_model(env, model_name: str):
    """拉取模型"""
    print(f"🔻 开始拉取模型: {model_name}")
    try:
        subprocess.run(
            [OLLAMA_EXE, "pull", model_name],
            cwd=CONFIG["OLLAMA_DIR"],
            env=env,
            check=True,
        )
        print("✅ 模型拉取完成")
    except subprocess.CalledProcessError as e:
        print(f"❌ 模型拉取失败: {e}")
        raise


def ensure_model(env, model_name: str):
    """确保模型存在，不存在则拉取"""
    if check_model_exists(env, model_name):
        print(f"✅ 模型 {model_name} 已存在")
        return
    pull_model(env, model_name)


# ========== 对话功能 ==========

def chat_stream(model_name: str, messages: list[dict]):
    """
    使用 /api/chat 进行流式对话
    messages: [{"role": "system"/"user"/"assistant", "content": "..."}]
    """
    url = f"{CONFIG['OLLAMA_URL']}/api/chat"
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True,
    }

    with requests.post(url, json=payload, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line.decode("utf-8"))
            msg = data.get("message", {})
            chunk = msg.get("content", "")
            if chunk:
                yield chunk
            if data.get("done"):
                break


def save_conversation(messages: list[dict], model_name: str):
    """保存对话历史"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"chat_{model_name}_{timestamp}.json"
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({
                "model": model_name,
                "timestamp": timestamp,
                "messages": messages
            }, f, ensure_ascii=False, indent=2)
        print(f"✅ 对话已保存至: {filename}")
    except Exception as e:
        print(f"❌ 保存失败: {e}")


def show_help():
    """显示帮助信息"""
    print("\n📖 命令列表:")
    print("  /exit   - 退出对话")
    print("  /clear  - 清空对话上下文（保留系统提示）")
    print("  /save   - 保存对话历史到 JSON 文件")
    print("  /count  - 显示当前对话轮数")
    print("  /help   - 显示此帮助信息")


def interactive_chat(model_name: str):
    """
    交互式多轮对话
    """
    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "你是一个帮我处理本地项目、数据库和游戏服务器相关问题的中文助手，"
                "回答尽量简洁清晰。"
            )
        }
    ]

    print(f"\n💬 已进入对话模式，当前模型: {model_name}")
    show_help()

    while True:
        try:
            user_input = input("\n👤 你: ").strip()
            
            if not user_input:
                continue
            
            # 处理命令
            if user_input in {"/exit", "exit", "quit"}:
                print("👋 结束对话")
                break
            
            elif user_input == "/clear":
                messages = messages[:1]  # 只保留 system 消息
                print("✅ 已清空对话上下文")
                continue
            
            elif user_input == "/save":
                save_conversation(messages, model_name)
                continue
            
            elif user_input == "/count":
                # 计算对话轮数（排除 system 消息）
                rounds = (len(messages) - 1) // 2
                print(f"📊 当前对话轮数: {rounds}")
                continue
            
            elif user_input == "/help":
                show_help()
                continue
            
            # 正常对话流程
            messages.append({"role": "user", "content": user_input})
            
            print("🤖 模型: ", end="", flush=True)
            assistant_reply = ""
            
            try:
                for chunk in chat_stream(model_name, messages):
                    print(chunk, end="", flush=True)
                    assistant_reply += chunk
                
                print()  # 换行
                
                if assistant_reply:
                    messages.append({"role": "assistant", "content": assistant_reply})
                else:
                    print("⚠️ 模型未返回内容")
                    messages.pop()  # 移除用户消息
                    
            except requests.exceptions.RequestException as e:
                print(f"\n❌ 请求出错: {e}")
                messages.pop()  # 移除用户消息
            except Exception as e:
                print(f"\n❌ 未知错误: {e}")
                messages.pop()
                
        except KeyboardInterrupt:
            print("\n⚠️ 检测到中断，输入 /exit 退出对话")
            continue
        except EOFError:
            print("\n👋 检测到输入结束，退出对话")
            break


# ========== 模型选择 ==========

def choose_model() -> str:
    """选择要使用的模型"""
    print("\n📦 请选择模型:")
    print("  1) phi3   ->", MODEL_MAP["phi3"])
    print("  2) llama  ->", MODEL_MAP["llama"])
    print("  3) qwen   ->", MODEL_MAP["qwen"])

    choice = input("输入 1 / 2 / 3 (默认 1): ").strip()

    model_key = {
        "1": "phi3",
        "2": "llama",
        "3": "qwen",
    }.get(choice, "phi3")

    model_name = MODEL_MAP[model_key]
    print(f"✅ 已选择模型: {model_key} ({model_name})")
    return model_name


# ========== 主入口 ==========

def main():
    """主函数"""
    try:
        # 启动 Ollama 服务
        proc, env = start_ollama_server()
        
        # 等待服务就绪
        if not wait_for_ollama_ready():
            print("❌ Ollama 启动失败，请检查日志")
            return 1
        
        # 选择模型
        model_name = choose_model()
        
        # 确保模型存在
        ensure_model(env, model_name)
        
        # 进入对话模式
        interactive_chat(model_name)
        
        return 0
        
    except KeyboardInterrupt:
        print("\n⚠️ 程序被中断")
        return 130
    except Exception as e:
        print(f"\n❌ 程序出错: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cleanup_process()


if __name__ == "__main__":
    exit(main())