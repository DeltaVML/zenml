#  Copyright (c) ZenML GmbH 2021. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.
"""Step decorator function."""

from types import FunctionType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    overload,
)

from zenml.logger import get_logger
from zenml.steps import BaseStep

if TYPE_CHECKING:
    from zenml.config.base_settings import SettingsOrDict
    from zenml.config.source import Source
    from zenml.materializers.base_materializer import BaseMaterializer

    MaterializerClassOrSource = Union[str, "Source", Type["BaseMaterializer"]]
    HookSpecification = Union[str, "Source", FunctionType]
    OutputMaterializersSpecification = Union[
        "MaterializerClassOrSource",
        Sequence["MaterializerClassOrSource"],
        Mapping[str, "MaterializerClassOrSource"],
        Mapping[str, Sequence["MaterializerClassOrSource"]],
    ]


STEP_INNER_FUNC_NAME = "entrypoint"
PARAM_STEP_NAME = "name"
PARAM_ENABLE_CACHE = "enable_cache"
PARAM_ENABLE_ARTIFACT_METADATA = "enable_artifact_metadata"
PARAM_ENABLE_ARTIFACT_VISUALIZATION = "enable_artifact_visualization"
PARAM_STEP_OPERATOR = "step_operator"
PARAM_EXPERIMENT_TRACKER = "experiment_tracker"
CLASS_CONFIGURATION = "_CLASS_CONFIGURATION"
PARAM_OUTPUT_ARTIFACTS = "output_artifacts"
PARAM_OUTPUT_MATERIALIZERS = "output_materializers"
PARAM_SETTINGS = "settings"
PARAM_EXTRA_OPTIONS = "extra"
PARAM_ON_FAILURE = "on_failure"
PARAM_ON_SUCCESS = "on_success"

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class _DecoratedStep(BaseStep):
    _CLASS_CONFIGURATION: ClassVar[Optional[Dict[str, Any]]] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        class_config = self._CLASS_CONFIGURATION or {}
        kwargs = {**class_config, **kwargs}
        super().__init__(*args, **kwargs)

    @property
    def source_object(self) -> Any:
        """The source object of this step.

        Returns:
            The source object of this step.
        """
        return self.entrypoint


@overload
def step(_func: F) -> Type[BaseStep]:
    ...


@overload
def step(
    *,
    name: Optional[str] = None,
    enable_cache: Optional[bool] = None,
    enable_artifact_metadata: Optional[bool] = None,
    enable_artifact_visualization: Optional[bool] = None,
    experiment_tracker: Optional[str] = None,
    step_operator: Optional[str] = None,
    output_materializers: Optional["OutputMaterializersSpecification"] = None,
    settings: Optional[Dict[str, "SettingsOrDict"]] = None,
    extra: Optional[Dict[str, Any]] = None,
    on_failure: Optional["HookSpecification"] = None,
    on_success: Optional["HookSpecification"] = None,
) -> Callable[[F], Type[BaseStep]]:
    ...


def step(
    _func: Optional[F] = None,
    *,
    name: Optional[str] = None,
    enable_cache: Optional[bool] = None,
    enable_artifact_metadata: Optional[bool] = None,
    enable_artifact_visualization: Optional[bool] = None,
    experiment_tracker: Optional[str] = None,
    step_operator: Optional[str] = None,
    output_materializers: Optional["OutputMaterializersSpecification"] = None,
    settings: Optional[Dict[str, "SettingsOrDict"]] = None,
    extra: Optional[Dict[str, Any]] = None,
    on_failure: Optional["HookSpecification"] = None,
    on_success: Optional["HookSpecification"] = None,
) -> Union[Type[BaseStep], Callable[[F], Type[BaseStep]]]:
    """Outer decorator function for the creation of a ZenML step.

    In order to be able to work with parameters such as `name`, it features a
    nested decorator structure.

    Args:
        _func: The decorated function.
        name: The name of the step. If left empty, the name of the decorated
            function will be used as a fallback.
        enable_cache: Specify whether caching is enabled for this step. If no
            value is passed, caching is enabled by default unless the step
            requires a `StepContext` (see
            `zenml.steps.step_context.StepContext` for more information).
        enable_artifact_metadata: Specify whether metadata is enabled for this
            step. If no value is passed, metadata is enabled by default.
        enable_artifact_visualization: Specify whether visualization is enabled
            for this step. If no value is passed, visualization is enabled by
            default.
        experiment_tracker: The experiment tracker to use for this step.
        step_operator: The step operator to use for this step.
        output_materializers: Output materializers for this step. If
            given as a dict, the keys must be a subset of the output names
            of this step. If a single value (type or string) is given, the
            materializer will be used for all outputs.
        settings: Settings for this step.
        extra: Extra configurations for this step.
        on_failure: Callback function in event of failure of the step. Can be
            a function with three possible parameters,
            `StepContext`, `BaseParameters`, and `BaseException`,
            or a source path to a function of the same specifications
            (e.g. `module.my_function`).
        on_success: Callback function in event of failure of the step. Can be
            a function with two possible parameters, `StepContext` and
            `BaseParameters, or a source path to a function of the same specifications
            (e.g. `module.my_function`).

    Returns:
        The inner decorator which creates the step class based on the
        ZenML BaseStep
    """
    logger.warning(
        "The `@step` decorator that you use to define your step is "
        "deprecated. Check out our docs https://docs.zenml.io for "
        "information on how to define steps in a more intuitive and "
        "flexible way!"
    )

    def inner_decorator(func: F) -> Type[BaseStep]:
        """Inner decorator function for the creation of a ZenML Step.

        Args:
            func: types.FunctionType, this function will be used as the
                "process" method of the generated Step.

        Returns:
            The class of a newly generated ZenML Step.
        """
        return type(  # noqa
            func.__name__,
            (_DecoratedStep,),
            {
                STEP_INNER_FUNC_NAME: staticmethod(func),
                CLASS_CONFIGURATION: {
                    PARAM_STEP_NAME: name,
                    PARAM_ENABLE_CACHE: enable_cache,
                    PARAM_ENABLE_ARTIFACT_METADATA: enable_artifact_metadata,
                    PARAM_ENABLE_ARTIFACT_VISUALIZATION: enable_artifact_visualization,
                    PARAM_EXPERIMENT_TRACKER: experiment_tracker,
                    PARAM_STEP_OPERATOR: step_operator,
                    PARAM_OUTPUT_MATERIALIZERS: output_materializers,
                    PARAM_SETTINGS: settings,
                    PARAM_EXTRA_OPTIONS: extra,
                    PARAM_ON_FAILURE: on_failure,
                    PARAM_ON_SUCCESS: on_success,
                },
                "__module__": func.__module__,
                "__doc__": func.__doc__,
            },
        )

    if _func is None:
        return inner_decorator
    else:
        return inner_decorator(_func)
