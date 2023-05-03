#  Copyright (c) ZenML GmbH 2023. All Rights Reserved.
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
"""Docker Service Connector.

The Docker Service Connector is responsible for authenticating with a Docker
(or compatible) registry.
"""
import re
import subprocess
from typing import Any, List, Optional, Tuple

from docker.client import DockerClient
from docker.errors import DockerException
from pydantic import SecretStr

from zenml.exceptions import AuthorizationException
from zenml.logger import get_logger
from zenml.models import (
    AuthenticationMethodModel,
    ResourceTypeModel,
    ServiceConnectorTypeModel,
)
from zenml.service_connectors.service_connector import (
    AuthenticationConfig,
    ServiceConnector,
)
from zenml.utils.enum_utils import StrEnum

logger = get_logger(__name__)


class DockerCredentials(AuthenticationConfig):
    """Docker client authentication credentials."""

    username: SecretStr
    password: SecretStr


DOCKER_CONNECTOR_TYPE = "docker"
DOCKER_RESOURCE_TYPE = "docker-registry"


class DockerAuthenticationMethods(StrEnum):
    """Docker Authentication methods."""

    PASSWORD = "password"


DOCKER_SERVICE_CONNECTOR_TYPE_SPEC = ServiceConnectorTypeModel(
    name="Docker Service Connector",
    connector_type=DOCKER_CONNECTOR_TYPE,
    description="""
The ZenML Docker Service Connector allows authenticating with a Docker or OCI
container registry and managing Docker clients for the registry. 

The connector provides pre-authenticated python-docker clients.
""",
    logo_url="https://public-flavor-logos.s3.eu-central-1.amazonaws.com/container_registry/docker.png",
    auth_methods=[
        AuthenticationMethodModel(
            name="Docker username and password/token",
            auth_method=DockerAuthenticationMethods.PASSWORD,
            description="""
Use a username and password or access token to authenticate with a container
registry server.
""",
            config_class=DockerCredentials,
        ),
    ],
    resource_types=[
        ResourceTypeModel(
            name="Docker/OCI container registry",
            resource_type=DOCKER_RESOURCE_TYPE,
            description="""
Allows users to access a Docker or OCI container registry as a resource.
When used by connector consumers, they are provided a pre-authenticated
python-docker client instance.

The resource ID must identify a Docker/OCI repository using one of the following
formats:
            
- repository URI: http[s]://host[:port]/<repository-name>
- DockerHub repository name: <repository-name>
""",
            auth_methods=DockerAuthenticationMethods.values(),
            # Request a Docker repository to be configured in the
            # connector or provided by the consumer.
            supports_instances=True,
            # Does not support listing all Docker repositories that can be
            # accessed with a given set of credentials. A Docker repository
            # must be manually configured in the connector or provided by the
            # consumer (i.e. cannot be selected from a list of available
            # repositories).
            supports_discovery=False,
            logo_url="https://public-flavor-logos.s3.eu-central-1.amazonaws.com/container_registry/docker.png",
        ),
    ],
)


