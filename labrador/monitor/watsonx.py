import json
import logging
import uuid
from typing import Any, List, Literal

logging.getLogger("ibm_watsonx_ai.client").setLevel(logging.ERROR)
logging.getLogger("ibm_watsonx_ai.wml_resource").setLevel(logging.ERROR)

REGIONS_URL = {
    "us-south": {"wml": "https://us-south.ml.cloud.ibm.com", 
                 "wos": "https://api.aiopenscale.cloud.ibm.com", 
                 "factsheet": None},
    "eu-de": {"wml": "https://eu-de.ml.cloud.ibm.com", 
              "wos": "https://eu-de.api.aiopenscale.cloud.ibm.com", 
              "factsheet": "frankfurt"},
    "au-syd": {"wml": "https://au-syd.ml.cloud.ibm.com", 
               "wos": "https://au-syd.api.aiopenscale.cloud.ibm.com", 
               "factsheet": "sydney"},
}

def _filter_dict(original_dict: dict, optional_keys: List, required_keys: List = []):
    """Filters a dictionary to keep only the specified keys and check required.
    
    Args:
        original_dict (dict): The original dictionary
        optional_keys (list): A list of keys to keep
        required_keys (list, optional): A list of keys that must exist in the dictionary
    """
    # Ensure all required keys are in the source dictionary
    missing_keys = [key for key in required_keys if key not in original_dict]
    if missing_keys:
        raise KeyError(f"Missing required parameter: {missing_keys}")
    
    all_keys_to_keep = set(required_keys + optional_keys)
    
    # Create a new dictionary with only the key-value pairs where the key is in 'keys' and value is not None
    return {key: original_dict[key] for key in all_keys_to_keep if key in original_dict and original_dict[key] is not None}     

def _convert_payload_format(records: List[dict], feature_fields: List[str]) -> List[dict]:
        
        payload_data = []
        response_fields = ["generated_text", "input_token_count", "generated_token_count"]
            
        for record in records: 
            request = { "parameters": { "template_variables": {}}}
            results = {}
                
            request["parameters"]["template_variables"] = {field: str(record.get(field, "")) for field in feature_fields}
            
            results = {field: record.get(field) for field in response_fields if record.get(field)}
                
            pl_record = {"request": request, "response": {"results": [results]}}
            payload_data.append(pl_record)
           
        return payload_data


class CloudPakforDataCredentials:
    """Encapsulate passed credentials for CloudPakforData.

    Args:
        url (str): Host URL of Cloud Pak for Data environment.
        api_key (str, optional): Environment api_key if IAM enabled.
        username (str, optional): Environment username.
        password (str, optional): Environment password.
        bedrock_url (str, optional): Bedrock URL. This url is required only when iam-integration is enabled on CP4D 4.0.x cluster.
        instance_id (str, optional): Instance ID.
        version (str, optional): CPD Version.
        disable_ssl_verification (bool, optional): Indicates whether verification of the server's SSL certificate. Defaults to ``True``.
    """
    
    def __init__(self,
                 url: str,
                 api_key: str = None,
                 username: str = None,
                 password: str = None,
                 bedrock_url: str = None,
                 instance_id: Literal["icp","openshift"] = None,
                 version: str = None,
                 disable_ssl_verification: bool = True) -> None:
        
        self.url = url
        self.api_key = api_key
        self.username = username
        self.api_key = api_key
        self.password = password
        self.bedrock_url = bedrock_url
        self.instance_id = instance_id
        self.api_key = api_key
        self.version = version
        self.disable_ssl_verification = disable_ssl_verification
        
    def to_dict(self) -> dict[str, Any]:
        data = dict([(k, v) for k, v in self.__dict__.items()])
        
        if "instance_id" in data and self.instance_id.lower() not in ["icp","openshift"]:
            data.pop("instance_id")
        
        return data


