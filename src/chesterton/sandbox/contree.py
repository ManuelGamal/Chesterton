"""Real SandboxRunner backed by Nebius Token Factory Sandboxes (ConTree).

The SDK is young and its surface is unverified against the live service. If it
shifts, change only this file — the protocol is the stable boundary.
"""

from __future__ import annotations

from collections.abc import Mapping

from chesterton.sandbox.protocol import RunResult

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes"

_MISSING_SDK = (
    "contree-sdk is not installed. Install the sandbox extra with "
    'pip install -e ".[sandbox]" before using ConTreeSandboxRunner.'
)


class ConTreeSandboxRunner:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self._client = None
        self._sdk = None

    async def _sdk_handle(self):
        if self._sdk is None:
            try:
                from contree_client.httpx import ContreeAsyncClient
                from contree_sdk import Contree
            except ImportError as exc:  # fail loudly, at first use, with a fix
                raise RuntimeError(_MISSING_SDK) from exc

            self._client = ContreeAsyncClient(
                self.api_key, base_url=self.base_url, timeout=120.0
            )
            self._sdk = Contree(self._client)
        return self._sdk

    async def use_image(self, ref: str) -> str:
        sdk = await self._sdk_handle()
        if ref.startswith("docker://"):
            image = await sdk.images.oci(ref)
        else:
            image = await sdk.images.use(ref)
        return image.uuid

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str] | None = None,
        disposable: bool = True,
        tag: str | None = None,
    ) -> RunResult:
        sdk = await self._sdk_handle()
        image = await sdk.images.use(checkpoint_id)
        result = await image.run(
            shell=shell,
            files=dict(files) if files else None,
            disposable=disposable,
            tag=tag,
        )
        # A disposable run persists nothing, so there is no id to fork from.
        # Reporting result.uuid here would let offline code depend on
        # something the fake cannot honestly provide.
        return RunResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            checkpoint_id=None if disposable else result.uuid,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._sdk = None
