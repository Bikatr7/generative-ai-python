from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import io
import inspect
import mimetypes
import typing
from typing import Any, Callable, Union
from typing_extensions import TypedDict

import pydantic

from google.generativeai.types import file_types
from google.ai import generativelanguage as glm

if typing.TYPE_CHECKING:
    import PIL.Image
    import IPython.display

    IMAGE_TYPES = (PIL.Image.Image, IPython.display.Image)
else:
    IMAGE_TYPES = ()
    try:
        import PIL.Image

        IMAGE_TYPES = IMAGE_TYPES + (PIL.Image.Image,)
    except ImportError:
        PIL = None

    try:
        import IPython.display

        IMAGE_TYPES = IMAGE_TYPES + (IPython.display.Image,)
    except ImportError:
        IPython = None


__all__ = [
    "BlobDict",
    "BlobType",
    "PartDict",
    "PartType",
    "ContentDict",
    "ContentType",
    "StrictContentType",
    "ContentsType",
    "FunctionDeclaration",
    "CallableFunctionDeclaration",
    "FunctionDeclarationType",
    "Tool",
    "ToolDict",
    "ToolsType",
    "FunctionLibrary",
    "FunctionLibraryType",
]


def pil_to_blob(img):
    bytesio = io.BytesIO()
    if isinstance(img, PIL.PngImagePlugin.PngImageFile):
        img.save(bytesio, format="PNG")
        mime_type = "image/png"
    else:
        img.save(bytesio, format="JPEG")
        mime_type = "image/jpeg"
    bytesio.seek(0)
    data = bytesio.read()
    return glm.Blob(mime_type=mime_type, data=data)


def image_to_blob(image) -> glm.Blob:
    if PIL is not None:
        if isinstance(image, PIL.Image.Image):
            return pil_to_blob(image)

    if IPython is not None:
        if isinstance(image, IPython.display.Image):
            name = image.filename
            if name is None:
                raise ValueError(
                    "Can only convert `IPython.display.Image` if "
                    "it is constructed from a local file (Image(filename=...))."
                )

            mime_type, _ = mimetypes.guess_type(name)
            if mime_type is None:
                mime_type = "image/unknown"

            return glm.Blob(mime_type=mime_type, data=image.data)

    raise TypeError(
        "Could not convert image. expected an `Image` type"
        "(`PIL.Image.Image` or `IPython.display.Image`).\n"
        f"Got a: {type(image)}\n"
        f"Value: {image}"
    )


class BlobDict(TypedDict):
    mime_type: str
    data: bytes


def _convert_dict(d: Mapping) -> glm.Content | glm.Part | glm.Blob:
    if is_content_dict(d):
        content = dict(d)
        if isinstance(parts := content["parts"], str):
            content["parts"] = [parts]
        content["parts"] = [to_part(part) for part in content["parts"]]
        return glm.Content(content)
    elif is_part_dict(d):
        part = dict(d)
        if "inline_data" in part:
            part["inline_data"] = to_blob(part["inline_data"])
        if "file_data" in part:
            part["file_data"] = to_file_data(part["file_data"])
        return glm.Part(part)
    elif is_blob_dict(d):
        blob = d
        return glm.Blob(blob)
    else:
        raise KeyError(
            "Could not recognize the intended type of the `dict`. "
            "A `Content` should have a 'parts' key. "
            "A `Part` should have a 'inline_data' or a 'text' key. "
            "A `Blob` should have 'mime_type' and 'data' keys. "
            f"Got keys: {list(d.keys())}"
        )


def is_blob_dict(d):
    return "mime_type" in d and "data" in d


if typing.TYPE_CHECKING:
    BlobType = Union[
        glm.Blob, BlobDict, PIL.Image.Image, IPython.display.Image
    ]  # Any for the images
else:
    BlobType = Union[glm.Blob, BlobDict, Any]


def to_blob(blob: BlobType) -> glm.Blob:
    if isinstance(blob, Mapping):
        blob = _convert_dict(blob)

    if isinstance(blob, glm.Blob):
        return blob
    elif isinstance(blob, IMAGE_TYPES):
        return image_to_blob(blob)
    else:
        if isinstance(blob, Mapping):
            raise KeyError(
                "Could not recognize the intended type of the `dict`\n" "A content should have "
            )
        raise TypeError(
            "Could not create `Blob`, expected `Blob`, `dict` or an `Image` type"
            "(`PIL.Image.Image` or `IPython.display.Image`).\n"
            f"Got a: {type(blob)}\n"
            f"Value: {blob}"
        )


