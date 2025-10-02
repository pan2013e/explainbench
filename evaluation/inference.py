import os
import backoff
import litellm

from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
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

COSTINFO = {
    'gemini/gemini-2.5-flash-lite': {
        'currency': 'USD',
        'currency_symbol': '$',
        'unit': 1_000_000,
        'input_price': 0.10,
        'output_price': 0.20,
    }
}

class Model:
    def __init__(self, model_id: str, **kwargs):
        self.model_id = model_id
        self.write_lock = Lock()
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
    def infer_once(self, messages: str | list[dict[str, str]], schema: type[Schema]) -> Schema:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        params = self.sampling_params.copy()
        if 'n' in params:
            params['n'] = 1
        response = completion(
            model=self.model_id,
            messages=messages,
            response_format=schema,
            **params
        )
        with self.write_lock:
            self.token_usage['completion_tokens'] += response.usage.completion_tokens
            self.token_usage['prompt_tokens'] += response.usage.prompt_tokens
            self.token_usage['total_tokens'] += response.usage.total_tokens
        content = response.choices[0].message.content
        return schema.model_validate_json(content)
    
    def infer(self, messages: str | list[dict[str, str]], schema: type[Schema]) -> list[Schema]:
        num_gens = self.sampling_params.get('n', 1)
        if num_gens == 1:
            return [self.infer_once(messages, schema)]
        generations = []
        with ThreadPoolExecutor(max_workers=min(10, num_gens)) as executor:
            futures = [executor.submit(self.infer_once, messages, schema) for _ in range(num_gens)]
            for future in as_completed(futures):
                generations.append(future.result())
        return generations
    
    def tqdm_usage(self):
        
        def fmt_token(num):
            if num >= 1_000_000:
                return f'{num/1_000_000:.2f}Mt'
            elif num >= 1_000:
                return f'{num/1_000:.2f}Kt'
            else:
                return f'{num}t'
        
        if self.model_id in COSTINFO:
            info = COSTINFO[self.model_id]
            price = (info['input_price'] * self.token_usage['prompt_tokens'] +
                     info['output_price'] * self.token_usage['completion_tokens']) / info['unit']
            return {
                'cost': f"{info['currency_symbol']}{price:.3f}",
            }
        else:
            return {
                'p': fmt_token(self.token_usage['prompt_tokens']),
                'c': fmt_token(self.token_usage['completion_tokens']),
                't': fmt_token(self.token_usage['total_tokens']),
            }

    def clear_usage(self):
        self.token_usage = {
            'completion_tokens': 0,
            'prompt_tokens': 0,
            'total_tokens': 0
        }
