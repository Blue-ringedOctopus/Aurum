from openai import OpenAI
from typing import List, Dict, Optional

class DeepSeekClient:
    """
    专为 DeepSeek API 定制的客户端，支持从参数或环境变量获取配置。
    推荐使用方式：直接传入 api_key 和 model。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-pro",
        base_url: str = "https://api.deepseek.com/v1",
        timeout: int = 60
    ):
        if not api_key:
            raise ValueError("API Key 不能为空")
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        stream: bool = False
    ) -> Optional[str]:
        """
        发送对话消息，返回模型响应（非流式或流式）。
        如果 stream=False，返回完整文本。
        如果 stream=True，将逐块打印到终端（主要用于调试），返回拼接后的完整文本。
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=stream,
            )
            if stream:
                collected = []
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        print(content, end="", flush=True)  # 调试用
                        collected.append(content)
                print()
                return "".join(collected)
            else:
                return response.choices[0].message.content
        except Exception as e:
            # 捕获异常并返回错误信息，便于前端显示
            return f"❌ 调用大模型失败: {str(e)}"

# 便捷函数（直接使用）
def call_llm(
    messages: List[Dict[str, str]],
    api_key: str,
    model: str = "deepseek-v3.2",
    base_url: str = "https://api.deepseek.com/v1",
    temperature: float = 0.7,
    timeout=120
) -> str:
    """
    一次性调用大模型，返回结果字符串。
    """
    client = DeepSeekClient(api_key, model, base_url, timeout=timeout)
    return client.chat(messages, temperature, stream=False)

