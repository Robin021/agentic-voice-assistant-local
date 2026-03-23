import litellm
from litellm.types.llms.custom_llm import CustomLLMItem
from .custom.t import MiniAssistantLLM
from .funasr.cosyvoice import FunASRCosyVoiceAPI


def load_custom_llm():
    """
    Load the custom LLM handler
    """

    litellm.provider_list.append("t")
    litellm.custom_provider_map.append(
        CustomLLMItem(provider="t", custom_handler=MiniAssistantLLM())
    )

    litellm.provider_list.append("funasr")