class FileDataDict(TypedDict):
    mime_type: str
    file_uri: str


FileDataType = Union[FileDataDict, glm.FileData, file_types.File]


def to_file_data(file_data: FileDataType):
    if isinstance(file_data, dict):
        if "file_uri" in file_data:
            file_data = glm.FileData(file_data)
        else:
            file_data = glm.File(file_data)

    if isinstance(file_data, file_types.File):
        file_data = file_data.to_proto()

    if isinstance(file_data, (glm.File, file_types.File)):
        file_data = glm.FileData(
            mime_type=file_data.mime_type,
            file_uri=file_data.uri,
        )

    if isinstance(file_data, glm.FileData):
        return file_data
    else:
        raise TypeError(f"Could not convert a {type(file_data)} to `FileData`")


class PartDict(TypedDict):
    text: str
    inline_data: BlobType


# When you need a `Part` accept a part object, part-dict, blob or string
PartType = Union[glm.Part, PartDict, BlobType, str, glm.FunctionCall, glm.FunctionResponse]


def is_part_dict(d):
    keys = list(d.keys())
    if len(keys) != 1:
        return False

    key = keys[0]

    return key in ["text", "inline_data", "function_call", "function_response", "file_data"]


def to_part(part: PartType):
    if isinstance(part, Mapping):
        part = _convert_dict(part)

    if isinstance(part, glm.Part):
        return part
    elif isinstance(part, str):
        return glm.Part(text=part)
    elif isinstance(part, glm.FileData):
        return glm.Part(file_data=part)
    elif isinstance(part, (glm.File, file_types.File)):
        return glm.Part(file_data=to_file_data(part))
    elif isinstance(part, glm.FunctionCall):
        return glm.Part(function_call=part)
    elif isinstance(part, glm.FunctionCall):
        return glm.Part(function_response=part)

    else:
        # Maybe it can be turned into a blob?
        return glm.Part(inline_data=to_blob(part))


class ContentDict(TypedDict):
    parts: list[PartType]
    role: str


def is_content_dict(d):
    return "parts" in d


# When you need a message accept a `Content` object or dict, a list of parts,
# or a single part
ContentType = Union[glm.Content, ContentDict, Iterable[PartType], PartType]

# For generate_content, we're not guessing roles for [[parts],[parts],[parts]] yet.
StrictContentType = Union[glm.Content, ContentDict]


def to_content(content: ContentType):
    if not content:
        raise ValueError("content must not be empty")

    if isinstance(content, Mapping):
        content = _convert_dict(content)

    if isinstance(content, glm.Content):
        return content
    elif isinstance(content, Iterable) and not isinstance(content, str):
        return glm.Content(parts=[to_part(part) for part in content])
    else:
        # Maybe this is a Part?
        return glm.Content(parts=[to_part(content)])


def strict_to_content(content: StrictContentType):
    if isinstance(content, Mapping):
        content = _convert_dict(content)

    if isinstance(content, glm.Content):
        return content
    else:
        raise TypeError(
            "Expected a `glm.Content` or a `dict(parts=...)`.\n"
            f"Got type: {type(content)}\n"
            f"Value: {content}\n"
        )


ContentsType = Union[ContentType, Iterable[StrictContentType], None]


def to_contents(contents: ContentsType) -> list[glm.Content]:
    if contents is None:
        return []

    if isinstance(contents, Iterable) and not isinstance(contents, (str, Mapping)):
        try:
            # strict_to_content so [[parts], [parts]] doesn't assume roles.
            contents = [strict_to_content(c) for c in contents]
            return contents
        except TypeError:
            # If you get a TypeError here it's probably because that was a list
            # of parts, not a list of contents, so fall back to `to_content`.
            pass

    contents = [to_content(contents)]
    return contents


