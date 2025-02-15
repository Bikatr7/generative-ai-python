"""Classes for working with the Gemini models."""

from __future__ import annotations

from collections.abc import Iterable
import dataclasses
import textwrap
from typing import Any
from typing import Union
import reprlib

# pylint: disable=bad-continuation, line-too-long


import google.api_core.exceptions
from google.ai import generativelanguage as glm
from google.generativeai import client
from google.generativeai import string_utils
from google.generativeai.types import content_types
from google.generativeai.types import generation_types
from google.generativeai.types import safety_types


class GenerativeModel:
    """
    The `genai.GenerativeModel` class wraps default parameters for calls to
    `GenerativeModel.generate_content`, `GenerativeModel.count_tokens`, and
    `GenerativeModel.start_chat`.

    This family of functionality is designed to support multi-turn conversations, and multimodal
    requests. What media-types are supported for input and output is model-dependant.

    >>> import google.generativeai as genai
    >>> import PIL.Image
    >>> genai.configure(api_key='YOUR_API_KEY')
    >>> model = genai.GenerativeModel('models/gemini-pro')
    >>> result = model.generate_content('Tell me a story about a magic backpack')
    >>> result.text
    "In the quaint little town of Lakeside, there lived a young girl named Lily..."

    Multimodal input:

    >>> model = genai.GenerativeModel('models/gemini-pro')
    >>> result = model.generate_content([
    ...     "Give me a recipe for these:", PIL.Image.open('scones.jpeg')])
    >>> result.text
    "**Blueberry Scones** ..."

    Multi-turn conversation:

    >>> chat = model.start_chat()
    >>> response = chat.send_message("Hi, I have some questions for you.")
    >>> response.text
    "Sure, I'll do my best to answer your questions..."

    To list the compatible model names use:

    >>> for m in genai.list_models():
    ...     if 'generateContent' in m.supported_generation_methods:
    ...         print(m.name)

    Arguments:
         model_name: The name of the model to query. To list compatible models use
         safety_settings: Sets the default safety filters. This controls which content is blocked
             by the api before being returned.
         generation_config: A `genai.GenerationConfig` setting the default generation parameters to
             use.
    """

    def __init__(
        self,
        model_name: str = "gemini-pro",
        safety_settings: safety_types.SafetySettingOptions | None = None,
        generation_config: generation_types.GenerationConfigType | None = None,
        tools: content_types.FunctionLibraryType | None = None,
        tool_config: content_types.ToolConfigType | None = None,
        system_instructions: content_types.ContentType | None = None,
    ):
        if "/" not in model_name:
            model_name = "models/" + model_name
        self._model_name = model_name
        self._safety_settings = safety_types.to_easy_safety_dict(
            safety_settings, harm_category_set="new"
        )
        self._generation_config = generation_types.to_generation_config_dict(generation_config)
        self._tools = content_types.to_function_library(tools)

        if tool_config is None:
            self._tool_config = None
        else:
            self._tool_config = content_types.to_tool_config(tool_config)

        if system_instructions is None:
            self._system_instructions = None
        else:
            self._system_instructions = content_types.to_content(system_instructions)

        self._client = None
        self._async_client = None

    @property
    def model_name(self):
        return self._model_name

    def __str__(self):
        return textwrap.dedent(
            f"""\
            genai.GenerativeModel(
                model_name='{self.model_name}',
                generation_config={self._generation_config},
                safety_settings={self._safety_settings},
                tools={self._tools},
            )"""
        )

    __repr__ = __str__

    def _prepare_request(
        self,
        *,
        contents: content_types.ContentsType,
        generation_config: generation_types.GenerationConfigType | None = None,
        safety_settings: safety_types.SafetySettingOptions | None = None,
        tools: content_types.FunctionLibraryType | None,
        tool_config: content_types.ToolConfigType | None,
    ) -> glm.GenerateContentRequest:
        """Creates a `glm.GenerateContentRequest` from raw inputs."""
        if not contents:
            raise TypeError("contents must not be empty")

        tools_lib = self._get_tools_lib(tools)
        if tools_lib is not None:
            tools_lib = tools_lib.to_proto()

        if tool_config is None:
            tool_config = self._tool_config
        else:
            tool_config = content_types.to_tool_config(tool_config)

        contents = content_types.to_contents(contents)

        generation_config = generation_types.to_generation_config_dict(generation_config)
        merged_gc = self._generation_config.copy()
        merged_gc.update(generation_config)

        safety_settings = safety_types.to_easy_safety_dict(safety_settings, harm_category_set="new")
        merged_ss = self._safety_settings.copy()
        merged_ss.update(safety_settings)
        merged_ss = safety_types.normalize_safety_settings(merged_ss, harm_category_set="new")

        return glm.GenerateContentRequest(
            model=self._model_name,
            contents=contents,
            generation_config=merged_gc,
            safety_settings=merged_ss,
            tools=tools_lib,
            tool_config=tool_config,
            system_instructions=self._system_instructions,
        )

    def _get_tools_lib(
        self, tools: content_types.FunctionLibraryType
    ) -> content_types.FunctionLibrary | None:
        if tools is None:
            return self._tools
        else:
            return content_types.to_function_library(tools)

    def generate_content(
        self,
        contents: content_types.ContentsType,
        *,
        generation_config: generation_types.GenerationConfigType | None = None,
        safety_settings: safety_types.SafetySettingOptions | None = None,
        stream: bool = False,
        tools: content_types.FunctionLibraryType | None = None,
        tool_config: content_types.ToolConfigType | None = None,
        request_options: dict[str, Any] | None = None,
    ) -> generation_types.GenerateContentResponse:
        """A multipurpose function to generate responses from the model.

        This `GenerativeModel.generate_content` method can handle multimodal input, and multi-turn
        conversations.

        >>> model = genai.GenerativeModel('models/gemini-pro')
        >>> response = model.generate_content('Tell me a story about a magic backpack')
        >>> response.text

        ### Streaming

        This method supports streaming with the `stream=True`. The result has the same type as the non streaming case,
        but you can iterate over the response chunks as they become available:

        >>> response = model.generate_content('Tell me a story about a magic backpack', stream=True)
        >>> for chunk in response:
        ...   print(chunk.text)

        ### Multi-turn

        This method supports multi-turn chats but is **stateless**: the entire conversation history needs to be sent with each
        request. This takes some manual management but gives you complete control:

        >>> messages = [{'role':'user', 'parts': ['hello']}]
        >>> response = model.generate_content(messages) # "Hello, how can I help"
        >>> messages.append(response.candidates[0].content)
        >>> messages.append({'role':'user', 'parts': ['How does quantum physics work?']})
        >>> response = model.generate_content(messages)

        For a simpler multi-turn interface see `GenerativeModel.start_chat`.

        ### Input type flexibility

        While the underlying API strictly expects a `list[glm.Content]` objects, this method
        will convert the user input into the correct type. The hierarchy of types that can be
        converted is below. Any of these objects can be passed as an equivalent `dict`.

        * `Iterable[glm.Content]`
        * `glm.Content`
        * `Iterable[glm.Part]`
        * `glm.Part`
        * `str`, `Image`, or `glm.Blob`

        In an `Iterable[glm.Content]` each `content` is a separate message.
        But note that an `Iterable[glm.Part]` is taken as the parts of a single message.

        Arguments:
            contents: The contents serving as the model's prompt.
            generation_config: Overrides for the model's generation config.
            safety_settings: Overrides for the model's safety settings.
            stream: If True, yield response chunks as they are generated.
            tools: `glm.Tools` more info coming soon.
            request_options: Options for the request.
        """
        request = self._prepare_request(
            contents=contents,
            generation_config=generation_config,
            safety_settings=safety_settings,
            tools=tools,
            tool_config=tool_config,
        )
        if self._client is None:
            self._client = client.get_default_generative_client()

        if request_options is None:
            request_options = {}

        try:
            if stream:
                with generation_types.rewrite_stream_error():
                    iterator = self._client.stream_generate_content(
                        request,
                        **request_options,
                    )
                return generation_types.GenerateContentResponse.from_iterator(iterator)
            else:
                response = self._client.generate_content(
                    request,
                    **request_options,
                )
                return generation_types.GenerateContentResponse.from_response(response)
        except google.api_core.exceptions.InvalidArgument as e:
            if e.message.startswith("Request payload size exceeds the limit:"):
                e.message += (
                    " Please upload your files with the File API instead."
                    "`f = genai.upload_file(path); m.generate_content(['tell me about this file:', f])`"
                )
            raise

    async def generate_content_async(
        self,
        contents: content_types.ContentsType,
        *,
        generation_config: generation_types.GenerationConfigType | None = None,
        safety_settings: safety_types.SafetySettingOptions | None = None,
        stream: bool = False,
        tools: content_types.FunctionLibraryType | None = None,
        tool_config: content_types.ToolConfigType | None = None,
        request_options: dict[str, Any] | None = None,
    ) -> generation_types.AsyncGenerateContentResponse:
        """The async version of `GenerativeModel.generate_content`."""
        request = self._prepare_request(
            contents=contents,
            generation_config=generation_config,
            safety_settings=safety_settings,
            tools=tools,
            tool_config=tool_config,
        )
        if self._async_client is None:
            self._async_client = client.get_default_generative_async_client()

        if request_options is None:
            request_options = {}

        try:
            if stream:
                with generation_types.rewrite_stream_error():
                    iterator = await self._async_client.stream_generate_content(
                        request,
                        **request_options,
                    )
                return await generation_types.AsyncGenerateContentResponse.from_aiterator(iterator)
            else:
                response = await self._async_client.generate_content(
                    request,
                    **request_options,
                )
                return generation_types.AsyncGenerateContentResponse.from_response(response)
        except google.api_core.exceptions.InvalidArgument as e:
            if e.message.startswith("Request payload size exceeds the limit:"):
                e.message += (
                    " Please upload your files with the File API instead."
                    "`f = genai.upload_file(path); m.generate_content(['tell me about this file:', f])`"
                )
            raise

    # fmt: off
    def count_tokens(
        self,
        contents: content_types.ContentsType,
        request_options: dict[str, Any] | None = None,
    ) -> glm.CountTokensResponse:
        if request_options is None:
            request_options = {}

        if self._client is None:
            self._client = client.get_default_generative_client()
        contents = content_types.to_contents(contents)
        return self._client.count_tokens(
            glm.CountTokensRequest(model=self.model_name, contents=contents),
                **request_options,
        )

    async def count_tokens_async(
        self,
        contents: content_types.ContentsType,
        request_options: dict[str, Any] | None = None,
    ) -> glm.CountTokensResponse:
        if request_options is None:
            request_options = {}

        if self._async_client is None:
            self._async_client = client.get_default_generative_async_client()
        contents = content_types.to_contents(contents)
        return await self._async_client.count_tokens(
            glm.CountTokensRequest(model=self.model_name, contents=contents),
                **request_options,
        )

    # fmt: on

    def start_chat(
        self,
        *,
        history: Iterable[content_types.StrictContentType] | None = None,
        enable_automatic_function_calling: bool = False,
    ) -> ChatSession:
        """Returns a `genai.ChatSession` attached to this model.

        >>> model = genai.GenerativeModel()
        >>> chat = model.start_chat(history=[...])
        >>> response = chat.send_message("Hello?")

        Arguments:
            history: An iterable of `glm.Content` objects, or equvalents to initialize the session.
        """
        if self._generation_config.get("candidate_count", 1) > 1:
            raise ValueError("Can't chat with `candidate_count > 1`")
        return ChatSession(
            model=self,
            history=history,
            enable_automatic_function_calling=enable_automatic_function_calling,
        )


