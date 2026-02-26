from typing import List
from agent_service.core.utils.config import MAX_RETRIES
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError


class LLM:
    """
    Wrapper cho ChatGoogleGenerativeAI với:
    - Retry tự động qua LangChain .with_retry() (exponential backoff)
    - API key rotation: khi 1 key hết quota, rotate sang key tiếp theo
    """

    def __init__(self, api_keys: List[str], model: str,
                 temperature: float = 0.5, max_tokens: int = 1024, top_p: float = 1.0):
        if not api_keys or not isinstance(api_keys, list):
            raise ValueError("api_keys must be a non-empty list of strings.")

        self.api_keys = api_keys
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

        self.current_key_index = 0
        self._tools = None
        self._bound_llm = None
        self._create_llm_instance()

        print(f"LLM class initialized for model '{model}' with {len(self.api_keys)} API keys.")

    def _create_llm_instance(self):
        """Tạo ChatGoogleGenerativeAI instance."""
        current_api_key = self.api_keys[self.current_key_index]

        self.llm = ChatGoogleGenerativeAI(
            api_key=current_api_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
        )

        # Nếu đã bind tools trước đó, bind lại trên instance mới
        if self._tools:
            self._bound_llm = self.llm.bind_tools(self._tools)

        print(f"LLM instance created with API key index: {self.current_key_index}")

    def _rotate_key(self):
        """Rotate sang API key tiếp theo và tạo lại LLM instance."""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        print(f"Rotating API key -> index: {self.current_key_index}")
        self._create_llm_instance()

    @staticmethod
    def _is_quota_error(error: Exception) -> bool:
        """Kiểm tra xem lỗi có phải do quota/rate limit không."""
        err_str = str(error).lower()
        return "429" in err_str or "resource_exhausted" in err_str

    def _get_target(self):
        """Lấy LLM target (có tools hoặc không), wrapped với .with_retry()."""
        base = self._bound_llm if self._bound_llm else self.llm
        return base.with_retry(
            retry_if_exception_type=(ChatGoogleGenerativeAIError,),
            wait_exponential_jitter=True,
            stop_after_attempt=MAX_RETRIES,
        )

    # ── Public API ───────────────────────────────────────────────────────

    def bind_tools(self, tools):
        """Bind tools. Returns self cho key rotation compatibility."""
        self._tools = tools
        self._bound_llm = self.llm.bind_tools(tools)
        return self

    async def ainvoke(self, messages):
        """
        Async invoke với:
        - .with_retry() xử lý exponential backoff (mỗi key)
        - Key rotation nếu tất cả retry của 1 key thất bại
        """
        for key_idx in range(len(self.api_keys)):
            try:
                target = self._get_target()
                return await target.ainvoke(messages)
            except ChatGoogleGenerativeAIError as e:
                if self._is_quota_error(e) and key_idx < len(self.api_keys) - 1:
                    print(f"[Key {self.current_key_index}] All retries failed. Rotating key...")
                    self._rotate_key()
                else:
                    raise

    def invoke(self, messages):
        """Sync invoke với retry + key rotation."""
        for key_idx in range(len(self.api_keys)):
            try:
                target = self._get_target()
                return target.invoke(messages)
            except ChatGoogleGenerativeAIError as e:
                if self._is_quota_error(e) and key_idx < len(self.api_keys) - 1:
                    print(f"[Key {self.current_key_index}] All retries failed. Rotating key...")
                    self._rotate_key()
                else:
                    raise

    def stream(self, messages):
        """Sync stream."""
        target = self._get_target()
        return target.stream(messages)

    async def astream(self, messages):
        """Async stream với key rotation."""
        for key_idx in range(len(self.api_keys)):
            try:
                target = self._get_target()
                async for chunk in target.astream(messages):
                    yield chunk
                return
            except ChatGoogleGenerativeAIError as e:
                if self._is_quota_error(e) and key_idx < len(self.api_keys) - 1:
                    print(f"[Key {self.current_key_index}] Stream failed. Rotating key...")
                    self._rotate_key()
                else:
                    raise

    def with_structured_output(self, output_schema, **kwargs):
        return self.llm.with_structured_output(output_schema, **kwargs)