class WatsonxExternalPromptMonitoring:
    """Provides functionality to interact with IBM watsonx.governance for monitoring external LLM's.
    
    Note:
            One of these parameters is required to create prompt monitor: ``project_id`` or ``space_id``. Not both.

    Args:
        api_key (str): IBM watsonx.governance API key.
        space_id (str, optional): watsonx.governance space_id.
        project_id (str, optional): watsonx.governance project_id.
        region (str, optional): Region where the watsonx.governance is hosted when using IBM Cloud. Defaults to ``us-south``
        cpd_creds (CloudPakforDataCredentials, optional): Cloud Pak for Data environment details.

    **Example**

    .. code-block:: python

        from labrador.monitor import WatsonxExternalPromptMonitoring

        # watsonx.governance (IBM Cloud)
        detached_watsonx_monitor = WatsonxExternalPromptMonitoring(api_key="your_api_key", 
                                                               space_id="your_space_id")
                                                               
        # watsonx.governance (cp4d)
        from labrador.monitor import CloudPakforDataCredentials
        
        cpd_creds = CloudPakforDataCredentials(url="your_cpd_url", 
                                  username="your_username", password="your_password",
                                 version="5.0", instance_id="openshift")
        
        detached_watsonx_monitor = WatsonxExternalPromptMonitoring(space_id="your_space_id"
                                                                cpd_creds=cpd_creds)
    """
    
    def __init__(self,
                 api_key: str = None,
                 space_id: str = None,
                 project_id: str = None,
                 region: Literal["us-south", "eu-de", "au-syd"] = "us-south",
                 cpd_creds: CloudPakforDataCredentials | dict = None,
                 ) -> None:
        
        try:
            import ibm_aigov_facts_client  # noqa: F401
            import ibm_cloud_sdk_core.authenticators  # noqa: F401
            import ibm_watson_openscale  # noqa: F401
            import ibm_watsonx_ai  # noqa: F401

        except ImportError:
            raise ImportError("""ibm-aigov-facts-client, ibm-watson-openscale or ibm-watsonx-ai module not found, 
                                please install it with `pip install ibm-aigov-facts-client ibm-watson-openscale ibm-watsonx-ai`""")
            
        if (not (project_id or space_id)) or (project_id and space_id):
            raise ValueError("`project_id` and `space_id` parameter cannot be set at the same time.")

        self.space_id = space_id
        self.project_id = project_id
        self.region = region
        self._api_key = api_key
        self._wos_client = None
        
        self._container_id = space_id if space_id else project_id
        self._container_type = "space" if space_id else "project"
        self._deployment_stage = "production" if space_id else "development"
        
        if cpd_creds: 
            self._wos_cpd_creds = _filter_dict(cpd_creds.to_dict(), ["username", "password", "api_key", 
                                                                   "disable_ssl_verification"], ["url"])
            self._fact_cpd_creds = _filter_dict(cpd_creds.to_dict(), ["username", "password", "api_key", 
                                                                        "bedrock_url"],["url"])
            self._fact_cpd_creds["service_url"] = self._fact_cpd_creds.pop("url")
            self._wml_cpd_creds = _filter_dict(cpd_creds.to_dict(), ["username", "password", "api_key", "instance_id", 
                                                                   "version", "bedrock_url"], ["url"])

                    
    def _create_detached_prompt(self, detached_details: dict, 
                                prompt_template_details: dict, 
                                detached_asset_details: dict) -> str:
        from ibm_aigov_facts_client import (  # type: ignore
            AIGovFactsClient,
            CloudPakforDataConfig,
            DetachedPromptTemplate,
            PromptTemplate,
        )
            
        try:
            if self._fact_cpd_creds: 
                cpd_creds = CloudPakforDataConfig(**self._fact_cpd_creds)
                
                aigov_client = AIGovFactsClient(
                    container_id=self._container_id,
                    container_type=self._container_type,
                    cloud_pak_for_data_configs=cpd_creds,
                    disable_tracing=True)
                
            else:
                aigov_client = AIGovFactsClient(
                    api_key=self._api_key,
                    container_id=self._container_id,
                    container_type=self._container_type,
                    disable_tracing=True,
                    region=REGIONS_URL[self.region]["factsheet"])
                
        except Exception as e:
            logging.error(f"Error connecting to IBM watsonx.governance (factsheets): {e}")
            raise

        created_detached_pta = aigov_client.assets.create_detached_prompt(
            **detached_asset_details,
            prompt_details=PromptTemplate(**prompt_template_details),
            detached_information=DetachedPromptTemplate(**detached_details))
            
        return created_detached_pta.to_dict()["asset_id"]
            
            
    def _create_deployment_pta(self, asset_id: str,
                               name: str,
                               model_id: str) -> str:
        from ibm_watsonx_ai import APIClient, Credentials  # type: ignore
            
        try:
            if self._wml_cpd_creds:
                creds = Credentials(**self._wml_cpd_creds)
                
                wml_client = APIClient(creds)
                wml_client.set.default_space(self.space_id)
                
            else:
                creds = Credentials({"url": REGIONS_URL[self.region]["wml"], "apikey": self._api_key})
                wml_client = APIClient(creds)
                wml_client.set.default_space(self.space_id)
                
        except Exception as e:
            logging.error(f"Error connecting to IBM watsonx.ai Runtime: {e}")
            raise
            
        meta_props = {
            wml_client.deployments.ConfigurationMetaNames.PROMPT_TEMPLATE: { "id" : asset_id },
            wml_client.deployments.ConfigurationMetaNames.DETACHED: {},
            wml_client.deployments.ConfigurationMetaNames.NAME: name + " " + "deployment",
            wml_client.deployments.ConfigurationMetaNames.BASE_MODEL_ID: model_id
        }
            
        created_deployment = wml_client.deployments.create(asset_id, meta_props)
            
        return wml_client.deployments.get_uid(created_deployment)
        
            
    def create_prompt_monitor(self,
                              name: str,
                              model_id: str,
                              task_id: Literal["retrieval_augmented_generation", "summarization"],
                              detached_model_provider: str,
                              description: str = "",
                              model_parameters: dict = None,
                              detached_model_name: str = None,
                              detached_model_url: str = None,
                              detached_prompt_url: str = None,
                              detached_prompt_additional_info: dict = None,
                              prompt_variables: List[str] = None,
                              prompt_template_version: str = None,
                              prompt_instruction: str = None,
                              input_text: str = None,
                              input_prefix: str = None,
                              output_prefix: str = None,
                              context_fields: List[str] = None,
                              question_field: str = None) -> dict:
        """Create a Detached/External Prompt Template Asset and setup monitors for a given prompt template asset.

        Args:
            name (str): The name of the External Prompt Template Asset..
            model_id (str): Id of the model associated with the prompt.
            task_id (str): The task identifier. Currently supports "retrieval_augmented_generation" and "summarization" tasks.
            detached_model_provider (str): The external model provider.
            description (str, optional): Description of the External Prompt Template Asset.
            model_parameters (dict, optional): Model parameters and their respective values.
            detached_model_name (str, optional): The name of the external model.
            detached_model_url (str, optional): URL of the external model.
            detached_prompt_url (str, optional): URL of the external prompt.
            detached_prompt_additional_info (dict, optional): Additional information related to the external prompt.
            prompt_variables (List[str], optional): Values for prompt variables.
            prompt_template_version (str, optional): Semantic version of the External Prompt Template Asset.
            prompt_instruction (str, optional): Instruction for using the prompt.
            input_text (str, optional): The input text for the prompt.
            input_prefix (str, optional): A prefix to add to the input.
            output_prefix (str, optional): A prefix to add to the output.
            context_fields (List[str], optional): A list of fields that will provide context to the prompt. Applicable only for ``retrieval_augmented_generation`` problem type.
            question_field (str, optional): The field containing the question to be answered. Applicable only for ``retrieval_augmented_generation`` problem type.

        **Example**

        .. code-block:: python

            detached_watsonx_monitor.create_prompt_monitor(name="Detached prompt (model AWS Anthropic)",
                                                    model_id="anthropic.claude-v2",
                                                    task_id="retrieval_augmented_generation",
                                                    detached_model_provider="AWS Bedrock",
                                                    detached_model_name="Anthropic Claude 2.0",
                                                    detached_model_url="https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-claude.html",
                                                    prompt_variables=["context1", "context2", "input_query"],
                                                    input_text="Prompt text to be given",
                                                    context_fields=["context1", "context2"],
                                                    question_field="input_query")
            
        """
        prompt_metadata = locals()
        # remove unused vars from dict
        prompt_metadata.pop("self", None)
        prompt_metadata.pop("context_fields", None)
        prompt_metadata.pop("question_field", None)
        
        # update name of keys to aigov_facts api
        prompt_metadata["model_version"] = prompt_metadata.pop("prompt_template_version", None)
        prompt_metadata["input"] = prompt_metadata.pop("input_text", None)
        prompt_metadata["model_provider"] = prompt_metadata.pop("detached_model_provider", None)
        prompt_metadata["model_name"] = prompt_metadata.pop("detached_model_name", None)
        prompt_metadata["model_url"] = prompt_metadata.pop("detached_model_url", None)
        prompt_metadata["prompt_url"] = prompt_metadata.pop("detached_prompt_url", None)
        prompt_metadata["prompt_additional_info"] = prompt_metadata.pop("detached_prompt_additional_info", None)
        
        # update list of vars to dict
        prompt_metadata["prompt_variables"] = { prompt_var: "" for prompt_var in prompt_metadata["prompt_variables"] }
        
        from ibm_watson_openscale import APIClient as WosAPIClient  # type: ignore
        
        if not self._wos_client:   
            try:
                if self._wos_cpd_creds:
                    from ibm_cloud_sdk_core.authenticators import (
                        CloudPakForDataAuthenticator,  # type: ignore
                    )
                    
                    authenticator = CloudPakForDataAuthenticator(**self._wos_cpd_creds)
                    self._wos_client = WosAPIClient(authenticator=authenticator, 
                                                    service_url=self._wos_cpd_creds["url"])
                    
                else:
                    from ibm_cloud_sdk_core.authenticators import (
                        IAMAuthenticator,  # type: ignore
                    )
                    
                    authenticator = IAMAuthenticator(apikey=self._api_key)
                    self._wos_client = WosAPIClient(authenticator=authenticator, service_url=REGIONS_URL[self.region]["wos"])
                    
            except Exception as e:
                logging.error(f"Error connecting to IBM watsonx.governance (openscale): {e}")
                raise
            
        detached_details = _filter_dict(prompt_metadata, 
                                        ["model_name", "model_url", "prompt_url", "prompt_additional_info"],
                                        ["model_id", "model_provider"])
        detached_details["prompt_id"] = "detached_prompt_" + str(uuid.uuid4())
        
        prompt_details = _filter_dict(prompt_metadata, 
                                      ["model_version", "prompt_variables", "prompt_instruction",
                                       "input_prefix", "output_prefix", "input", "model_parameters"])
        
        detached_asset_details = _filter_dict(prompt_metadata, ["description"],
                                              ["name", "model_id", "task_id"])
        
        detached_pta_id = self._create_detached_prompt(detached_details, prompt_details, detached_asset_details)
        deployment_id = None
        if self._container_type == "space":
            deployment_id =  self._create_deployment_pta(detached_pta_id, name, model_id)
            
        monitors = {
            "generative_ai_quality": {
                "parameters": {
                    "min_sample_size": 10,
                    "metrics_configuration":{}
                    }
                }}
        
        max_attempt_execute_prompt_setup = 0
        while max_attempt_execute_prompt_setup < 2:
            try:
                generative_ai_monitor_details = self._wos_client.wos.execute_prompt_setup(
                    prompt_template_asset_id = detached_pta_id, 
                    space_id = self.space_id,
                    project_id=self.project_id,
                    deployment_id = deployment_id,
                    label_column = "reference_output",
                    context_fields=context_fields,     
                    question_field = question_field,   
                    operational_space_id = self._deployment_stage, 
                    problem_type = task_id,
                    input_data_type = "unstructured_text", 
                    supporting_monitors = monitors, 
                    background_mode = False).result
                
                break
                
            except Exception as e:
                if e.code == 403 and "The user entitlement does not exist" in e.message \
                and max_attempt_execute_prompt_setup < 1:
                    max_attempt_execute_prompt_setup = max_attempt_execute_prompt_setup + 1
                    
                    data_marts = self._wos_client.data_marts.list().result
                    if (data_marts.data_marts is None) or (not data_marts.data_marts):
                        raise ValueError("Error retrieving IBM watsonx.governance (openscale) data mart. \
                                         Make sure the data mart are configured.")
                        
                    data_mart_id = data_marts.data_marts[0].metadata.id
                    
                    self._wos_client.wos.add_instance_mapping(
                        service_instance_id=data_mart_id,
                        space_id=self.space_id,
                        project_id=self.project_id)
                else:
                    max_attempt_execute_prompt_setup = 2
                    raise e

        generative_ai_monitor_details = generative_ai_monitor_details._to_dict()   
               
        return {"detached_prompt_template_asset_id": detached_pta_id,
                "deployment_id": deployment_id,
                "subscription_id": generative_ai_monitor_details["subscription_id"]} 
        
                    
    def payload_logging(self, payload_records: List[dict], subscription_id: str) -> None:
        """Store records to payload logging.

        Args:
            payload_records (List[dict]): 
            subscription_id (str): 

        **Example**

        .. code-block:: python

            detached_watsonx_monitor.payload_logging(payload_records=[{"context1": "value_context1",
                                                    "context2": "value_context1",
                                                    "input_query": "What's Labrador?",
                                                    "input_token_count": 25,
                                                    "generated_token_count": 150}], 
                                            subscription_id="5d62977c-a53d-4b6d-bda1-7b79b3b9d1a0")
        """
        from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
        from ibm_watson_openscale import APIClient as WosAPIClient
        from ibm_watson_openscale.supporting_classes.enums import (
            DataSetTypes,
            TargetTypes,
        )
        
        if not self._wos_client:
            try:
                if self._wos_cpd_creds:
                    from ibm_cloud_sdk_core.authenticators import (
                        CloudPakForDataAuthenticator,  # type: ignore
                    )
                    
                    authenticator = CloudPakForDataAuthenticator(**self._wos_cpd_creds)
                    self._wos_client = WosAPIClient(authenticator=authenticator, 
                                                    service_url=self._wos_cpd_creds["url"])
                    
                else:
                    from ibm_cloud_sdk_core.authenticators import (
                        IAMAuthenticator,  # type: ignore
                    )
                    
                    authenticator = IAMAuthenticator(apikey=self._api_key)
                    self._wos_client = WosAPIClient(authenticator=authenticator, service_url=REGIONS_URL[self.region]["wos"])
                
            except Exception as e:
                logging.error(f"Error connecting to IBM watsonx.governance (openscale): {e}")
                raise
        
        subscription_details = self._wos_client.subscriptions.get(subscription_id).result
        subscription_details = json.loads(str(subscription_details))
            
        feature_fields = subscription_details["entity"]["asset_properties"]["feature_fields"]
            
        payload_data_set_id = self._wos_client.data_sets.list(type=DataSetTypes.PAYLOAD_LOGGING,
                                                              target_target_id=subscription_id, 
                                                              target_target_type=TargetTypes.SUBSCRIPTION).result.data_sets[0].metadata.id
            
        payload_data = _convert_payload_format(payload_records, feature_fields)
        self._wos_client.data_sets.store_records(data_set_id=payload_data_set_id, 
                                                 request_body=payload_data,
                                                 background_mode=False)
                   
     
