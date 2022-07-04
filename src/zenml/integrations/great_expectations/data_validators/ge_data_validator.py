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
"""Implementation of the Great Expectations data validator."""

import os
from typing import Any, ClassVar, Dict, List, Optional, cast

import great_expectations as ge  # type: ignore[import]
import pandas as pd  # type: ignore[import]
import yaml
from great_expectations.data_context.data_context import (  # type: ignore[import]
    BaseDataContext,
    DataContext,
)
from great_expectations.data_context.types.base import (  # type: ignore[import]
    DataContextConfig,
)

from great_expectations.checkpoint.types.checkpoint_result import (  # type: ignore[import]
    CheckpointResult,
)
from great_expectations.core import ExpectationSuite  # type: ignore[import]
from great_expectations.data_context.types.resource_identifiers import (  # type: ignore[import]
    ExpectationSuiteIdentifier,
)
from great_expectations.profile.user_configurable_profiler import (  # type: ignore[import]
    UserConfigurableProfiler,
)
from pydantic import root_validator, validator

from zenml.data_validators import BaseDataValidator
from zenml.environment import Environment
from zenml.integrations.great_expectations import (
    GREAT_EXPECTATIONS_DATA_VALIDATOR_FLAVOR,
)
from zenml.integrations.great_expectations.ge_store_backend import (
    ZenMLArtifactStoreBackend,
)
from zenml.integrations.great_expectations.utils import (
    create_batch_request,
)
from zenml.io import fileio
from zenml.logger import get_logger
from zenml.repository import Repository
from zenml.steps import (
    STEP_ENVIRONMENT_NAME,
    StepEnvironment,
)
from zenml.utils import io_utils
from zenml.utils.string_utils import random_str

logger = get_logger(__name__)


