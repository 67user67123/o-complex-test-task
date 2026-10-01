from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["client", "manager"]
    content: str = Field(min_length=1, max_length=6000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Реплика не может быть пустой.")
        return value.strip()


class SuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=6000)
    history: list[Message] = Field(default_factory=list, max_length=30)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Введите обращение клиента.")
        return value.strip()

    @model_validator(mode="after")
    def limit_history(self):
        if sum(len(item.content) for item in self.history) > 20000:
            raise ValueError("История переписки должна быть не длиннее 20000 символов.")
        return self


class GeneratedReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_reply: str = Field(min_length=1, max_length=4000)
    manager_tip: str = Field(min_length=1, max_length=2500)

    @field_validator("client_reply", "manager_tip")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Модель вернула пустой текст.")
        return value.strip()


class Source(BaseModel):
    id: str
    title: str
    kind: str
    score: float


class Timings(BaseModel):
    retrieval_ms: int
    generation_ms: int
    total_ms: int


class SuggestResponse(GeneratedReply):
    sources: list[Source]
    timings: Timings