class WatsonxPromptMonitoring:
    """Provides functionality to interact with IBM watsonx.governance for monitoring IBM watsonx.ai LLM's.
    
    Note:
            One of these parameters is required to create prompt monitor: ``project_id`` or ``space_id``. Not both.

    Args:
        api_key (str): IBM watsonx.governance API key.
        space_id (str, optional): watsonx.governance space_id.
        project_id (str, optional): watsonx.governance project_id.
        region (str, optional): Region where the watsonx.governance is hosted when using IBM Cloud. Defaults to ``us-south``
        cpd_creds (CloudPakforDataCredentials, optional): Cloud Pak for Data environment details.

    **Example**

    .. code-block:: python

        from labrador.monitor import WatsonxPromptMonitoring

        # watsonx.governance (IBM Cloud)
        watsonx_monitor = WatsonxExternalPromptMonitoring(api_key="your_api_key", 
                                                        space_id="your_space_id")
        
        # watsonx.governance (cp4d)
        from labrador.monitor import CloudPakforDataCredentials
        
        cpd_creds = CloudPakforDataCredentials(url="your_cpd_url", 
                                  username="your_username", password="your_password",
                                 version="5.0", instance_id="openshift")
        
        detached_watsonx_monitor = WatsonxExternalPromptMonitoring(space_id="your_space_id"
                                                                cpd_creds=cpd_creds)                                            
    """
    
    def __init__(self,
                 api_key: str =None,
                 space_id: str = None,
                 project_id: str = None,
                 region: Literal["us-south", "eu-de", "au-syd"] = "us-south",
                 cpd_creds: CloudPakforDataCredentials | dict = None,
                 ) -> None:
        try:
            import ibm_aigov_facts_client  # noqa: F401
            import ibm_cloud_sdk_core.authenticators  # noqa: F401
            import ibm_watson_openscale  # noqa: F401
            import ibm_watsonx_ai  # noqa: F401

        except ImportError:
            raise ImportError("""ibm-aigov-facts-client, ibm-watson-openscale or ibm-watsonx-ai module not found, 
                                please install it with `pip install ibm-aigov-facts-client ibm-watson-openscale ibm-watsonx-ai`""")
            
        if (not (project_id or space_id)) or (project_id and space_id):
            raise ValueError("`project_id` and `space_id` parameter cannot be set at the same time.")

        self.space_id = space_id
        self.project_id = project_id
        self.region = region
        self._api_key = api_key
        self._wos_client = None
        
        self._container_id = space_id if space_id else project_id
        self._container_type = "space" if space_id else "project"
        self._deployment_stage = "production" if space_id else "development"
        
        if cpd_creds: 
            self._wos_cpd_creds = _filter_dict(cpd_creds.to_dict(), ["username", "password", "api_key", 
                                                                   "disable_ssl_verification"], ["url"])
            self._fact_cpd_creds = _filter_dict(cpd_creds.to_dict(), ["username", "password", "api_key", 
                                                                        "bedrock_url"],["url"])
            self._fact_cpd_creds["service_url"] = self._fact_cpd_creds.pop("url")
            self._wml_cpd_creds = _filter_dict(cpd_creds.to_dict(), ["username", "password", "api_key", "instance_id", 
                                                                   "version", "bedrock_url"], ["url"])

                    
    def _create_prompt_template(self, prompt_template_details: dict, asset_details: dict) -> str:
        from ibm_aigov_facts_client import (
            AIGovFactsClient,
            CloudPakforDataConfig,
            PromptTemplate,
        )
            
        try:
            if self._fact_cpd_creds: 
                cpd_creds = CloudPakforDataConfig(**self._fact_cpd_creds)
                
                aigov_client = AIGovFactsClient(
                    container_id=self._container_id,
                    container_type=self._container_type,
                    cloud_pak_for_data_configs=cpd_creds,
                    disable_tracing=True)
                
            else:
                aigov_client = AIGovFactsClient(
                    api_key=self._api_key,
                    container_id=self._container_id,
                    container_type=self._container_type,
                    disable_tracing=True,
                    region=REGIONS_URL[self.region]["factsheet"])
                
        except Exception as e:
            logging.error(f"Error connecting to IBM watsonx.governance (factsheets): {e}")
            raise

        created_pta = aigov_client.assets.create_prompt(
            **asset_details, 
            input_mode="structured",
            prompt_details=PromptTemplate(**prompt_template_details))
            
        return created_pta.to_dict()["asset_id"]
            
            
    def _create_deployment_pta(self, asset_id: str,
                               name: str,
                               model_id: str) -> str:
        from ibm_watsonx_ai import APIClient, Credentials  # type: ignore
            
        try:
            if self._wml_cpd_creds:
                creds = Credentials(**self._wml_cpd_creds)
                
                wml_client = APIClient(creds)
                wml_client.set.default_space(self.space_id)

            else:
                creds = Credentials({"url": REGIONS_URL[self.region]["wml"], "apikey": self._api_key})
                
                wml_client = APIClient(creds)
                wml_client.set.default_space(self.space_id)
                
        except Exception as e:
            logging.error(f"Error connecting to IBM watsonx.ai Runtime: {e}")
            raise
            
        meta_props = {
            wml_client.deployments.ConfigurationMetaNames.PROMPT_TEMPLATE: { "id" : asset_id },
            wml_client.deployments.ConfigurationMetaNames.FOUNDATION_MODEL: {},
            wml_client.deployments.ConfigurationMetaNames.NAME: name + " " + "deployment",
            wml_client.deployments.ConfigurationMetaNames.BASE_MODEL_ID: model_id
        }
            
        created_deployment = wml_client.deployments.create(asset_id, meta_props)
            
        return wml_client.deployments.get_uid(created_deployment)
        
            
    def create_prompt_monitor(self,
                              name: str,
                              model_id: str,
                              task_id: Literal["retrieval_augmented_generation", "summarization"],
                              description: str = "",
                              model_parameters: dict = None,
                              prompt_variables: List[str] = None,
                              prompt_template_version: str = None,
                              prompt_instruction: str = None,
                              input_text: str = None,
                              input_prefix: str = None,
                              output_prefix: str = None,
                              context_fields: List[str] = None,
                              question_field: str = None,
                              ) -> dict:
        """Create an IBM Prompt Template Asset and setup monitors for a given prompt template asset.

        Args:
            name (str): The name of the Prompt Template Asset.
            model_id (str): Id of the model associated with the prompt.
            task_id (str): The task identifier. Currently supports "retrieval_augmented_generation" and "summarization" tasks.
            description (str, optional): Description of the Prompt Template Asset.
            model_parameters (dict, optional): Model parameters and their respective values.
            prompt_variables (List[str], optional): Values for prompt input variables.
            prompt_template_version (str, optional): Semantic version of the Prompt Template Asset.
            prompt_instruction (str, optional): Instruction for using the prompt.
            input_text (str, optional): The input text for the prompt.
            input_prefix (str, optional): A prefix to add to the input.
            output_prefix (str, optional): A prefix to add to the output.
            context_fields (List[str], optional): A list of fields that will provide context to the prompt. Applicable only for ``retrieval_augmented_generation`` problem type.
            question_field (str, optional): The field containing the question to be answered. Applicable only for ``retrieval_augmented_generation`` problem type.
            
        **Example**

        .. code-block:: python

            watsonx_monitor.create_prompt_monitor(name="IBM prompt template",
                                                    model_id="ibm/granite-3-2b-instruct",
                                                    task_id="retrieval_augmented_generation",
                                                    prompt_variables=["context1", "context2", "input_query"],
                                                    input_text="Prompt text to be given",
                                                    context_fields=["context1", "context2"],
                                                    question_field="input_query")
            
        """
        prompt_metadata = locals()
        # remove unused vars from dict
        prompt_metadata.pop("self", None)
        prompt_metadata.pop("context_fields", None)
        prompt_metadata.pop("question_field", None)
        
        # update name of keys to aigov_facts api
        prompt_metadata["model_version"] = prompt_metadata.pop("prompt_template_version", None)
        prompt_metadata["input"] = prompt_metadata.pop("input_text", None)
        
        # update list of vars to dict
        prompt_metadata["prompt_variables"] = { prompt_var: "" for prompt_var in prompt_metadata["prompt_variables"] }
        
        from ibm_cloud_sdk_core.authenticators import IAMAuthenticator  # type: ignore
        from ibm_watson_openscale import APIClient as WosAPIClient  # type: ignore
        
        if not self._wos_client:
            try:
                if self._wos_cpd_creds:
                    from ibm_cloud_sdk_core.authenticators import (
                        CloudPakForDataAuthenticator,  # type: ignore
                    )
                    
                    authenticator = CloudPakForDataAuthenticator(**self._wos_cpd_creds)
                    
                    self._wos_client = WosAPIClient(authenticator=authenticator, 
                                                    service_url=self._wos_cpd_creds["url"])
                    
                else:
                    from ibm_cloud_sdk_core.authenticators import (
                        IAMAuthenticator,  # type: ignore
                    )
                    
                    authenticator = IAMAuthenticator(apikey=self._api_key)
                    self._wos_client = WosAPIClient(authenticator=authenticator, service_url=REGIONS_URL[self.region]["wos"])
                    
            except Exception as e:
                logging.error(f"Error connecting to IBM watsonx.governance (openscale): {e}")
                raise
        
        prompt_details = _filter_dict(prompt_metadata, 
                                      ["model_version", "prompt_variables", "prompt_instruction",
                                       "input_prefix", "output_prefix", "input", "model_parameters"])
        
        asset_details = _filter_dict(prompt_metadata, ["description"],
                                     ["name", "model_id", "task_id"])
        
        pta_id = self._create_prompt_template(prompt_details, asset_details)
        deployment_id = None
        if self._container_type == "space":
            deployment_id =  self._create_deployment_pta(pta_id, name, model_id)
        
        monitors = {
            "generative_ai_quality": {
                "parameters": {
                    "min_sample_size": 10,
                    "metrics_configuration":{}
                    }
                }}
            
        max_attempt_execute_prompt_setup = 0
        while max_attempt_execute_prompt_setup < 2:
            try:
                generative_ai_monitor_details = self._wos_client.wos.execute_prompt_setup(
                    prompt_template_asset_id = pta_id, 
                    space_id = self.space_id,
                    project_id=self.project_id,
                    deployment_id = deployment_id,
                    label_column = "reference_output",
                    context_fields=context_fields,     
                    question_field = question_field,   
                    operational_space_id = "production", 
                    problem_type = task_id,
                    input_data_type = "unstructured_text", 
                    supporting_monitors = monitors, 
                    background_mode = False).result
                
                break
                
            except Exception as e:
                if e.code == 403 and "The user entitlement does not exist" in e.message \
                and max_attempt_execute_prompt_setup < 1:
                    max_attempt_execute_prompt_setup = max_attempt_execute_prompt_setup + 1
                    
                    data_marts = self._wos_client.data_marts.list().result
                    if (data_marts.data_marts is None) or (not data_marts.data_marts):
                        raise ValueError("Error retrieving IBM watsonx.governance (openscale) data mart. \
                                         Make sure the data mart are configured.")
                        
                    data_mart_id = data_marts.data_marts[0].metadata.id
                    
                    self._wos_client.wos.add_instance_mapping(
                        service_instance_id=data_mart_id,
                        space_id=self.space_id,
                        project_id=self.project_id)
                else:
                    max_attempt_execute_prompt_setup = 2
                    raise e

        generative_ai_monitor_details = generative_ai_monitor_details._to_dict()
            
        return {"prompt_template_asset_id": pta_id,
                "deployment_id": deployment_id,
                "subscription_id": generative_ai_monitor_details["subscription_id"]} 
        
                    
    def payload_logging(self, payload_records: List[dict], subscription_id: str) -> None:
        """Store records to payload logging.

        Args:
            payload_records (List[dict]): 
            subscription_id (str): 

        **Example**

        .. code-block:: python

            watsonx_monitor.payload_logging(payload_records=[{"context1": "value_context1",
                                                    "context2": "value_context1",
                                                    "input_query": "What's Labrador?",
                                                    "input_token_count": 25,
                                                    "generated_token_count": 150}], 
                                            subscription_id="5d62977c-a53d-4b6d-bda1-7b79b3b9d1a0")
        """
        from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
        from ibm_watson_openscale import APIClient as WosAPIClient
        from ibm_watson_openscale.supporting_classes.enums import (
            DataSetTypes,
            TargetTypes,
        )
        
        if not self._wos_client:
            try:
                if self._wos_cpd_creds:
                    from ibm_cloud_sdk_core.authenticators import (
                        CloudPakForDataAuthenticator,  # type: ignore
                    )
                    
                    authenticator = CloudPakForDataAuthenticator(**self._wos_cpd_creds)
                    
                    self._wos_client = WosAPIClient(authenticator=authenticator, 
                                                    service_url=self._wos_cpd_creds["url"])
                    
                else:
                    from ibm_cloud_sdk_core.authenticators import (
                        IAMAuthenticator,  # type: ignore
                    )
                    
                    authenticator = IAMAuthenticator(apikey=self._api_key)
                    self._wos_client = WosAPIClient(authenticator=authenticator, service_url=REGIONS_URL[self.region]["wos"])
                
            except Exception as e:
                logging.error(f"Error connecting to IBM watsonx.governance (openscale): {e}")
                raise
        
        subscription_details = self._wos_client.subscriptions.get(subscription_id).result
        subscription_details = json.loads(str(subscription_details))
            
        feature_fields = subscription_details["entity"]["asset_properties"]["feature_fields"]
            
        payload_data_set_id = self._wos_client.data_sets.list(type=DataSetTypes.PAYLOAD_LOGGING,
                                                              target_target_id=subscription_id, 
                                                              target_target_type=TargetTypes.SUBSCRIPTION).result.data_sets[0].metadata.id
            
        payload_data = _convert_payload_format(payload_records, feature_fields)
        self._wos_client.data_sets.store_records(data_set_id=payload_data_set_id, 
                                                 request_body=payload_data,
                                                 background_mode=False)
                  
                  