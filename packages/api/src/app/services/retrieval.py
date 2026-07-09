import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.sandbox.e2b import E2BSandboxSpec
from app.core.sandbox.factory import create_sandbox
from app.services.indexing import active_sandbox

log = logging.getLogger(__name__)


def _on_stdout(chunk: str) -> None:
    log.info(f"[stdout:retrieve_code_chunks]:{chunk}")


def _on_stderr(chunk: str) -> None:
    log.error(f"[stderr:retrieve_code_chunks]:{chunk}")


async def retrieve_code_chunks(
    *,
    query: str,
    repo_name: str,
    repo_id: str,
    user_id: str,
    limit: int = 20,
    spec: E2BSandboxSpec,
    session: AsyncSession,
):

    try:
        active_sb = await active_sandbox(
            session=session, user_id=user_id, repo_id=repo_id
        )
        if active_sb is None:
            raise Exception(f"NO ACTIVE SANDBOX FOR REPO:{repo_id}")

        sandbox = create_sandbox(
            spec=spec,
            user_id=user_id,
            repo_id=repo_id,
            sandbox_name=active_sb.sandbox_name,
        )

        connected_sandbox = await sandbox.connect(
            sandbox_id=active_sb.id,
            sandbox_name=active_sb.sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )

        search_command = (
            # f"cd /home/user/sentinel-workspace/context && "
            # f"LANCEDB_URI=/home/user/lance_data "
            # f'OPENAI_API_KEY="{settings.openai_api_key}" '
            f"PYTHONUNBUFFERED=1 python -u search.py "
            f'--repo-name "{repo_name}" '
            f'--query "{query}" '
            f"--limit {limit} "
        )

        envs = {
            "OPENAI_API_KEY": settings.openai_api_key,
            "LANCEDB_URI": "/home/user/lance_data",
        }

        search = await connected_sandbox.execute_streaming(
            search_command,
            cwd="/home/user/sentinel-workspace/context",
            on_stderr=_on_stderr,
            on_stdout=_on_stdout,
            envs=envs,
            timeout=20 * 60,
        )

        log.info(f"[retreive:error]:{search.error}")
        log.info(f"[retreive:result]:{search.stdout} \n [query]:{query}")
        return search.stdout

    except Exception as e:
        log.error(f"[FAILED TO RETREIVE]:{query}: \n [error]:{e}")