def _generate_schema(
    f: Callable[..., Any],
    *,
    descriptions: Mapping[str, str] | None = None,
    required: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Generates the OpenAPI Schema for a python function.

    Args:
        f: The function to generate an OpenAPI Schema for.
        descriptions: Optional. A `{name: description}` mapping for annotating input
            arguments of the function with user-provided descriptions. It
            defaults to an empty dictionary (i.e. there will not be any
            description for any of the inputs).
        required: Optional. For the user to specify the set of required arguments in
            function calls to `f`. If unspecified, it will be automatically
            inferred from `f`.

    Returns:
        dict[str, Any]: The OpenAPI Schema for the function `f` in JSON format.
    """
    if descriptions is None:
        descriptions = {}
    if required is None:
        required = []
    defaults = dict(inspect.signature(f).parameters)
    fields_dict = {
        name: (
            # 1. We infer the argument type here: use Any rather than None so
            # it will not try to auto-infer the type based on the default value.
            (param.annotation if param.annotation != inspect.Parameter.empty else Any),
            pydantic.Field(
                # 2. We do not support default values for now.
                # default=(
                #     param.default if param.default != inspect.Parameter.empty
                #     else None
                # ),
                # 3. We support user-provided descriptions.
                description=descriptions.get(name, None),
            ),
        )
        for name, param in defaults.items()
        # We do not support *args or **kwargs
        if param.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_ONLY,
        )
    }
    parameters = pydantic.create_model(f.__name__, **fields_dict).schema()
    # Postprocessing
    # 4. Suppress unnecessary title generation:
    #    * https://github.com/pydantic/pydantic/issues/1051
    #    * http://cl/586221780
    parameters.pop("title", None)
    for name, function_arg in parameters.get("properties", {}).items():
        function_arg.pop("title", None)
        annotation = defaults[name].annotation
        # 5. Nullable fields:
        #     * https://github.com/pydantic/pydantic/issues/1270
        #     * https://stackoverflow.com/a/58841311
        #     * https://github.com/pydantic/pydantic/discussions/4872
        if typing.get_origin(annotation) is typing.Union and type(None) in typing.get_args(
            annotation
        ):
            function_arg["nullable"] = True
    # 6. Annotate required fields.
    if required:
        # We use the user-provided "required" fields if specified.
        parameters["required"] = required
    else:
        # Otherwise we infer it from the function signature.
        parameters["required"] = [
            k
            for k in defaults
            if (
                defaults[k].default == inspect.Parameter.empty
                and defaults[k].kind
                in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                    inspect.Parameter.POSITIONAL_ONLY,
                )
            )
        ]
    schema = dict(name=f.__name__, description=f.__doc__, parameters=parameters)
    return schema


def _rename_schema_fields(schema):
    if schema is None:
        return schema

    schema = schema.copy()

    type_ = schema.pop("type", None)
    if type_ is not None:
        schema["type_"] = type_.upper()

    format_ = schema.pop("format", None)
    if format_ is not None:
        schema["format_"] = format_

    items = schema.pop("items", None)
    if items is not None:
        schema["items"] = _rename_schema_fields(items)

    properties = schema.pop("properties", None)
    if properties is not None:
        schema["properties"] = {k: _rename_schema_fields(v) for k, v in properties.items()}

    return schema


class FunctionDeclaration:
    def __init__(self, *, name: str, description: str, parameters: dict[str, Any] | None = None):
        """A  class wrapping a `glm.FunctionDeclaration`, describes a function for `genai.GenerativeModel`'s `tools`."""
        self._proto = glm.FunctionDeclaration(
            name=name, description=description, parameters=_rename_schema_fields(parameters)
        )

    @property
    def name(self) -> str:
        return self._proto.name

    @property
    def description(self) -> str:
        return self._proto.description

    @property
    def parameters(self) -> glm.Schema:
        return self._proto.parameters

    @classmethod
    def from_proto(cls, proto) -> FunctionDeclaration:
        self = cls(name="", description="", parameters={})
        self._proto = proto
        return self

    def to_proto(self) -> glm.FunctionDeclaration:
        return self._proto

    @staticmethod
    def from_function(function: Callable[..., Any], descriptions: dict[str, str] | None = None):
        """Builds a `CallableFunctionDeclaration` from a python function.

        The function should have type annotations.

        This method is able to generate the schema for arguments annotated with types:

        `AllowedTypes = float | int | str | list[AllowedTypes] | dict`

        This method does not yet build a schema for `TypedDict`, that would allow you to specify the dictionary
        contents. But you can build these manually.
        """

        if descriptions is None:
            descriptions = {}

        schema = _generate_schema(function, descriptions=descriptions)

        return CallableFunctionDeclaration(**schema, function=function)


StructType = dict[str, "ValueType"]
ValueType = Union[float, str, bool, StructType, list["ValueType"], None]


class CallableFunctionDeclaration(FunctionDeclaration):
    """An extension of `FunctionDeclaration` that can be built from a python function, and is callable.

    Note: The python function must have type annotations.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        function: Callable[..., Any],
    ):
        super().__init__(name=name, description=description, parameters=parameters)
        self.function = function

    def __call__(self, fc: glm.FunctionCall) -> glm.FunctionResponse:
        result = self.function(**fc.args)
        if not isinstance(result, dict):
            result = {"result": result}
        return glm.FunctionResponse(name=fc.name, response=result)


FunctionDeclarationType = Union[
    FunctionDeclaration,
    glm.FunctionDeclaration,
    dict[str, Any],
    Callable[..., Any],
]


def _make_function_declaration(
    fun: FunctionDeclarationType,
) -> FunctionDeclaration | glm.FunctionDeclaration:
    if isinstance(fun, (FunctionDeclaration, glm.FunctionDeclaration)):
        return fun
    elif isinstance(fun, dict):
        if "function" in fun:
            return CallableFunctionDeclaration(**fun)
        else:
            return FunctionDeclaration(**fun)
    elif callable(fun):
        return CallableFunctionDeclaration.from_function(fun)
    else:
        raise TypeError(
            "Expected an instance of `genai.FunctionDeclaraionType`. Got a:\n" f"  {type(fun)=}\n",
            fun,
        )


def _encode_fd(fd: FunctionDeclaration | glm.FunctionDeclaration) -> glm.FunctionDeclaration:
    if isinstance(fd, glm.FunctionDeclaration):
        return fd

    return fd.to_proto()


class Tool:
    """A wrapper for `glm.Tool`, Contains a collection of related `FunctionDeclaration` objects."""

    def __init__(self, function_declarations: Iterable[FunctionDeclarationType]):
        # The main path doesn't use this but is seems useful.
        self._function_declarations = [_make_function_declaration(f) for f in function_declarations]
        self._index = {}
        for fd in self._function_declarations:
            name = fd.name
            if name in self._index:
                raise ValueError("")
            self._index[fd.name] = fd

        self._proto = glm.Tool(
            function_declarations=[_encode_fd(fd) for fd in self._function_declarations]
        )

    @property
    def function_declarations(self) -> list[FunctionDeclaration | glm.FunctionDeclaration]:
        return self._function_declarations

    def __getitem__(
        self, name: str | glm.FunctionCall
    ) -> FunctionDeclaration | glm.FunctionDeclaration:
        if not isinstance(name, str):
            name = name.name

        return self._index[name]

    def __call__(self, fc: glm.FunctionCall) -> glm.FunctionResponse | None:
        declaration = self[fc]
        if not callable(declaration):
            return None

        return declaration(fc)

    def to_proto(self):
        return self._proto


class ToolDict(TypedDict):
    function_declarations: list[FunctionDeclarationType]


ToolType = Union[
    Tool, glm.Tool, ToolDict, Iterable[FunctionDeclarationType], FunctionDeclarationType
]


def _make_tool(tool: ToolType) -> Tool:
    if isinstance(tool, Tool):
        return tool
    elif isinstance(tool, glm.Tool):
        return Tool(function_declarations=tool.function_declarations)
    elif isinstance(tool, dict):
        if "function_declarations" in tool:
            return Tool(**tool)
        else:
            fd = tool
            return Tool(function_declarations=[glm.FunctionDeclaration(**fd)])
    elif isinstance(tool, Iterable):
        return Tool(function_declarations=tool)
    else:
        try:
            return Tool(function_declarations=[tool])
        except Exception as e:
            raise TypeError(
                "Expected an instance of `genai.ToolType`. Got a:\n" f"  {type(tool)=}",
                tool,
            ) from e


class FunctionLibrary:
    """A container for a set of `Tool` objects, manages lookup and execution of their functions."""

    def __init__(self, tools: Iterable[ToolType]):
        tools = _make_tools(tools)
        self._tools = list(tools)
        self._index = {}
        for tool in self._tools:
            for declaration in tool.function_declarations:
                name = declaration.name
                if name in self._index:
                    raise ValueError(
                        f"A `FunctionDeclaration` named {name} is already defined. "
                        "Each `FunctionDeclaration` must be uniquely named."
                    )
                self._index[declaration.name] = declaration

    def __getitem__(
        self, name: str | glm.FunctionCall
    ) -> FunctionDeclaration | glm.FunctionDeclaration:
        if not isinstance(name, str):
            name = name.name

        return self._index[name]

    def __call__(self, fc: glm.FunctionCall) -> glm.Part | None:
        declaration = self[fc]
        if not callable(declaration):
            return None

        response = declaration(fc)
        return glm.Part(function_response=response)

    def to_proto(self):
        return [tool.to_proto() for tool in self._tools]


ToolsType = Union[Iterable[ToolType], ToolType]


def _make_tools(tools: ToolsType) -> list[Tool]:
    if isinstance(tools, Iterable) and not isinstance(tools, Mapping):
        tools = [_make_tool(t) for t in tools]
        if len(tools) > 1 and all(len(t.function_declarations) == 1 for t in tools):
            # flatten into a single tool.
            tools = [_make_tool([t.function_declarations[0] for t in tools])]
        return tools
    else:
        tool = tools
        return [_make_tool(tool)]


FunctionLibraryType = Union[FunctionLibrary, ToolsType]


def to_function_library(lib: FunctionLibraryType | None) -> FunctionLibrary | None:
    if lib is None:
        return lib
    elif isinstance(lib, FunctionLibrary):
        return lib
    else:
        return FunctionLibrary(tools=lib)


FunctionCallingMode = glm.FunctionCallingConfig.Mode

# fmt: off
_FUNCTION_CALLING_MODE = {
    1: FunctionCallingMode.AUTO,
    FunctionCallingMode.AUTO: FunctionCallingMode.AUTO,
    "mode_auto": FunctionCallingMode.AUTO,
    "auto": FunctionCallingMode.AUTO,

    2: FunctionCallingMode.ANY,
    FunctionCallingMode.ANY: FunctionCallingMode.ANY,
    "mode_any": FunctionCallingMode.ANY,
    "any": FunctionCallingMode.ANY,

    3: FunctionCallingMode.NONE,
    FunctionCallingMode.NONE: FunctionCallingMode.NONE,
    "mode_none": FunctionCallingMode.NONE,
    "none": FunctionCallingMode.NONE,
}
# fmt: on

FunctionCallingModeType = Union[FunctionCallingMode, str, int]


def to_function_calling_mode(x: FunctionCallingModeType) -> FunctionCallingMode:
    if isinstance(x, str):
        x = x.lower()
    return _FUNCTION_CALLING_MODE[x]


class FunctionCallingConfigDict(TypedDict):
    mode: FunctionCallingModeType
    allowed_function_names: list[str]


FunctionCallingConfigType = Union[FunctionCallingConfigDict, glm.FunctionCallingConfig]


def to_function_calling_config(obj: FunctionCallingConfigType) -> glm.FunctionCallingConfig:
    if isinstance(obj, (FunctionCallingMode, str, int)):
        obj = {"mode": to_function_calling_mode(obj)}

    return glm.FunctionCallingConfig(obj)


class ToolConfigDict:
    function_calling_config: FunctionCallingConfigType


ToolConfigType = Union[ToolConfigDict, glm.ToolConfig]


def to_tool_config(obj: ToolConfigType) -> glm.ToolConfig:
    if isinstance(obj, glm.ToolConfig):
        return obj
    elif isinstance(obj, dict):
        fcc = obj.pop("function_calling_config")
        fcc = to_function_calling_config(fcc)
        obj["function_calling_config"] = fcc
        return glm.ToolConfig(**obj)
    else:
        raise TypeError(
            f"Could not convert input to `glm.ToolConfig`: \n'" f"  type: {type(obj)}\n", obj
        )
