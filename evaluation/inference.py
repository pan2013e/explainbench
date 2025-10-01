import os
import backoff
import litellm

from typing import TypeVar
from dotenv import load_dotenv
from litellm import completion
from pydantic import BaseModel

__all__ = ['Model']

litellm.enable_json_schema_validation=True
litellm.drop_params=True

DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(DIR, '..', '.env')
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE)

Schema = TypeVar('Schema', bound=BaseModel)

class Model:
    def __init__(self, model_id: str, **kwargs):
        self.model_id = model_id
        self.token_usage = {
            'completion_tokens': 0,
            'prompt_tokens': 0,
            'total_tokens': 0
        }
        self.sampling_params = {
            "n": 1,
            "temperature": 1.0,
            "top_p": 1.0,
            "max_tokens": 2048,
        }
        self.sampling_params.update(kwargs)

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    def infer(self, messages: str | list[dict[str, str]], schema: type[Schema]) -> Schema:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        response = completion(
            model=self.model_id,
            messages=messages,
            response_format=schema,
            **self.sampling_params
        )
        self.token_usage['completion_tokens'] += response.usage.completion_tokens
        self.token_usage['prompt_tokens'] += response.usage.prompt_tokens
        self.token_usage['total_tokens'] += response.usage.total_tokens
        content = response.choices[0].message.content
        return schema.model_validate_json(content)
