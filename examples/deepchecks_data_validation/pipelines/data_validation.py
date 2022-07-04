#  Copyright (c) ZenML GmbH 2022. All Rights Reserved.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.

from zenml.integrations.constants import DEEPCHECKS, SKLEARN
from zenml.pipelines import pipeline


@pipeline(enable_cache=False, required_integrations=[DEEPCHECKS, SKLEARN])
def data_validation_pipeline(
    data_loader,
    trainer,
    data_validator,
    post_validation,
):
    """Links all the steps together in a pipeline"""
    df_train, df_test = data_loader()
    model = trainer(df_train)
    validation_result = data_validator(
        reference_dataset=df_train,
        comparison_dataset=df_test,
        model=model,
    )
    post_validation(validation_result)
