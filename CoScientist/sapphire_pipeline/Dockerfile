FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY CoScientist/papers_processing_refactoring/requirements.txt /app/CoScientist/papers_processing_refactoring/requirements.txt
COPY CoScientist/sapphire_pipeline/requirements.txt /app/CoScientist/sapphire_pipeline/requirements.txt
RUN pip install --no-cache-dir -r CoScientist/sapphire_pipeline/requirements.txt

COPY CoScientist/papers_processing_refactoring /app/CoScientist/papers_processing_refactoring
COPY CoScientist/sapphire_pipeline /app/CoScientist/sapphire_pipeline
COPY CoScientist/paper_analysis/research_taxonomy.py /app/CoScientist/paper_analysis/research_taxonomy.py

RUN mkdir -p /app/data /app/data/papers && \
    chown -R 10001:10001 /app/data
USER 10001:10001

ENTRYPOINT ["python", "CoScientist/sapphire_pipeline/__main__.py"]
CMD ["--page-size", "100"]