class ChatSession:
    """Contains an ongoing conversation with the model.

    >>> model = genai.GenerativeModel(model="gemini-pro")
    >>> chat = model.start_chat()
    >>> response = chat.send_message("Hello")
    >>> print(response.text)
    >>> response = chat.send_message(...)

    This `ChatSession` object collects the messages sent and received, in its
    `ChatSession.history` attribute.

    Arguments:
        model: The model to use in the chat.
        history: A chat history to initialize the object with.
    """

    _USER_ROLE = "user"
    _MODEL_ROLE = "model"

    def __init__(
        self,
        model: GenerativeModel,
        history: Iterable[content_types.StrictContentType] | None = None,
        enable_automatic_function_calling: bool = False,
    ):
        self.model: GenerativeModel = model
        self._history: list[glm.Content] = content_types.to_contents(history)
        self._last_sent: glm.Content | None = None
        self._last_received: generation_types.BaseGenerateContentResponse | None = None
        self.enable_automatic_function_calling = enable_automatic_function_calling

    def send_message(
        self,
        content: content_types.ContentType,
        *,
        generation_config: generation_types.GenerationConfigType = None,
        safety_settings: safety_types.SafetySettingOptions = None,
        stream: bool = False,
        tools: content_types.FunctionLibraryType | None = None,
        tool_config: content_types.ToolConfigType | None = None,
    ) -> generation_types.GenerateContentResponse:
        """Sends the conversation history with the added message and returns the model's response.

        Appends the request and response to the conversation history.

        >>> model = genai.GenerativeModel(model="gemini-pro")
        >>> chat = model.start_chat()
        >>> response = chat.send_message("Hello")
        >>> print(response.text)
        "Hello! How can I assist you today?"
        >>> len(chat.history)
        2

        Call it with `stream=True` to receive response chunks as they are generated:

        >>> chat = model.start_chat()
        >>> response = chat.send_message("Explain quantum physics", stream=True)
        >>> for chunk in response:
        ...   print(chunk.text, end='')

        Once iteration over chunks is complete, the `response` and `ChatSession` are in states identical to the
        `stream=False` case. Some properties are not available until iteration is complete.

        Like `GenerativeModel.generate_content` this method lets you override the model's `generation_config` and
        `safety_settings`.

        Arguments:
             content: The message contents.
             generation_config: Overrides for the model's generation config.
             safety_settings: Overrides for the model's safety settings.
             stream: If True, yield response chunks as they are generated.
        """
        if self.enable_automatic_function_calling and stream:
            raise NotImplementedError(
                "The `google.generativeai` SDK does not yet support `stream=True` with "
                "`enable_automatic_function_calling=True`"
            )

        tools_lib = self.model._get_tools_lib(tools)

        content = content_types.to_content(content)

        if not content.role:
            content.role = self._USER_ROLE

        history = self.history[:]
        history.append(content)

        generation_config = generation_types.to_generation_config_dict(generation_config)
        if generation_config.get("candidate_count", 1) > 1:
            raise ValueError("Can't chat with `candidate_count > 1`")

        response = self.model.generate_content(
            contents=history,
            generation_config=generation_config,
            safety_settings=safety_settings,
            stream=stream,
            tools=tools_lib,
            tool_config=tool_config,
        )

        self._check_response(response=response, stream=stream)

        if self.enable_automatic_function_calling and tools_lib is not None:
            self.history, content, response = self._handle_afc(
                response=response,
                history=history,
                generation_config=generation_config,
                safety_settings=safety_settings,
                stream=stream,
                tools_lib=tools_lib,
            )

        self._last_sent = content
        self._last_received = response

        return response

    def _check_response(self, *, response, stream):
        if response.prompt_feedback.block_reason:
            raise generation_types.BlockedPromptException(response.prompt_feedback)

        if not stream:
            if response.candidates[0].finish_reason not in (
                glm.Candidate.FinishReason.FINISH_REASON_UNSPECIFIED,
                glm.Candidate.FinishReason.STOP,
                glm.Candidate.FinishReason.MAX_TOKENS,
            ):
                raise generation_types.StopCandidateException(response.candidates[0])

    def _get_function_calls(self, response) -> list[glm.FunctionCall]:
        candidates = response.candidates
        if len(candidates) != 1:
            raise ValueError(
                f"Automatic function calling only works with 1 candidate, got: {len(candidates)}"
            )
        parts = candidates[0].content.parts
        function_calls = [part.function_call for part in parts if part and "function_call" in part]
        return function_calls

    def _handle_afc(
        self, *, response, history, generation_config, safety_settings, stream, tools_lib
    ) -> tuple[list[glm.Content], glm.Content, generation_types.BaseGenerateContentResponse]:

        while function_calls := self._get_function_calls(response):
            if not all(callable(tools_lib[fc]) for fc in function_calls):
                break
            history.append(response.candidates[0].content)

            function_response_parts: list[glm.Part] = []
            for fc in function_calls:
                fr = tools_lib(fc)
                assert fr is not None, (
                    "This should never happen, it should only return None if the declaration"
                    "is not callable, and that's guarded against above."
                )
                function_response_parts.append(fr)

            send = glm.Content(role=self._USER_ROLE, parts=function_response_parts)
            history.append(send)

            response = self.model.generate_content(
                contents=history,
                generation_config=generation_config,
                safety_settings=safety_settings,
                stream=stream,
                tools=tools_lib,
            )

            self._check_response(response=response, stream=stream)

        *history, content = history
        return history, content, response

    async def send_message_async(
        self,
        content: content_types.ContentType,
        *,
        generation_config: generation_types.GenerationConfigType = None,
        safety_settings: safety_types.SafetySettingOptions = None,
        stream: bool = False,
        tools: content_types.FunctionLibraryType | None = None,
        tool_config: content_types.ToolConfigType | None = None,
    ) -> generation_types.AsyncGenerateContentResponse:
        """The async version of `ChatSession.send_message`."""
        if self.enable_automatic_function_calling and stream:
            raise NotImplementedError(
                "The `google.generativeai` SDK does not yet support `stream=True` with "
                "`enable_automatic_function_calling=True`"
            )

        tools_lib = self.model._get_tools_lib(tools)

        content = content_types.to_content(content)

        if not content.role:
            content.role = self._USER_ROLE

        history = self.history[:]
        history.append(content)

        generation_config = generation_types.to_generation_config_dict(generation_config)
        if generation_config.get("candidate_count", 1) > 1:
            raise ValueError("Can't chat with `candidate_count > 1`")

        response = await self.model.generate_content_async(
            contents=history,
            generation_config=generation_config,
            safety_settings=safety_settings,
            stream=stream,
            tools=tools_lib,
            tool_config=tool_config,
        )

        self._check_response(response=response, stream=stream)

        if self.enable_automatic_function_calling and tools_lib is not None:
            self.history, content, response = await self._handle_afc_async(
                response=response,
                history=history,
                generation_config=generation_config,
                safety_settings=safety_settings,
                stream=stream,
                tools_lib=tools_lib,
            )

        self._last_sent = content
        self._last_received = response

        return response

    async def _handle_afc_async(
        self, *, response, history, generation_config, safety_settings, stream, tools_lib
    ) -> tuple[list[glm.Content], glm.Content, generation_types.BaseGenerateContentResponse]:

        while function_calls := self._get_function_calls(response):
            if not all(callable(tools_lib[fc]) for fc in function_calls):
                break
            history.append(response.candidates[0].content)

            function_response_parts: list[glm.Part] = []
            for fc in function_calls:
                fr = tools_lib(fc)
                assert fr is not None, (
                    "This should never happen, it should only return None if the declaration"
                    "is not callable, and that's guarded against above."
                )
                function_response_parts.append(fr)

            send = glm.Content(role=self._USER_ROLE, parts=function_response_parts)
            history.append(send)

            response = await self.model.generate_content_async(
                contents=history,
                generation_config=generation_config,
                safety_settings=safety_settings,
                stream=stream,
                tools=tools_lib,
            )

            self._check_response(response=response, stream=stream)

        *history, content = history
        return history, content, response

    def __copy__(self):
        return ChatSession(
            model=self.model,
            # Be sure the copy doesn't share the history.
            history=list(self.history),
        )

    def rewind(self) -> tuple[glm.Content, glm.Content]:
        """Removes the last request/response pair from the chat history."""
        if self._last_received is None:
            result = self._history.pop(-2), self._history.pop()
            return result
        else:
            result = self._last_sent, self._last_received.candidates[0].content
            self._last_sent = None
            self._last_received = None
            return result

    @property
    def last(self) -> generation_types.BaseGenerateContentResponse | None:
        """returns the last received `genai.GenerateContentResponse`"""
        return self._last_received

    @property
    def history(self) -> list[glm.Content]:
        """The chat history."""
        last = self._last_received
        if last is None:
            return self._history

        if last.candidates[0].finish_reason not in (
            glm.Candidate.FinishReason.FINISH_REASON_UNSPECIFIED,
            glm.Candidate.FinishReason.STOP,
            glm.Candidate.FinishReason.MAX_TOKENS,
        ):
            error = generation_types.StopCandidateException(last.candidates[0])
            last._error = error

        if last._error is not None:
            raise generation_types.BrokenResponseError(
                "Can not build a coherent char history after a broken "
                "streaming response "
                "(See the previous Exception fro details). "
                "To inspect the last response object, use `chat.last`."
                "To remove the last request/response `Content` objects from the chat "
                "call `last_send, last_received = chat.rewind()` and continue "
                "without it."
            ) from last._error

        sent = self._last_sent
        received = last.candidates[0].content
        if not received.role:
            received.role = self._MODEL_ROLE
        self._history.extend([sent, received])

        self._last_sent = None
        self._last_received = None

        return self._history

    @history.setter
    def history(self, history):
        self._history = content_types.to_contents(history)
        self._last_sent = None
        self._last_received = None

    def __repr__(self) -> str:
        _dict_repr = reprlib.Repr()
        _model = str(self.model).replace("\n", "\n" + " " * 4)

        def content_repr(x):
            return f"glm.Content({_dict_repr.repr(type(x).to_dict(x))})"

        try:
            history = list(self.history)
        except (generation_types.BrokenResponseError, generation_types.IncompleteIterationError):
            history = list(self._history)

        if self._last_sent is not None:
            history.append(self._last_sent)
        history = [content_repr(x) for x in history]

        last_received = self._last_received
        if last_received is not None:
            if last_received._error is not None:
                history.append("<STREAMING ERROR>")
            else:
                history.append("<STREAMING IN PROGRESS>")

        _history = ",\n    " + f"history=[{', '.join(history)}]\n)"

        return (
            textwrap.dedent(
                f"""\
                ChatSession(
                    model="""
            )
            + _model
            + _history
        )
