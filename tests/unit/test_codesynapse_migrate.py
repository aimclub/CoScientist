import asyncio

from CoScientist.integrations.codesynapse.migrate import apply_indexes


class _Collection:
    def __init__(self):
        self.calls = []

    async def create_index(self, keys, **kwargs):
        self.calls.append((keys, kwargs))


class _Database:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


def test_migration_creates_unique_identity_indexes_idempotently():
    async def scenario():
        database = _Database()
        await apply_indexes(database)
        await apply_indexes(database)

        run_indexes = database["integration_runs"].calls
        event_indexes = database["trace_outbox"].calls
        assert any(kwargs.get("unique") for _, kwargs in run_indexes)
        assert any(kwargs.get("unique") for _, kwargs in event_indexes)

    asyncio.run(scenario())
