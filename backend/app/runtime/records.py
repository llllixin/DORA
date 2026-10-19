"""Run event sinks; no raw requests, responses, credentials or hidden reasoning."""
def default_repository():
    from app.repository import Repository
    return Repository()


def append(repository, run_id, event):
    if repository is not None and repository.append_agent_run_event(run_id, event) is None:
        raise RuntimeError('runtime_run_missing')
