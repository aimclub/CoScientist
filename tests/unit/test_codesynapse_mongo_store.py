import asyncio

from CoScientist.integrations.codesynapse.models import IntegrationRun, TraceEvent
from CoScientist.integrations.codesynapse.mongo_store import MongoIntegrationStore


class _Result:
    def __init__(self, inserted_id=True):
        self.inserted_id = inserted_id


class _Collection:
    def __init__(self):
        self.documents = []

    async def insert_one(self, document):
        self.documents.append(dict(document))
        return _Result()

    async def find_one(self, query):
        return next((item for item in self.documents if all(item.get(k) == v for k, v in query.items())), None)

    async def replace_one(self, query, document, upsert=False):
        self.documents[:] = [item for item in self.documents if not all(item.get(k) == v for k, v in query.items())]
        self.documents.append(dict(document))
        return _Result()


class _Database:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


def test_mongo_store_persists_run_and_idempotently_accepts_duplicate_event():
    async def scenario():
        store = MongoIntegrationStore(_Database())
        run = IntegrationRun(external_run_id="external-1", tenant_id="tenant-1", project_id="project-1")
        await store.create_run(run)
        assert (await store.get_run("external-1")).project_id == "project-1"

        event = TraceEvent(event_id="event-1", run_id="run-1", sequence=1, tenant_id="tenant-1", project_id="project-1", type="run.started")
        assert await store.append_event(event)
        assert not await store.append_event(event)

    asyncio.run(scenario())
