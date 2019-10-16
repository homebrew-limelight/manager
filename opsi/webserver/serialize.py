import logging
from dataclasses import _MISSING_TYPE, asdict, fields
from typing import Any, Callable, Dict, List, Optional, Type

from opsi.manager.link import NodeLink
from opsi.manager.manager import Manager
from opsi.manager.manager_schema import Function, ModuleItem
from opsi.manager.pipeline import Connection, Link, Links, Pipeline, StaticLink
from opsi.manager.types import *
from opsi.util.concurrency import FifoLock

from .schema import *

__all__ = (
    "export_manager",
    "export_nodetree",
    "import_nodetree",
    "NodeTreeImportError",
)

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------


def _rangetype_serialize(type):
    if not isinstance(type, RangeType):
        return None

    return InputOutputF(type="range", params=type.serialize())


def _slide_serialize(type):
    if not isinstance(type, Slide):
        return None

    return InputOutputF(type="slide", params=type.serialize())


def _tuple_serialize(type):
    if not isinstance(type, tuple):
        return None

    return InputOutputF(type="box", params={"options": type})


_type_name: Dict[Type, str] = {
    float: "dec",
    bool: "boolean",
    MatBW: "mbw",
    Contour: "cnt",
    Contours: "cts",
    AnyType: "any",
}
_normal_types = {int, str, Mat}

# Each item in _abnormal_types takes in a type and returns InputOutputF if the
# parser supports the type, or None if it does not
_abnormal_types: List[Callable[[Type[any]], Optional[InputOutputF]]] = [
    _slide_serialize,
    _rangetype_serialize,
    _tuple_serialize,
]  # add new type parsers here


def get_type(_type: Type) -> InputOutputF:
    if (_type is None) or (_type == type(None)):
        return None

    if _type in _type_name:
        name = _type_name.get(_type)
        return InputOutputF(type=name)
    elif _type in _normal_types:
        return InputOutputF(type=_type.__name__)

    for parser in _abnormal_types:
        IO = parser(_type)

        if IO is not None:
            return IO

    raise TypeError(f"Unknown type {_type} ({type(_type)})")


def get_field_type(field) -> InputOutputF:
    io = get_type(field.type)
    if field.default and type(field.default) is not _MISSING_TYPE:
        io.params["default"] = field.default
    return io


def get_types(types):
    pruned_types = []
    # if none, just don't show it
    for _type in types:
        if _type[1] is not type(None):
            pruned_types.append(_type)
    return {name: get_type(type) for name, type in pruned_types}


def get_settings_types(types):
    pruned_types = []
    # if none, just don't show it
    for _type in types:
        if type(_type.type) is not type(None):
            pruned_types.append(_type)
    return {field.name: get_field_type(field) for field in pruned_types}


def _serialize_funcs(funcs: Dict[str, Type[Function]]) -> List[FunctionF]:
    return [
        FunctionF(
            name=func.__name__,
            type=func.type,
            settings=get_settings_types(func.SettingTypes),
            inputs=get_types(func.InputTypes.items()),
            outputs=get_types(func.OutputTypes.items()),
        )
        for func in funcs.values()
    ]


def _serialize_modules(modules: Dict[str, ModuleItem]) -> List[ModuleF]:
    return [
        ModuleF(
            package=mod_package,
            version=mod.info.version,
            funcs=_serialize_funcs(mod.funcs),
        )
        for mod_package, mod in modules.items()
    ]


def export_manager(manager: Manager) -> SchemaF:
    if FUNC_INSTEAD_OF_MODS:
        return SchemaF(funcs=_serialize_funcs(manager.funcs))
    else:
        return SchemaF(modules=_serialize_modules(manager.modules))


# ---------------------------------------------------------


# removes all Nones from dict
def _prune_factory(inp):
    pruned = {}
    for i in inp:
        if i[1] is not None:
            pruned[i[0]] = i[1]
    return pruned


def _serialize_settings(settings) -> Dict[str, Any]:
    if settings is None:
        return {}

    return asdict(settings, dict_factory=_prune_factory)


def _serialize_link(link: Optional[Link]) -> Optional[LinkN]:
    if link is None:
        return None

    if isinstance(link, StaticLink):
        return None
    if isinstance(link, NodeLink):
        return LinkN(id=link.node.id, name=link.name)

    raise TypeError(f"Unknown link type: {type(link)}")


