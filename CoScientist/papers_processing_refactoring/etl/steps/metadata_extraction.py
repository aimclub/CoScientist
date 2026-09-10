from langchain_core.messages import HumanMessage

from ..base import ETLStep
from ..context import ETLContext
from ...utils.general_utils import OpenAlexClassification, PaperMetadata
from ...utils.openalex import find_doi_by_title, get_openalex_domain_and_field
from ...utils.prompts import classification_from_content_prompt, metadata_extraction_prompt


class MetadataExtractionStep(ETLStep):
    """Extract paper metadata and classification without generating a summary."""

    name = "metadata_extraction"

    def run(self, ctx: ETLContext) -> None:
        article_id = ctx.article.id

        html = ctx.artifact_store.get_html(article_id, "image_captioning")
        if not html:
            raise RuntimeError(f"{self.name} step requires cleaned HTML")

        manifest_data = ctx.artifact_store.get_metadata(article_id, "image_captioning") or {}
        metadata_llm = ctx.llm.with_structured_output(PaperMetadata)
        paper_metadata: PaperMetadata = metadata_llm.invoke(
            [HumanMessage(content=metadata_extraction_prompt + html)]
        )

        doi = find_doi_by_title(
            paper_metadata.paper_title,
            paper_metadata.publication_year,
        )
        classification = get_openalex_domain_and_field(
            doi=doi,
            title=paper_metadata.paper_title,
            publication_year=paper_metadata.publication_year,
        )
        if classification is None:
            classification_llm = ctx.llm.with_structured_output(OpenAlexClassification)
            llm_classification: OpenAlexClassification = classification_llm.invoke(
                [
                    HumanMessage(
                        content=classification_from_content_prompt.format(
                            TITLE=paper_metadata.paper_title,
                            ARTICLE_CONTENT=html,
                        )
                    )
                ]
            )
            domain = llm_classification.primary_domain
            field = llm_classification.primary_field
        else:
            domain, field = classification

        manifest_data["paper_metadata"] = {
            **paper_metadata.model_dump(),
            "doi": doi or "unknown",
            "domain": domain,
            "field": field,
        }
        manifest_data["paper_of_file_name"] = ctx.article.name
        manifest_data["article_metadata"] = ctx.article.metadata

        ctx.artifact_store.put_html(article_id, self.name, html)
        ctx.artifact_store.put_metadata(article_id, self.name, manifest_data)
