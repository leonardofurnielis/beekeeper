from typing import List, Any, Optional
from spyder_index.core.document import Document
from spyder_index.core.embeddings import BaseEmbedding, Embedding

from pydantic.v1 import BaseModel, PrivateAttr


class WatsonxEmbedding(BaseModel, BaseEmbedding):
    """IBM watsonx embedding models.

    Note:
            One of these parameters is required: ``project_id`` or ``space_id``.

    See https://cloud.ibm.com/apidocs/watsonx-ai#endpoint-url for the watsonx.ai API endpoints.

    Args:
        model_name (str): IBM watsonx.ai model to be used. Defaults to ``ibm/slate-30m-english-rtrvr``.
        api_key (str): API Key for accessing IBM watsonx.ai.
        url (str): Service instance url.
        truncate_input_tokens (str): Maximum number of input tokens accepted. Defaults to ``512``
        project_id (str, optional): ID of the watsonx.ai project.
        space_id (str, optional): ID of the watsonx.ai space.
    """

    model_name: str = "ibm/slate-30m-english-rtrvr"
    api_key: str
    url: str
    truncate_input_tokens: int = 512
    project_id: Optional[str] = None
    space_id: Optional[str] = None

    _client: Any = PrivateAttr()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        try:
            from ibm_watsonx_ai import Credentials
            from ibm_watsonx_ai.foundation_models import Embeddings as WatsonxEmbeddings

        except ImportError:
            raise ImportError("ibm-watsonx-ai package not found, please install it with `pip install ibm-watsonx-ai`")

        if not self.project_id and not self.space_id:
            raise ValueError("Must provide one of these parameters [`project_id`, `space_id`]")

        kwargs_params = {
            "model_id": self.model_name,
            "params": {"truncate_input_tokens": self.truncate_input_tokens, "return_options": {"input_text": False}},
            "credentials": Credentials(api_key=self.api_key, url=self.url)
        }

        if self.project_id:
            kwargs_params["project_id"] = self.project_id
        else:
            kwargs_params["space_id"] = self.space_id

        self._client = WatsonxEmbeddings(**kwargs_params)

    def get_query_embedding(self, query: str) -> Embedding:
        """Compute embedding for a text.

        Args:
            query (str): Input query to compute embedding.

        A way you may use:
        >>> from spyder_index.embeddings import WatsonxEmbedding
        >>> text = "A python data library for building AI applications"
        >>> watsonx_embed = WatsonxEmbedding(api_key="<you_api_key>",
        >>>                                  url="https://us-south.ml.cloud.ibm.com",
        >>>                                  project_id="<your_project_id>")
        >>> embeddings = watsonx_embed.get_query_embedding(text)
        """
        embedding_text = self.get_texts_embedding([query])[0]

        return embedding_text

    def get_texts_embedding(self, texts: List[str]) -> List[Embedding]:
        """Compute embeddings for list of texts.

        Args:
            texts (List[str]): List of text to compute embeddings.
        """
        embedding_texts = self._client.embed_documents(texts)

        return embedding_texts

    def get_documents_embedding(self, documents: List[Document]) -> List[Embedding]:
        """Compute embeddings for a list of documents.

        Args:
            documents (List[Document]): List of `Document` objects to compute embeddings.
        """

        texts = [document.get_content() for document in documents]
        embedding_documents = self.get_texts_embedding(texts)

        return embedding_documents