def _serialize_input(link: Optional[Link]) -> InputN:
    linkn = _serialize_link(link)

    if link is None:
        return InputN(link=linkn, value=None)

    if isinstance(link, StaticLink):
        return InputN(link=linkn, value=link.value)

    raise TypeError(f"Unknown link type: {type(link)}")


def export_nodetree(pipeline: Pipeline) -> NodeTreeN:
    nodes: List[NodeN] = []

    for id, node in pipeline.nodes.items():
        # allow importing legacy nodetrees
        try:
            node.pos = [] if node.pos is None else node.pos
        except AttributeError:
            node.pos = []
            LOGGER.debug("Initalized default value for node", exc_info=True)
        nodes.append(
            NodeN(
                type=node.func_type.type,
                id=id,
                settings=_serialize_settings(node.settings),
                pos=node.pos,
                inputs={
                    name: (
                        _serialize_link(link)
                        if LINKS_INSTEAD_OF_INPUTS
                        else _serialize_input(link)
                    )
                    for name, link in node.inputLinks.items()
                },
            )
        )

    return NodeTreeN(nodes=nodes)


# ---------------------------------------------------------


class NodeTreeImportError(ValueError):
    def __init__(self, node: NodeN = None, msg=""):
        self.node = node

        if not self.node:
            super().__init__(msg)
        else:
            super().__init__(f"Node '{self.node.id}' of type '{node.type}' {msg}")

        # since exc_info == True, this class must not be instantiated outside an `except:` clause
        LOGGER.debug(f"Error during nodetree import: {self.args[0]}", exc_info=True)


def _process_node_links(program, node: NodeN) -> List[str]:
    links: Links = {}
    empty_links: List[str] = []

    link: Optional[LinkN]

    for name, input in node.inputs.items():
        if LINKS_INSTEAD_OF_INPUTS:
            link = input
        else:
            link = input.link

        if link is None:
            empty_links.append(name)
            continue

        links[name] = Connection(link.id, link.name)

    program.pipeline.create_links(node.id, links)

    return empty_links


def _process_widget(type: Type, val):
    if isinstance(type, _RangeBaseType):
        # if type == RangeType:
        #   Val is a Tuple[float, float]
        #   Convert to Range
        # if type == Slide:
        #   Val needs to be validated
        val = type.create(*val)

    return val


def _process_node_inputs(program, node: NodeN):
    empty_links = _process_node_links(program, node)

    if LINKS_INSTEAD_OF_INPUTS:
        return

    # node.inputs : Dict[str, InputN]
    real_node = program.pipeline.nodes[node.id]

    for name in empty_links:
        type = real_node.func.InputTypes[name]
        real_node.set_static_link(name, _process_widget(type, node.inputs[name].value))


def _process_node_settings(program, node: NodeN):
    if None in node.settings.values():
        raise NodeTreeImportError(node, "Cannot have None value in settings")

    real_node = program.pipeline.nodes[node.id]
    real_node.pos = node.pos
    try:
        settings = real_node.func_type.Settings(**node.settings)
        real_node.settings = settings
    except TypeError as e:
        # intialize node with default settings
        default_fields = {}
        dc_fields = fields(real_node.func_type.Settings)
        for field in dc_fields:
            if type(field.default) is _MISSING_TYPE:
                # create a defaultly initalized class if default not defined
                default_fields[field.name] = field.type.__class__()
            else:
                default_fields[field.name] = field.default
        real_node.settings = real_node.func_type.Settings(**default_fields)
        # TODO: (ASAP) re-enable this. it's a bit buggy when this is disabled (nodetree gets continually imported??)
        # raise NodeTreeImportError(
        #     node, "Missing key in settings. Default initalizing..."
        # ) from e


def import_nodetree(program, nodetree: NodeTreeN):
    # todo: how to cache FifoLock in the stateless import_nodetree function?
    with FifoLock(program.queue):
        ids = [node.id for node in nodetree.nodes]
        program.pipeline.prune_nodetree(ids)

        for node in nodetree.nodes:
            if node.id not in program.pipeline.nodes:
                program.create_node(node.type, node.id)

        for node in nodetree.nodes:
            _process_node_settings(program, node)
            if LINKS_INSTEAD_OF_INPUTS:
                _process_node_links(program, node)
            else:
                _process_node_inputs(program, node)
