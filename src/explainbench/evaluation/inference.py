"""LiteLLM-backed structured inference used by ExplainBench evaluation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import TypeVar

import backoff
import litellm
from dotenv import load_dotenv
from pydantic import BaseModel


PredictionModel = TypeVar("PredictionModel", bound=BaseModel)

COSTINFO = {
    "gpt-5.2-2025-12-11": {
        "currency": "$",
        "unit": 1_000_000,
        "input_price": 1.75,
        "output_price": 14.00,
    },
    "gpt-5-mini-2025-08-07": {
        "currency": "$",
        "unit": 1_000_000,
        "input_price": 0.25,
        "output_price": 2.00,
    },
    "gpt-5-nano-2025-08-07": {
        "currency": "$",
        "unit": 1_000_000,
        "input_price": 0.05,
        "output_price": 0.40,
    },
}

litellm.enable_json_schema_validation = True
litellm.drop_params = True


class Model:
    """Thread-safe structured-output model adapter compatible with legacy code."""

    def __init__(
        self,
        model_id: str,
        *,
        env_file: str | Path | None = None,
        **sampling_params,
    ) -> None:
        if env_file is None:
            load_dotenv()
        else:
            load_dotenv(dotenv_path=env_file)
        self.model_id = model_id
        self.write_lock = Lock()
        self.token_usage = self._empty_usage()
        self.sampling_params = {
            "n": 1,
            "temperature": 1.0,
            "top_p": 1.0,
            "max_tokens": 8192,
        }
        self.sampling_params.update(sampling_params)
        if self.sampling_params["n"] < 1:
            raise ValueError("n must be at least 1")

    @staticmethod
    def _empty_usage() -> dict[str, int]:
        return {
            "completion_tokens": 0,
            "prompt_tokens": 0,
            "total_tokens": 0,
        }

    @backoff.on_exception(backoff.expo, Exception, max_tries=5)
    def infer_once(
        self,
        messages: str | list[dict[str, str]],
        schema: type[PredictionModel],
    ) -> PredictionModel:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        params = self.sampling_params.copy()
        params["n"] = 1
        response = litellm.completion(
            model=self.model_id,
            messages=messages,
            response_format=schema,
            **params,
        )
        usage = response.usage
        with self.write_lock:
            self.token_usage["completion_tokens"] += usage.completion_tokens
            self.token_usage["prompt_tokens"] += usage.prompt_tokens
            self.token_usage["total_tokens"] += usage.total_tokens
        content = response.choices[0].message.content
        if not content:
            raise ValueError("model returned an empty structured response")
        return schema.model_validate_json(content)

    def infer(
        self,
        messages: str | list[dict[str, str]],
        schema: type[PredictionModel],
    ) -> list[PredictionModel]:
        num_generations = self.sampling_params["n"]
        if num_generations == 1:
            return [self.infer_once(messages, schema)]

        generations: list[PredictionModel] = []
        with ThreadPoolExecutor(max_workers=min(10, num_generations)) as executor:
            futures = [
                executor.submit(self.infer_once, messages, schema)
                for _ in range(num_generations)
            ]
            for future in as_completed(futures):
                generations.append(future.result())
        return generations

    def tqdm_usage(self) -> dict[str, str]:
        def format_tokens(number: int) -> str:
            if number >= 1_000_000:
                return f"{number / 1_000_000:.2f}Mt"
            if number >= 1_000:
                return f"{number / 1_000:.2f}Kt"
            return f"{number}t"

        if self.model_id in COSTINFO:
            info = COSTINFO[self.model_id]
            price = (
                info["input_price"] * self.token_usage["prompt_tokens"]
                + info["output_price"] * self.token_usage["completion_tokens"]
            ) / info["unit"]
            return {"cost": f"{info['currency']}{price:.3f}"}
        return {
            "p": format_tokens(self.token_usage["prompt_tokens"]),
            "c": format_tokens(self.token_usage["completion_tokens"]),
            "t": format_tokens(self.token_usage["total_tokens"]),
        }

    def clear_usage(self) -> None:
        with self.write_lock:
            self.token_usage = self._empty_usage()