class DockerServiceConnector(ServiceConnector):
    """Docker service connector."""

    config: DockerCredentials

    @classmethod
    def _get_connector_type(cls) -> ServiceConnectorTypeModel:
        """Get the service connector specification.

        Returns:
            The service connector specification.
        """
        return DOCKER_SERVICE_CONNECTOR_TYPE_SPEC

    @classmethod
    def _parse_resource_id(
        cls,
        resource_id: str,
    ) -> Tuple[str, Optional[str]]:
        """Validate and convert a Docker resource ID into a Docker repository name and registry.

        Args:
            resource_id: The resource ID to convert.

        Returns:
            The Docker repository name and registry. The registry is None if
            the resource ID is a DockerHub repository name.

        Raises:
            ValueError: If the provided resource ID is not a valid Docker
                repository.
        """
        repository_name: Optional[str] = None
        registry: Optional[str] = None
        if re.match(
            r"^(https?://)?[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*(:[0-9]+)?/.+$",
            resource_id,
        ):
            # The resource ID is a repository URL
            if resource_id.startswith("https://"):
                repository_name = resource_id.split("/", 2)[2]
            else:
                repository_name = resource_id
            registry = repository_name.split("/", 1)[0]
        elif re.match(r"^[a-zA-Z0-9-]+$", resource_id):
            # The resource ID is a DockerHub repository name
            repository_name = resource_id
        else:
            raise ValueError(
                f"Invalid resource ID for a Docker registry: {resource_id}. "
                f"Please provide a valid repository name or URL in the "
                f"following format:\n"
                f"repository name/URL: [https://]host[:port]/<repository-name>\n"
                f"DockerHub repository name: <repository-name>\n"
            )
        return repository_name, registry

    def _canonical_resource_id(
        self, resource_type: str, resource_id: str
    ) -> str:
        """Convert a resource ID to its canonical form.

        Args:
            resource_type: The resource type to canonicalize.
            resource_id: The resource ID to canonicalize.

        Returns:
            The canonical resource ID.
        """
        return self._parse_resource_id(resource_id)[0]

    def _authorize_client(
        self,
        docker_client: DockerClient,
        resource_id: Optional[str] = None,
    ) -> None:
        """Authorize a Docker client to have access to the configured Docker registry.

        Args:
            docker_client: The Docker client to authenticate.
            resource_id: The resource ID to authorize the client for. If None,
                the client is authorized for the configured resource ID.
        """
        cfg = self.config
        resource_id = resource_id or self.resource_id
        assert resource_id is not None
        _, registry = self._parse_resource_id(resource_id)

        docker_client.login(
            username=cfg.username.get_secret_value(),
            password=cfg.password.get_secret_value(),
            registry=registry,
            reauth=True,
        )

    def _connect_to_resource(
        self,
        **kwargs: Any,
    ) -> Any:
        """Authenticate and connect to a Docker/OCI registry.

        Initialize, authenticate and return a python-docker client.

        Args:
            kwargs: Additional implementation specific keyword arguments to pass
                to the session or client constructor.

        Returns:
            An authenticated python-docker client object.

        Raises:
            AuthorizationException: If authentication failed.
        """
        docker_client = DockerClient.from_env()
        self._authorize_client(docker_client)

        return docker_client

    def _configure_local_client(
        self,
        **kwargs: Any,
    ) -> None:
        """Configure the local Docker client to authenticate to a Docker/OCI registry.

        Args:
            kwargs: Additional implementation specific keyword arguments to use
                to configure the client.

        Raises:
            AuthorizationException: If authentication failed.
            NotImplementedError: If the connector instance does not support
                local configuration for the indicated resource type or client
                type.
        """
        # Call the docker CLI to authenticate to the Docker registry
        cfg = self.config

        assert self.resource_id is not None
        _, registry = self._parse_resource_id(self.resource_id)

        docker_login_cmd = [
            "docker",
            "login",
            "-u",
            cfg.username.get_secret_value(),
            "--password-stdin",
        ]
        if registry:
            docker_login_cmd.append(registry)

        try:
            subprocess.run(
                docker_login_cmd,
                check=True,
                input=cfg.password.get_secret_value().encode(),
            )
        except subprocess.CalledProcessError as e:
            raise AuthorizationException(
                f"Failed to authenticate to Docker registry "
                f"'{self.resource_id}': {e}"
            ) from e

    @classmethod
    def _auto_configure(
        cls,
        auth_method: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs: Any,
    ) -> "DockerServiceConnector":
        """Auto-configure the connector.

        Not supported by the Docker connector.

        Args:
            auth_method: The particular authentication method to use. If not
                specified, the connector implementation must decide which
                authentication method to use or raise an exception.
            resource_type: The type of resource to configure.
            resource_id: The ID of the resource to configure. The
                implementation may choose to either require or ignore this
                parameter if it does not support or detect an resource type that
                supports multiple instances.
            kwargs: Additional implementation specific keyword arguments to use.

        Returns:
            A connector instance configured with authentication credentials
            automatically extracted from the environment.

        Raises:
            NotImplementedError: If the connector auto-configuration fails or
                is not supported.
        """
        raise NotImplementedError(
            "Auto-configuration is not supported by the Docker connector."
        )

    def _verify(
        self,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> List[str]:
        """Verify that the connector can authenticate and access resources.

        Args:
            resource_type: The type of resource to verify. Must be set to the
                Docker resource type.
            resource_id: The Docker registry name or URL to connect to. If not
                provided, this method will verify that it can connect to any
                Docker registry.
        """
        # The docker server isn't available on the ZenML server, so we can't
        # verify the credentials there.
        try:
            docker_client = DockerClient.from_env()
        except DockerException as e:
            logger.warning(
                f"Failed to connect to Docker daemon: {e}"
                f"\nSkipping Docker connector verification."
            )
        else:
            if resource_id:
                self._authorize_client(docker_client, resource_id)
                docker_client.close()

        return [resource_id] if resource_id else []
