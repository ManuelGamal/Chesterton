"""Real SandboxRunner backed by Nebius Token Factory Sandboxes (ConTree).

Verified against `contree-sdk` 0.3.6 by offline introspection on 2026-09-18.
An earlier version of this file was written from the plan's assumptions and was
wrong in three places — it imported a `contree_client` package that does not
exist, passed a client object to a constructor that takes `base_url`/`token`,
and treated `.uuid` as a string. None of that could be caught by the shape-only
tests, which is why the SDK surface is now pinned by a real-construction test.

Surface this file depends on (all confirmed present in 0.3.6):

    Contree(config=None, *, base_url=None, token=None)
        .images -> ImagesManager
    ImagesManager.use(ref: str | UUID | OCIReference, strict: bool = False)
    ImagesManager.oci(ref, *, tag=None, username=None, password=None, timeout=None)
    ContreeImage.run(command=None, *, shell=None, files=None, env=None, cwd=None,
                     tag=None, timeout=None, disposable=True, ...) -> ContreeImage
        .stdout .stderr .exit_code .elapsed .state  (properties)
        .uuid  -> uuid.UUID   (instance attribute, NOT a str)

Two shapes worth knowing. `run()` returns another `ContreeImage`, not a result
object — the image *is* the checkpoint, so runs chain. And `ContreeImage` is
awaitable (`__await__`), which is what makes `await image.run(...)` work even
though `run` is not itself a coroutine function.
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
        self._sdk = None

    def _handle(self):
        """The Contree client, built on first use.

        Lazy so that importing this module — and running every test that only
        checks its shape — does not require the sandbox extra.
        """
        if self._sdk is None:
            try:
                from contree_sdk import Contree
            except ImportError as exc:  # fail loudly, at first use, with a fix
                raise RuntimeError(_MISSING_SDK) from exc

            self._sdk = Contree(base_url=self.base_url, token=self.api_key)
        return self._sdk

    async def use_image(self, ref: str) -> str:
        sdk = self._handle()
        if ref.startswith("docker://"):
            image = await sdk.images.oci(ref)
        else:
            image = await sdk.images.use(ref)
        # .uuid is a uuid.UUID; the protocol promises a str.
        return str(image.uuid)

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str] | None = None,
        disposable: bool = True,
        tag: str | None = None,
    ) -> RunResult:
        sdk = self._handle()
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
            checkpoint_id=None if disposable else str(result.uuid),
        )

    async def aclose(self) -> None:
        """No-op against contree-sdk 0.3.6, which exposes no close/aclose.

        Kept because the protocol declares it and a future SDK may acquire
        one — consumers should not have to learn which implementation needs
        closing.
        """
        self._sdk = None
