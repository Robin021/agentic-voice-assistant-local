import os
from typing import Any, Sequence
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from schemas import ChatMessage
from markupsafe import escape

# Initialize Jinja2 environment
env = Environment(
    loader=FileSystemLoader(os.path.dirname(__file__)),
    autoescape=select_autoescape(
        enabled_extensions=("md"),
        default_for_string=True,
        default=False,
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)


def get_prompt_template(
    prompt_name: str,
    configurable: dict[str, Any] | None = None,
) -> str:
    """
    Load and return a prompt template using Jinja2.

    Args:
        prompt_name: Name of the prompt template file (without .md extension)

    Returns:
        The template string with proper variable substitution syntax
    """
    # Convert state to dict for template rendering
    state_vars = {
        "CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"),
    }

    # Add configurable variables
    if configurable:

        def sanitize_recursive(data):
            if isinstance(data, str):
                return str(escape(data))
            elif isinstance(data, dict):
                return {key: sanitize_recursive(value) for key, value in data.items()}
            elif isinstance(data, list):
                return [sanitize_recursive(item) for item in data]
            else:
                return data

        sanitized_configurable = sanitize_recursive(configurable)
        state_vars.update(sanitized_configurable)  # type: ignore

    try:
        template = env.get_template(f"{prompt_name}.md")
        return template.render(**state_vars)
    except Exception as e:
        raise ValueError(f"Error loading template {prompt_name}: {e}")


def apply_prompt_template(
    prompt_name: str,
    messages: Sequence[ChatMessage],
    configurable: dict[str, Any] | None = None,
) -> list:
    """
    Apply template variables to a prompt template and return formatted messages.

    Args:
        prompt_name: Name of the prompt template to use
        state: Current agent state containing variables to substitute

    Returns:
        List of messages with the system prompt as the first message
    """
    try:
        system_prompt = get_prompt_template(
            prompt_name=prompt_name, configurable=configurable
        )
        return [{"role": "system", "content": system_prompt}] + [
            {"role": x.role, "content": x.content} for x in messages
        ]
    except Exception as e:
        raise ValueError(f"Error applying template {prompt_name}: {e}")


def apply_prompt(
    system_prompts: str,
    messages: Sequence[ChatMessage],
    configurable: dict[str, Any] | None = None,
) -> list:
    """
    Apply template variables to a prompt template and return formatted messages.

    Args:
        system_prompts: The system prompts to use
        state: Current agent state containing variables to substitute

    Returns:
        List of messages with the system prompt as the first message
    """
    try:
        return [{"role": "system", "content": str(escape(system_prompts))}] + [
            {"role": x.role, "content": x.content} for x in messages
        ]
    except Exception as e:
        raise ValueError(
            f"Error applying system prompts {str(escape(system_prompts))}: {e}"
        )