class GreatExpectationsDataValidator(BaseDataValidator):
    """Great Expectations data validator stack component.

    Attributes:
        context_root_dir: location of an already initialized Great Expectations
            data context. If configured, the data validator will only be usable
            with local orchestrators.
        context_config: in-line Great Expectations data context configuration.
        configure_zenml_stores: if set, ZenML will automatically configure
            stores that use the Artifact Store as a backend. If neither
            `context_root_dir` nor `context_config` are set, this is the default
            behavior.
        configure_local_docs: configure a local data docs site where Great
            Expectations docs are generated and can be visualized locally.
    """

    context_root_dir: Optional[str] = None
    context_config: Optional[Dict[str, Any]] = None
    configure_zenml_stores: bool = False
    configure_local_docs: bool = True
    _context: BaseDataContext = None

    # Class Configuration
    FLAVOR: ClassVar[str] = GREAT_EXPECTATIONS_DATA_VALIDATOR_FLAVOR

    @validator("context_root_dir")
    def _ensure_valid_context_root_dir(
        cls, context_root_dir: Optional[str] = None
    ) -> Optional[str]:
        """Ensures that the root directory is an absolute path and points to an existing path.

        Args:
            context_root_dir: The context_root_dir value to validate.

        Returns:
            The context_root_dir if it is valid.

        Raises:
            ValueError: If the context_root_dir is not valid.
        """
        if context_root_dir:
            context_root_dir = os.path.abspath(context_root_dir)
            if not fileio.exists(context_root_dir):
                raise ValueError(
                    f"The Great Expectations context_root_dir value doesn't "
                    f"point to an existing data context path: {context_root_dir}"
                )
        return context_root_dir

    @root_validator(pre=True)
    def _convert_context_config(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Converts context_config from JSON/YAML string format to a dict.

        Args:
            values: Values passed to the object constructor

        Returns:
            Values passed to the object constructor

        Raises:
            ValueError: If the context_config value is not a valid JSON/YAML or
                if the GE configuration extracted from it fails GE validation.
        """
        context_config = values.get("context_config")
        if context_config and not isinstance(context_config, dict):
            try:
                context_config_dict = yaml.safe_load(context_config)
            except yaml.parser.ParserError as e:
                raise ValueError(
                    f"Malformed `context_config` value. Only JSON and YAML formats "
                    f"are supported: {str(e)}"
                )
            try:
                context_config = DataContextConfig(**context_config_dict)
                BaseDataContext(project_config=context_config)
            except Exception as e:
                raise ValueError(f"Invalid `context_config` value: {str(e)}")

            values["context_config"] = context_config_dict
        return values

    @classmethod
    def get_active_data_validator(cls) -> "GreatExpectationsDataValidator":
        """Get the Great Expectations data validator registered in the active stack.

        Returns:
            The Great Expectations data validator registered in the active stack.

        TypeError: if a Great Expectations data validator is not part of the
            active stack.
        """
        repo = Repository(skip_repository_check=True)  # type: ignore[call-arg]
        data_validator = repo.active_stack.data_validator
        if data_validator and isinstance(data_validator, cls):
            return data_validator

        raise TypeError(
            f"The active stack needs to have a Great Expectations data "
            f"validator component registered to be able to run data validation "
            f"actions with Great Expectations. You can create a new stack with "
            f"a Great Expectations data validator component or update your "
            f"existing stack to add this component, e.g.:\n\n"
            f"  `zenml data-validator register great_expectations "
            f"--flavor={cls.FLAVOR} ...`\n"
            f"  `zenml stack register stack-name -dv great_expectations ...`\n"
            f"  or:\n"
            f"  `zenml stack update -dv great_expectations`\n\n"
        )

    @classmethod
    def get_data_context(cls) -> BaseDataContext:
        """Get the Great Expectations data context managed by ZenML.

        Call this method to retrieve the data context managed by ZenML
        through the active Great Expectations data validator stack component.

        Returns:
            A Great Expectations data context managed by ZenML as configured
            through the active data validator stack component.

        Raises:
            TypeError: if a Great Expectations data validator is not part of the
                active stack.
        """
        return cls.get_active_data_validator().data_context

    @property
    def local_path(self) -> Optional[str]:
        """Return a local path where this component stores information.

        If an existing local GE data context is used, it is
        interpreted as a local path that needs to be accessible in
        all runtime environments.

        Returns:
            The local path where this component stores information.
        """
        return self.context_root_dir

    def get_store_config(self, class_name: str, prefix: str) -> Dict[str, Any]:
        """Generate a Great Expectations store configuration.

        Args:
            class_name: The store class name
            prefix: The path prefix for the ZenML store configuration

        Returns:
            A dictionary with the GE store configuration.
        """
        return {
            "class_name": class_name,
            "store_backend": {
                "module_name": ZenMLArtifactStoreBackend.__module__,
                "class_name": ZenMLArtifactStoreBackend.__name__,
                "prefix": f"{str(self.uuid)}/{prefix}",
            },
        }

    def get_data_docs_config(
        self, prefix: str, local: bool = False
    ) -> Dict[str, Any]:
        """Generate Great Expectations data docs configuration.

        Args:
            prefix: The path prefix for the ZenML data docs configuration
            local: Whether the data docs site is local or remote.

        Returns:
            A dictionary with the GE data docs site configuration.
        """
        if local:
            store_backend = {
                "class_name": "TupleFilesystemStoreBackend",
                "base_directory": f"{self.root_directory}/{prefix}",
            }
        else:
            store_backend = {
                "module_name": ZenMLArtifactStoreBackend.__module__,
                "class_name": ZenMLArtifactStoreBackend.__name__,
                "prefix": f"{str(self.uuid)}/{prefix}",
            }

        return {
            "class_name": "SiteBuilder",
            "store_backend": store_backend,
            "site_index_builder": {
                "class_name": "DefaultSiteIndexBuilder",
            },
        }

    @property
    def data_context(self) -> BaseDataContext:
        """Returns the Great Expectations data context configured for this component.

        Returns:
            The Great Expectations data context configured for this component.
        """
        if not self._context:
            expectations_store_name = "zenml_expectations_store"
            validations_store_name = "zenml_validations_store"
            checkpoint_store_name = "zenml_checkpoint_store"
            profiler_store_name = "zenml_profiler_store"
            evaluation_parameter_store_name = "evaluation_parameter_store"

            zenml_context_config = dict(
                stores={
                    expectations_store_name: self.get_store_config(
                        "ExpectationsStore", "expectations"
                    ),
                    validations_store_name: self.get_store_config(
                        "ValidationsStore", "validations"
                    ),
                    checkpoint_store_name: self.get_store_config(
                        "CheckpointStore", "checkpoints"
                    ),
                    profiler_store_name: self.get_store_config(
                        "ProfilerStore", "profilers"
                    ),
                    evaluation_parameter_store_name: {
                        "class_name": "EvaluationParameterStore"
                    },
                },
                expectations_store_name=expectations_store_name,
                validations_store_name=validations_store_name,
                checkpoint_store_name=checkpoint_store_name,
                profiler_store_name=profiler_store_name,
                evaluation_parameter_store_name=evaluation_parameter_store_name,
                data_docs_sites={
                    "zenml_artifact_store": self.get_data_docs_config(
                        "data_docs"
                    )
                },
            )

            configure_zenml_stores = self.configure_zenml_stores
            if self.context_root_dir:
                # initialize the local data context, if a local path was
                # configured
                self._context = DataContext(self.context_root_dir)
            else:
                # create an in-memory data context configuration that is not
                # backed by a local YAML file (see https://docs.greatexpectations.io/docs/guides/setup/configuring_data_contexts/how_to_instantiate_a_data_context_without_a_yml_file/).
                if self.context_config:
                    context_config = DataContextConfig(**self.context_config)
                else:
                    context_config = DataContextConfig(**zenml_context_config)
                    # skip adding the stores after initialization, as they are
                    # already baked in the initial configuration
                    configure_zenml_stores = False
                self._context = BaseDataContext(project_config=context_config)

            if configure_zenml_stores:
                self._context.config.expectations_store_name = (
                    expectations_store_name
                )
                self._context.config.validations_store_name = (
                    validations_store_name
                )
                self._context.config.checkpoint_store_name = (
                    checkpoint_store_name
                )
                self._context.config.profiler_store_name = profiler_store_name
                self._context.config.evaluation_parameter_store_name = (
                    evaluation_parameter_store_name
                )
                for store_name, store_config in zenml_context_config[  # type: ignore[attr-defined]
                    "stores"
                ].items():
                    self._context.add_store(
                        store_name=store_name,
                        store_config=store_config,
                    )
                for site_name, site_config in zenml_context_config[  # type: ignore[attr-defined]
                    "data_docs_sites"
                ].items():
                    self._context.config.data_docs_sites[
                        site_name
                    ] = site_config

            if self.configure_local_docs:

                repo = Repository(skip_repository_check=True)  # type: ignore[call-arg]
                artifact_store = repo.active_stack.artifact_store
                if artifact_store.FLAVOR != "local":
                    self._context.config.data_docs_sites[
                        "zenml_local"
                    ] = self.get_data_docs_config("data_docs", local=True)

        return self._context

    @property
    def root_directory(self) -> str:
        """Returns path to the root directory for all local files concerning this data validator.

        Returns:
            Path to the root directory.
        """
        path = os.path.join(
            io_utils.get_global_config_directory(),
            self.FLAVOR,
            str(self.uuid),
        )

        if not os.path.exists(path):
            fileio.makedirs(path)

        return path

    def data_profiling(
        self,
        dataset: pd.DataFrame,
        expectation_suite_name: str,
        data_asset_name: Optional[str] = None,
        profiler_kwargs: Optional[Dict[str, Any]] = None,
        overwrite_existing_suite: bool = True,
    ) -> ExpectationSuite:
        """Infer a Great Expectation Expectation Suite from a given dataset.

        This Great Expectations specific data profiling method implementation
        builds an Expectation Suite automatically by running a
        UserConfigurableProfiler on an input dataset [as covered in the official
        GE documentation](https://docs.greatexpectations.io/docs/guides/expectations/how_to_create_and_edit_expectations_with_a_profiler).

        Args:
            dataset: The dataset from which the expectation suite will be
                inferred.
            expectation_suite_name: The name of the expectation suite to create
                or update.
            data_asset_name: The name of the data asset to use to identify the
                dataset in the Great Expectations docs.
            profiler_kwargs: A dictionary of custom keyword arguments to pass to
                the profiler.
            overwrite_existing_suite: Whether to overwrite an existing
                expectation suite, if one exists with that name.

        Returns:
            The inferred Expectation Suite.
        """
        context = self.data_context

        suite_exists = False
        if context.expectations_store.has_key(  # noqa
            ExpectationSuiteIdentifier(expectation_suite_name)
        ):
            suite_exists = True
            suite = context.get_expectation_suite(expectation_suite_name)
            if not overwrite_existing_suite:
                logger.info(
                    f"Expectation Suite `{expectation_suite_name}` "
                    f"already exists and `overwrite_existing_suite` is not set "
                    f"in the step configuration. Skipping re-running the "
                    f"profiler."
                )
                return suite

        batch_request = create_batch_request(context, dataset, data_asset_name)

        try:
            if suite_exists:
                validator = context.get_validator(
                    batch_request=batch_request,
                    expectation_suite_name=expectation_suite_name,
                )
            else:
                validator = context.get_validator(
                    batch_request=batch_request,
                    create_expectation_suite_with_name=expectation_suite_name,
                )

            profiler = UserConfigurableProfiler(
                profile_dataset=validator, **profiler_kwargs
            )

            suite = profiler.build_suite()
            context.save_expectation_suite(
                expectation_suite=suite,
                expectation_suite_name=expectation_suite_name,
            )

            context.build_data_docs()
        finally:
            context.delete_datasource(batch_request.datasource_name)

        return suite

    def data_profile_validation(
        self,
        dataset: pd.DataFrame,
        profile: str,
        data_asset_name: Optional[str] = None,
        action_list: Optional[List[Dict[str, Any]]] = None,
    ) -> CheckpointResult:
        """Great Expectations data validation.

        This Great Expectations specific data profile validation method
        implementation validates an input dataset against an Expectation Suite
        (the GE definition of a profile) [as covered in the official GE
        documentation](https://docs.greatexpectations.io/docs/guides/validation/how_to_validate_data_by_running_a_checkpoint).

        Args:
            dataset: The dataset to validate.
            profile: The name of the expectation suite to use to validate the
                dataset.
            data_asset_name: The name of the data asset to use to identify the
                dataset in the Great Expectations docs.
            action_list: A list of additional Great Expectations actions to run after
                the validation check.
        Returns:
            The Great Expectations validation (checkpoint) result.
        """
        try:
            # get pipeline name, step name and run id
            step_env = cast(
                StepEnvironment, Environment()[STEP_ENVIRONMENT_NAME]
            )
            run_id = step_env.pipeline_run_id
            step_name = step_env.step_name
        except KeyError:
            # if not running inside a pipeline step, use random values
            run_id = f"pipeline_{random_str(5)}"
            step_name = f"step_{random_str(5)}"

        context = self.data_context

        checkpoint_name = f"{run_id}_{step_name}"

        batch_request = create_batch_request(context, dataset, data_asset_name)

        action_list = action_list or [
            {
                "name": "store_validation_result",
                "action": {"class_name": "StoreValidationResultAction"},
            },
            {
                "name": "store_evaluation_params",
                "action": {"class_name": "StoreEvaluationParametersAction"},
            },
            {
                "name": "update_data_docs",
                "action": {"class_name": "UpdateDataDocsAction"},
            },
        ]

        checkpoint_config = {
            "name": checkpoint_name,
            "run_name_template": f"{run_id}",
            "config_version": 1,
            "class_name": "Checkpoint",
            "expectation_suite_name": profile,
            "action_list": action_list,
        }
        context.add_checkpoint(**checkpoint_config)

        try:
            results = context.run_checkpoint(
                checkpoint_name=checkpoint_name,
                validations=[{"batch_request": batch_request}],
            )
        finally:
            context.delete_datasource(batch_request.datasource_name)
            context.delete_checkpoint(checkpoint_name)

        return results
